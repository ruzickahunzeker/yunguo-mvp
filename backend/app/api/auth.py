import secrets
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select
from app.api.deps import DB, CurrentUser
from app.core.security import hash_password, verify_password, token_for
from app.core.rate_limit import limit
from app.models import User, Wallet
from app.schemas.requests import Register, Login, Profile, PasswordChange, ForgotPassword, ResetPassword, VerifyEmail
from app.core.config import get_settings
from app.core.security import digest
from app.services.password_reset import issue_reset, consume_reset, NEUTRAL_MESSAGE
from app.repositories.queries import row
from app.services.email_verification import issue_verification, consume_verification
from app.services.accounts import locked_account
from app.services.commerce import audit

router = APIRouter(prefix='/auth', tags=['身份认证'])
# A real hash equalizes work for unknown emails without persisting a dummy account.
DUMMY_HASH = hash_password(secrets.token_urlsafe(32))

def public_user(user):
    return row(user, ('password_hash', 'token_version'))

@router.post('/register', status_code=201)
def register(payload: Register, request: Request, db: DB):
    limit(request, 'register', 5)
    email = str(payload.email).lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, '邮箱已被使用')
    user = User(email=email, name=payload.name, password_hash=hash_password(payload.password), role='user')
    db.add(user)
    db.flush()
    db.add(Wallet(user_id=user.id))
    if get_settings().email_verification_enabled:
        issue_verification(db, user)
    db.commit()
    return {'user': public_user(user), 'access_token': token_for(user), 'token_type': 'bearer'}

@router.post('/login')
def login(payload: Login, request: Request, db: DB):
    limit(request, 'login', 10, 300)
    email = str(payload.email).lower()
    limit(request, f'login.account:{digest(email)}', 20, 900, per_client=False)
    user = db.scalar(select(User).where(User.email == email))
    valid = verify_password(payload.password, user.password_hash if user else DUMMY_HASH)
    if not valid or not user or not user.active:
        raise HTTPException(401, '邮箱或密码错误，或账号已停用')
    return {'user': public_user(user), 'access_token': token_for(user), 'token_type': 'bearer'}

@router.get('/me')
def me(user: CurrentUser):
    return public_user(user)

@router.patch('/me')
def profile(payload: Profile, user: CurrentUser, db: DB):
    user = locked_account(db, user)
    user.name = payload.name
    audit(db, user, 'auth.profile-updated', user.id, 'Display name updated')
    db.commit()
    return public_user(user)

@router.post('/password')
def change_password(payload: PasswordChange, user: CurrentUser, db: DB, request: Request):
    limit(request, 'password.change', 10, 300)
    limit(request, f'password.change.user:{user.id}', 5, 300, per_client=False)
    user = locked_account(db, user)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, '原密码错误')
    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1
    audit(db, user, 'auth.password-changed', user.id, 'Password changed; prior sessions revoked')
    db.commit()
    return {'message': '密码已修改，请重新登录'}

@router.post('/logout')
def logout(user: CurrentUser, db: DB):
    user = locked_account(db, user)
    user.token_version += 1
    audit(db, user, 'auth.logout', user.id, 'All prior sessions revoked')
    db.commit()
    return {'message': '所有登录会话已退出'}


@router.get('/features')
def features():
    settings = get_settings()
    return {'password_reset_enabled': settings.password_reset_enabled,
        'email_verification_enabled': settings.email_verification_enabled,
        'require_verified_email_for_purchase': settings.require_verified_email_for_purchase}

@router.post('/forgot-password', status_code=202)
def forgot_password(payload: ForgotPassword, request: Request, db: DB):
    limit(request, 'password-reset.request', 5, 300)
    limit(request, 'password-reset.email:' + digest(str(payload.email).lower()), 3, 900, per_client=False)
    if not get_settings().password_reset_enabled:
        raise HTTPException(503, '邮件找回暂未配置，请联系管理员核验身份')
    issue_reset(db, str(payload.email))
    db.commit()
    return {'message': NEUTRAL_MESSAGE}

@router.post('/reset-password')
def reset_password(payload: ResetPassword, request: Request, db: DB):
    limit(request, 'password-reset.consume', 10, 300)
    if not get_settings().password_reset_enabled:
        raise HTTPException(503, '邮件找回暂未配置，请联系管理员核验身份')
    consume_reset(db, payload.token, payload.new_password)
    db.commit()
    return {'message': '密码已重置，请使用新密码重新登录'}


@router.post('/verification/request', status_code=202)
def request_verification(user: CurrentUser, request: Request, db: DB):
    limit(request, 'email-verification.request', 5, 300)
    limit(request, f'email-verification.user:{user.id}', 3, 900, per_client=False)
    if not get_settings().email_verification_enabled:
        raise HTTPException(503, '邮箱验证暂未配置，请联系管理员')
    queued = issue_verification(db, user)
    db.commit()
    return {'message': '验证邮件已进入发送队列，请检查收件箱和垃圾邮件' if queued else '邮箱已验证，无需重复发送'}

@router.post('/verify-email')
def verify_email(payload: VerifyEmail, request: Request, db: DB):
    limit(request, 'email-verification.consume', 10, 300)
    if not get_settings().email_verification_enabled:
        raise HTTPException(503, '邮箱验证暂未配置，请联系管理员')
    consume_verification(db, payload.token)
    db.commit()
    return {'message': '邮箱验证成功，你可以返回账号继续使用'}
