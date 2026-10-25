import hashlib
import hmac
from datetime import timedelta
import jwt
from pwdlib import PasswordHash
from app.core.config import get_settings
from app.models.entities import now

password_hasher = PasswordHash.recommended()

def hash_password(value: str):
    return password_hasher.hash(value)

def verify_password(value: str, hashed: str):
    return password_hasher.verify(value, hashed)

def digest(value: str):
    return hmac.new(get_settings().code_pepper.encode(), value.encode(), hashlib.sha256).hexdigest()

def token_for(user):
    settings = get_settings()
    return jwt.encode({'sub': str(user.id), 'ver': user.token_version, 'exp': now() + timedelta(minutes=settings.token_minutes)}, settings.jwt_secret, algorithm='HS256')
