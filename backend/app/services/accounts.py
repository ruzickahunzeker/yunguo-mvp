"""Recheck authenticated account state under lock before account mutations."""
from fastapi import HTTPException
from sqlalchemy import select
from app.models import User

def locked_account(db, user):
    original_version = user.token_version
    current = db.scalar(select(User).where(User.id == user.id)
        .with_for_update(key_share=True).execution_options(populate_existing=True))
    if not current or not current.active or current.token_version != original_version:
        raise HTTPException(401, '账号或登录会话已变化，请重新登录')
    return current
