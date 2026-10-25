import secrets
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select, update
from app.core.config import get_settings
from app.core.security import digest, hash_password
from app.models import PasswordResetToken, User, AuditLog, now

NEUTRAL_MESSAGE = '如果该邮箱对应有效账号，你将收到密码重置邮件，请检查收件箱和垃圾邮件。'
INVALID_MESSAGE = '重置链接无效或已过期，请重新申请'

def raw_token(record):
    # Domain separation: DB contains only identifier and HMAC hash. Worker can
    # reconstruct the high-entropy credential without storing tokens/email bodies.
    return digest(f'password-reset:v1:{record.id}:{record.user_id}:{record.auth_version}')

def issue_reset(db, email):
    user = db.scalar(select(User).where(User.email == email.lower()).with_for_update())
    if not user or not user.active:
        return
    # One pending/sent credential per account. Re-issuing invalidates old links.
    db.execute(update(PasswordResetToken).where(PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None)).values(used_at=now(), delivery_status='CANCELED'))
    record = PasswordResetToken(id=secrets.token_hex(16), user_id=user.id,
        auth_version=user.token_version, expires_at=now()+timedelta(minutes=get_settings().password_reset_minutes), token_hash='')
    record.token_hash = digest(raw_token(record))
    db.add(record)

def consume_reset(db, token, new_password):
    record = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == digest(token)))
    if not record:
        raise HTTPException(400, INVALID_MESSAGE)
    # User -> reset record lock order matches issuance. Refresh any cached identity.
    user = db.scalar(select(User).where(User.id == record.user_id).with_for_update().execution_options(populate_existing=True))
    if not user or not user.active or user.token_version != record.auth_version:
        raise HTTPException(400, INVALID_MESSAGE)
    claimed = db.execute(update(PasswordResetToken).where(PasswordResetToken.id == record.id,
        PasswordResetToken.used_at.is_(None), PasswordResetToken.expires_at > now())
        .values(used_at=now(), delivery_status='CANCELED').execution_options(synchronize_session='fetch')
        .returning(PasswordResetToken.id)).scalar_one_or_none()
    if not claimed:
        raise HTTPException(400, INVALID_MESSAGE)
    user.password_hash = hash_password(new_password)
    user.token_version += 1
    db.execute(update(PasswordResetToken).where(PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None)).values(used_at=now(), delivery_status='CANCELED'))
    db.add(AuditLog(actor_id=user.id, action='auth.password-reset', target=str(user.id), detail='Email reset credential consumed; all sessions revoked'))
