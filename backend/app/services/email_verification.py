import secrets
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select, update
from app.core.config import get_settings
from app.core.security import digest
from app.models import EmailVerificationToken, User, AuditLog, now

INVALID_MESSAGE = '验证链接无效或已过期，请登录后重新申请'

def raw_token(record):
    return digest(f'email-verification:v1:{record.id}:{record.user_id}:{record.auth_version}:{record.email_hash}')

def eligible(user, record):
    return bool(user and user.active and user.token_version == record.auth_version
        and user.email_verified_at is None and digest(user.email.lower()) == record.email_hash)

def issue_verification(db, user):
    original_version = user.token_version
    user = db.scalar(select(User).where(User.id == user.id).with_for_update(key_share=True).execution_options(populate_existing=True))
    if not user or not user.active or user.token_version != original_version:
        raise HTTPException(401, '账号或登录会话已变化，请重新登录')
    if user.email_verified_at:
        return False
    db.execute(update(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id,
        EmailVerificationToken.used_at.is_(None)).values(used_at=now(), delivery_status='CANCELED'))
    record = EmailVerificationToken(id=secrets.token_hex(16), user_id=user.id,
        auth_version=user.token_version, email_hash=digest(user.email.lower()),
        expires_at=now()+timedelta(minutes=get_settings().email_verification_minutes), token_hash='')
    record.token_hash = digest(raw_token(record))
    db.add(record)
    return True

def consume_verification(db, token):
    record = db.scalar(select(EmailVerificationToken).where(EmailVerificationToken.token_hash == digest(token)))
    if not record:
        raise HTTPException(400, INVALID_MESSAGE)
    user = db.scalar(select(User).where(User.id == record.user_id).with_for_update(key_share=True).execution_options(populate_existing=True))
    if not eligible(user, record):
        raise HTTPException(400, INVALID_MESSAGE)
    claimed = db.execute(update(EmailVerificationToken).where(EmailVerificationToken.id == record.id,
        EmailVerificationToken.used_at.is_(None), EmailVerificationToken.expires_at > now())
        .values(used_at=now(), delivery_status='CANCELED').execution_options(synchronize_session='fetch')
        .returning(EmailVerificationToken.id)).scalar_one_or_none()
    if not claimed:
        raise HTTPException(400, INVALID_MESSAGE)
    user.email_verified_at = now()
    db.execute(update(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id,
        EmailVerificationToken.used_at.is_(None)).values(used_at=now(), delivery_status='CANCELED'))
    db.add(AuditLog(actor_id=user.id, action='auth.email-verified', target=str(user.id), detail='Single-use email ownership credential consumed'))
