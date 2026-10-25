from datetime import datetime, timezone
from sqlalchemy import String, Integer, BigInteger, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, CheckConstraint, Index, Identity
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

def now():
    return datetime.now(timezone.utc)

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class Role(Base):
    __tablename__ = 'roles'
    name: Mapped[str] = mapped_column(String(20), primary_key=True)
    label: Mapped[str] = mapped_column(String(50))

class User(TimestampMixin, Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(80), default='')
    role: Mapped[str] = mapped_column(ForeignKey('roles.name'), default='user')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(default=0)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Product(TimestampMixin, Base):
    __tablename__ = 'products'
    __table_args__ = (CheckConstraint('price >= 0 AND original_price >= 0 AND stock >= 0', name='ck_product_values'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default='')
    category: Mapped[str] = mapped_column(String(60), default='数字服务')
    original_price: Mapped[int] = mapped_column(BigInteger)
    price: Mapped[int] = mapped_column(BigInteger)
    stock: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(default=0)

class ProductPrice(Base):
    __tablename__ = 'product_prices'
    __table_args__ = (UniqueConstraint('product_id', 'role', name='uq_product_role'), CheckConstraint('price >= 0', name='ck_agent_price'))
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'))
    role: Mapped[str] = mapped_column(ForeignKey('roles.name'))
    price: Mapped[int] = mapped_column(BigInteger)

class Wallet(TimestampMixin, Base):
    __tablename__ = 'wallets'
    __table_args__ = (CheckConstraint('balance >= 0 AND frozen >= 0', name='ck_wallet_nonnegative'),)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    frozen: Mapped[int] = mapped_column(BigInteger, default=0)

class Order(TimestampMixin, Base):
    __tablename__ = 'orders'
    __table_args__ = (
        UniqueConstraint('user_id', 'idempotency_key', name='uq_order_request'),
        CheckConstraint('amount >= 0', name='ck_order_amount'),
        CheckConstraint("payment_status IN ('PAID','REFUNDED')", name='ck_payment_state'),
        CheckConstraint("fulfillment_status IN ('QUEUED','PROCESSING','COMPLETED','FAILED','CANCELED')", name='ck_fulfillment_state'),
        CheckConstraint("source IN ('wallet','code')", name='ck_order_source'),
        Index('ix_order_user_created', 'user_id', 'created_at'),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'))
    product_name: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(BigInteger)
    payment_status: Mapped[str] = mapped_column(String(20), default='PAID')
    fulfillment_status: Mapped[str] = mapped_column(String(20), default='QUEUED', index=True)
    idempotency_key: Mapped[str] = mapped_column(String(80))
    lookup_hash: Mapped[str] = mapped_column(String(64))
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class RedeemCode(TimestampMixin, Base):
    __tablename__ = 'redeem_codes'
    __table_args__ = (CheckConstraint("status IN ('UNUSED','USED','VOID')", name='ck_code_status'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    suffix: Mapped[str] = mapped_column(String(6))
    batch_id: Mapped[str] = mapped_column(String(40), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default='UNUSED', index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey('orders.id'), nullable=True, unique=True)
    request_key: Mapped[str | None] = mapped_column(String(80), nullable=True)

class WalletTransaction(Base):
    __tablename__ = 'wallet_transactions'
    __table_args__ = (CheckConstraint('balance_after >= 0 AND frozen_after >= 0', name='ck_ledger_nonnegative'), Index('ix_ledger_user_time', 'user_id', 'created_at'))
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('wallets.user_id'))
    amount: Mapped[int] = mapped_column(BigInteger)
    frozen_delta: Mapped[int] = mapped_column(BigInteger, default=0)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    frozen_after: Mapped[int] = mapped_column(BigInteger, default=0)
    kind: Mapped[str] = mapped_column(String(30))
    reference: Mapped[str] = mapped_column(String(160), unique=True)
    note: Mapped[str] = mapped_column(String(200), default='')
    order_id: Mapped[str | None] = mapped_column(ForeignKey('orders.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class OrderEvent(Base):
    __tablename__ = 'order_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('orders.id'), index=True)
    action: Mapped[str] = mapped_column(String(50))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    note: Mapped[str] = mapped_column(String(500), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class FulfillmentJob(TimestampMixin, Base):
    __tablename__ = 'fulfillment_jobs'
    __table_args__ = (CheckConstraint('attempts >= 0 AND attempts <= 3', name='ck_job_attempts'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('orders.id'), unique=True)
    state: Mapped[str] = mapped_column(String(20), default='QUEUED', index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(100))
    detail: Mapped[str] = mapped_column(String(500), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

class WorkerHeartbeat(Base):
    __tablename__ = 'worker_heartbeats'
    service: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class MonitorState(Base):
    __tablename__ = 'monitor_state'
    __table_args__ = (CheckConstraint('id = 1', name='ck_monitor_singleton'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    first_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class OperationalAlert(Base):
    __tablename__ = 'operational_alerts'
    __table_args__ = (
        UniqueConstraint('code', 'scope', name='uq_alert_rule_scope'),
        CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','RESOLVED')", name='ck_alert_status'),
        CheckConstraint("severity IN ('info','warning')", name='ck_alert_severity'),
        CheckConstraint('occurrences >= 1 AND count >= 0', name='ck_alert_counts'),
        Index('ix_alert_status_seen', 'status', 'last_seen_at'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(30), default='platform')
    severity: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default='OPEN')
    count: Mapped[int] = mapped_column(default=0)
    occurrences: Mapped[int] = mapped_column(default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class AlertEvent(Base):
    __tablename__ = 'alert_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey('operational_alerts.id'), index=True)
    action: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    note: Mapped[str] = mapped_column(String(200), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Agent(TimestampMixin, Base):
    __tablename__ = 'agents'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    level_id: Mapped[int] = mapped_column(ForeignKey('agent_levels.id'), default=1, index=True)

class AgentRelation(Base):
    __tablename__ = 'agent_relations'
    __table_args__ = (CheckConstraint('parent_id != child_id', name='ck_no_self_agent'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey('agents.user_id'))
    child_id: Mapped[int] = mapped_column(ForeignKey('agents.user_id'), unique=True)

class Payment(TimestampMixin, Base):
    __tablename__ = 'payments'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    provider: Mapped[str] = mapped_column(String(30), default='demo')
    external_id: Mapped[str] = mapped_column(String(160), unique=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default='PAID')
    __table_args__ = (CheckConstraint('amount > 0', name='ck_payment_amount'),)

class SystemSetting(Base):
    __tablename__ = 'system_settings'
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))

class PasswordResetToken(Base):
    """Single-use credentials and durable SMTP delivery state; no plaintext token/body."""
    __tablename__ = 'password_reset_tokens'
    __table_args__ = (
        CheckConstraint("delivery_status IN ('QUEUED','SENT','FAILED','CANCELED')", name='ck_reset_delivery_status'),
        CheckConstraint('attempts >= 0 AND attempts <= 3', name='ck_reset_delivery_attempts'),
        Index('ix_reset_delivery', 'delivery_status', 'next_attempt_at'),
        Index('ix_reset_user_created', 'user_id', 'created_at'),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    auth_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(20), default='QUEUED')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_error: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentLevel(TimestampMixin, Base):
    __tablename__ = 'agent_levels'
    id: Mapped[int] = mapped_column(Integer, Identity(start=2), primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)

class AgentLevelPrice(TimestampMixin, Base):
    __tablename__ = 'agent_level_prices'
    __table_args__ = (UniqueConstraint('level_id', 'product_id', name='uq_level_product_price'),
        CheckConstraint('price >= 0', name='ck_level_product_price'))
    id: Mapped[int] = mapped_column(primary_key=True)
    level_id: Mapped[int] = mapped_column(ForeignKey('agent_levels.id'))
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'))
    price: Mapped[int] = mapped_column(BigInteger)

class AgentProductRule(TimestampMixin, Base):
    __tablename__ = 'agent_product_rules'
    __table_args__ = (UniqueConstraint('agent_id', 'product_id', name='uq_agent_product_rule'),
        CheckConstraint('price IS NULL OR price >= 0', name='ck_agent_override_price'))
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey('agents.user_id'))
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'))
    price: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)


class EmailVerificationToken(Base):
    __tablename__ = 'email_verification_tokens'
    __table_args__ = (
        CheckConstraint("delivery_status IN ('QUEUED','SENT','FAILED','CANCELED')", name='ck_verification_delivery_status'),
        CheckConstraint('attempts >= 0 AND attempts <= 3', name='ck_verification_delivery_attempts'),
        Index('ix_verification_delivery', 'delivery_status', 'next_attempt_at'),
        Index('ix_verification_user_created', 'user_id', 'created_at'),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    auth_version: Mapped[int] = mapped_column(Integer)
    email_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(20), default='QUEUED')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_error: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
