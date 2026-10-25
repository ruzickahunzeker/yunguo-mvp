from typing import Annotated
import jwt
from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.config import get_settings
from app.models import User

DB = Annotated[Session, Depends(get_db)]
bearer = HTTPBearer(auto_error=False)

def current_user(db: DB, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    try:
        if not credentials:
            raise ValueError()
        claims = jwt.decode(credentials.credentials, get_settings().jwt_secret, algorithms=['HS256'], options={'require': ['exp', 'sub', 'ver']})
        user = db.get(User, int(claims['sub']))
        if not user or not user.active or user.token_version != claims['ver']:
            raise ValueError()
        return user
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise HTTPException(401, '登录已失效，请重新登录', headers={'WWW-Authenticate': 'Bearer'})

CurrentUser = Annotated[User, Depends(current_user)]

def admin_user(user: CurrentUser):
    if user.role != 'admin':
        raise HTTPException(403, '需要管理员权限')
    return user
Admin = Annotated[User, Depends(admin_user)]

def agent_user(user: CurrentUser):
    if user.role not in ('agent', 'admin'):
        raise HTTPException(403, '需要代理权限')
    return user
AgentUser = Annotated[User, Depends(agent_user)]

def idempotency_key(value: Annotated[str, Header(alias='Idempotency-Key', min_length=16, max_length=80)]):
    if not all(c.isalnum() or c in '-_' for c in value) or not value.isascii():
        raise HTTPException(422, '幂等键须为16–80位ASCII字母、数字、下划线或短横线')
    return value
Key = Annotated[str, Depends(idempotency_key)]
