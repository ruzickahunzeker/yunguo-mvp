from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit
from pydantic import model_validator, Field, SecretStr, EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_env: Literal['development', 'test', 'production'] = 'development'
    database_url: str = 'sqlite:///./yunguo.db'
    jwt_secret: str
    code_pepper: str
    redis_url: str = ''
    demo_recharge_enabled: bool = False
    fulfillment_mode: Literal['mock', 'manual', 'authorized'] = 'manual'
    fulfillment_provider_url: str = ''
    fulfillment_provider_token: SecretStr = SecretStr('')
    fulfillment_webhook_secret: SecretStr = SecretStr('')
    mock_direct_topup_enabled: bool = False
    cors_origins: list[str] = ['http://localhost:5173']
    token_minutes: int = 60
    monitor_enabled: bool = True
    monitor_interval_seconds: int = Field(default=15, ge=5, le=300)
    worker_heartbeat_seconds: int = Field(default=10, ge=5, le=60)
    worker_stale_seconds: int = Field(default=60, ge=30, le=600)
    monitor_stale_minutes: int = Field(default=30, ge=1, le=10080)
    trust_proxy: bool = False
    password_reset_enabled: bool = False
    email_verification_enabled: bool = False
    require_verified_email_for_purchase: bool = False
    email_verification_minutes: int = Field(default=60, ge=5, le=1440)
    public_base_url: str = 'http://localhost:5173'
    smtp_host: str = ''
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ''
    smtp_password: SecretStr = SecretStr('')
    smtp_security: Literal['starttls', 'ssl', 'none'] = 'starttls'
    smtp_from: EmailStr = 'noreply@example.com'
    password_reset_minutes: int = Field(default=20, ge=5, le=60)

    @model_validator(mode='after')
    def secure_config(self):
        if self.worker_stale_seconds < max(self.worker_heartbeat_seconds * 3, self.monitor_interval_seconds * 2):
            raise ValueError('Worker stale timeout must cover heartbeat and monitor intervals')
        for value in (self.jwt_secret, self.code_pepper):
            if len(value) < 32 or value.startswith('replace-'):
                raise ValueError('Set independent random JWT_SECRET and CODE_PEPPER (32+ characters)')
        if self.jwt_secret == self.code_pepper:
            raise ValueError('JWT_SECRET and CODE_PEPPER must differ')
        if self.app_env == 'production':
            if self.demo_recharge_enabled or self.mock_direct_topup_enabled or not self.redis_url or not self.database_url.startswith('postgresql'):
                raise ValueError('Production requires PostgreSQL, Redis, and disabled demo recharge')
            if self.fulfillment_mode == 'mock':
                raise ValueError('Production cannot use mock fulfillment; use manual or a contracted authorized provider')
            if self.fulfillment_mode == 'authorized':
                provider = urlsplit(self.fulfillment_provider_url)
                token = self.fulfillment_provider_token.get_secret_value()
                webhook_secret = self.fulfillment_webhook_secret.get_secret_value()
                if not (self.fulfillment_provider_url and provider.scheme == 'https' and provider.netloc
                        and not provider.username and not provider.password and not provider.query and not provider.fragment
                        and len(token) >= 32 and len(webhook_secret) >= 32):
                    raise ValueError('Authorized fulfillment requires a clean HTTPS provider URL and 32+ character token/webhook secret')
        if self.require_verified_email_for_purchase and not self.email_verification_enabled:
            raise ValueError('Purchase verification requires EMAIL_VERIFICATION_ENABLED')
        if self.password_reset_enabled or self.email_verification_enabled:
            url = urlsplit(self.public_base_url)
            if not self.smtp_host or url.scheme not in ('https', 'http') or not url.netloc or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
                raise ValueError('Email features require SMTP_HOST and PUBLIC_BASE_URL origin')
            if bool(self.smtp_username) != bool(self.smtp_password.get_secret_value()):
                raise ValueError('SMTP username and password must be provided together')
            if self.app_env == 'production' and (url.scheme != 'https' or self.smtp_security == 'none'):
                raise ValueError('Production email requires HTTPS and encrypted SMTP')
        return self

@lru_cache
def get_settings():
    return Settings()
