"""Transaction-scoped operations. Callers commit once, after audit/event/ledger writes."""
import secrets
from datetime import timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select, update, delete
from app.models import (User, Product, ProductPrice, Wallet, WalletTransaction, Order, OrderEvent,
    RedeemCode, FulfillmentJob, FulfillmentCheck, AuditLog, Payment, SystemSetting, now)
from app.core.security import digest
from app.core.config import get_settings
from app.repositories.queries import required
from app.services.pricing import agent_context, quote_for, assert_confirmed


def audit(db, actor, action, target, detail=''):
    db.add(AuditLog(actor_id=actor.id, action=action, target=str(target), detail=detail))

def enabled(db, key):
    setting = db.get(SystemSetting, key)
    if setting and setting.value != 'true':
        raise HTTPException(409, '业务暂时关闭，请稍后重试')

def move_wallet(db, user_id, amount, reference, kind, note='', order_id=None, frozen_delta=0):
    existing = db.scalar(select(WalletTransaction).where(WalletTransaction.reference == reference))
    if existing:
        if (existing.user_id, existing.amount, existing.frozen_delta, existing.kind, existing.note, existing.order_id) != (user_id, amount, frozen_delta, kind, note, order_id):
            raise HTTPException(409, '幂等键已用于不同请求')
        return existing
    value = db.execute(update(Wallet).where(Wallet.user_id == user_id,
        Wallet.balance + amount >= 0, Wallet.frozen + frozen_delta >= 0).values(
        balance=Wallet.balance + amount, frozen=Wallet.frozen + frozen_delta).returning(Wallet.balance, Wallet.frozen)).first()
    if value is None:
        raise HTTPException(409, '钱包可用余额或冻结余额不足')
    entry = WalletTransaction(user_id=user_id, amount=amount, frozen_delta=frozen_delta,
        balance_after=value.balance, frozen_after=value.frozen, reference=reference, kind=kind, note=note, order_id=order_id)
    db.add(entry)
    db.flush()
    return entry

def proof(order, key):
    # Reconstructable only with the same high-entropy client idempotency key.
    return digest(f'lookup:{order.id}:{key}')

def result(order, key):
    created_at = order.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return {'order_id': order.id, 'lookup_token': proof(order, key),
            'payment_status': order.payment_status, 'fulfillment_status': order.fulfillment_status,
            'product_name': order.product_name, 'product_sku': order.product_sku,
            'subscription_months': order.subscription_months, 'amount': order.amount, 'created_at': created_at.isoformat()}

def new_order(db, product, source, amount, key, user_id=None):
    order = Order(id='YG' + secrets.token_hex(16), user_id=user_id, product_id=product.id,
        product_name=product.name, product_sku=product.sku, product_description=product.description,
        subscription_months=product.subscription_months, source=source, amount=amount, idempotency_key=key, lookup_hash='',
        verification_required=product.verification_required)
    order.lookup_hash = digest(proof(order, key))
    db.add(order)
    db.flush()
    db.add(FulfillmentJob(order_id=order.id))
    db.add(OrderEvent(order_id=order.id, action='created', actor_id=user_id, note=source))
    return order

def purchase(db, user, product_id, key, expected_amount):
    original_version = user.token_version
    user = db.scalar(select(User).where(User.id == user.id).with_for_update(key_share=True).execution_options(populate_existing=True))
    if not user or not user.active or user.token_version != original_version:
        raise HTTPException(401, '账号或登录会话已变化，请重新登录')
    previous = db.scalar(select(Order).where(Order.user_id == user.id, Order.idempotency_key == key))
    if previous:
        if previous.product_id != product_id or previous.source != 'wallet' or previous.amount != expected_amount:
            raise HTTPException(409, '幂等键已用于不同请求')
        return result(previous, key)
    if get_settings().require_verified_email_for_purchase and user.email_verified_at is None:
        raise HTTPException(403, '请先验证注册邮箱，再购买商品')
    enabled(db, 'sales_enabled')
    context = agent_context(db, user, lock=True)
    product = db.scalar(select(Product).where(Product.id == product_id).with_for_update(key_share=True))
    if not product or not product.active:
        raise HTTPException(409, '商品不存在或已下架')
    quote = quote_for(db, product, user, context)
    assert_confirmed(quote, expected_amount)
    amount = quote.effective_price
    claimed = db.execute(update(Product).where(Product.id == product.id, Product.stock > 0, Product.active.is_(True))
        .values(stock=Product.stock - 1).returning(Product.id)).scalar_one_or_none()
    if claimed is None:
        raise HTTPException(409, '商品库存不足')
    order = new_order(db, product, 'wallet', amount, key, user.id)
    move_wallet(db, user.id, -amount, f'purchase:{order.id}', 'purchase', order_id=order.id)
    return result(order, key)

def redeem(db, raw, key):
    normalized = raw.strip().upper()
    # Locking plus conditional UPDATE; SQLite write transactions use BEGIN IMMEDIATE.
    code = db.scalar(select(RedeemCode).where(RedeemCode.code_hash == digest(normalized)).with_for_update())
    if not code:
        raise HTTPException(400, '卡密无效或不可兑换')
    if code.status == 'USED' and code.request_key == key:
        return result(required(db, Order, code.order_id), key)
    enabled(db, 'redemption_enabled')
    product = db.scalar(select(Product).where(Product.id == code.product_id).with_for_update())
    if not product or not product.active:
        raise HTTPException(400, '商品不可兑换')
    claimed = db.execute(update(RedeemCode).where(RedeemCode.id == code.id, RedeemCode.status == 'UNUSED',
        RedeemCode.expires_at > now()).values(status='USED', used_at=now(), request_key=key).execution_options(synchronize_session='fetch').returning(RedeemCode.id)).scalar_one_or_none()
    if claimed is None:
        raise HTTPException(400, '卡密无效或不可兑换')
    order = new_order(db, product, 'code', 0, key)
    code.order_id = order.id
    return result(order, key)

def issue_codes(db, actor, payload):
    product = db.scalar(select(Product).where(Product.id == payload.product_id).with_for_update())
    if not product or not product.active:
        raise HTTPException(409, '商品不可用')
    if payload.owner_id:
        owner = required(db, User, payload.owner_id)
        if owner.role != 'agent' or not owner.active:
            raise HTTPException(422, '卡密只能分配给有效代理')
    claimed = db.execute(update(Product).where(Product.id == product.id, Product.stock >= payload.quantity)
        .values(stock=Product.stock - payload.quantity).returning(Product.id)).scalar_one_or_none()
    if claimed is None:
        raise HTTPException(409, '库存不足，生成卡密需要预留库存')
    batch = secrets.token_hex(12)
    raw_codes = []
    for _ in range(payload.quantity):
        raw = 'YG-' + secrets.token_hex(16).upper()
        raw_codes.append(raw)
        db.add(RedeemCode(code_hash=digest(raw), suffix=raw[-6:], batch_id=batch,
            product_id=product.id, owner_id=payload.owner_id, expires_at=now() + timedelta(days=payload.valid_days)))
    audit(db, actor, 'codes.generate', batch, f'quantity={payload.quantity};owner={payload.owner_id}')
    return {'batch_id': batch, 'codes': raw_codes, 'notice': '完整卡密仅显示一次，请立即导出并妥善交付'}

def demo_recharge(db, user, amount, key):
    reference = f'demo:{user.id}:{key}'
    ledger = move_wallet(db, user.id, amount, reference, 'demo_recharge')
    payment = db.scalar(select(Payment).where(Payment.external_id == reference))
    if not payment:
        db.add(Payment(id=secrets.token_hex(16), user_id=user.id, external_id=reference, amount=amount))
    return ledger

def order_action(db, actor, order_id, action, note):
    job = db.scalar(select(FulfillmentJob).where(FulfillmentJob.order_id == order_id).with_for_update())
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        raise HTTPException(404, '订单不存在')
    if not job:
        raise HTTPException(409, '订单缺少履约任务')
    if action == 'refund':
        if order.payment_status == 'REFUNDED':
            return order
        if order.source != 'wallet' or order.fulfillment_status not in ('FAILED', 'CANCELED'):
            raise HTTPException(409, '仅支持失败或取消的钱包订单退款；已履约订单需线下核实')
        move_wallet(db, order.user_id, order.amount, f'refund:{order.id}', 'refund', order_id=order.id)
        order.payment_status = 'REFUNDED'
    elif action == 'retry':
        if order.payment_status != 'PAID' or order.fulfillment_status != 'FAILED' or job.attempts >= 3:
            raise HTTPException(409, '当前订单不可重试或已达3次上限')
        order.fulfillment_status = 'QUEUED'
        order.failure_reason = None
        job.state = 'QUEUED'
        job.last_error = None
    elif action == 'cancel':
        if order.fulfillment_status != 'QUEUED':
            raise HTTPException(409, '仅待履约订单可以取消')
        order.fulfillment_status = 'CANCELED'
        job.state = 'CANCELED'
    else:
        if order.payment_status != 'PAID' or order.fulfillment_status not in ('QUEUED','PROCESSING') or job.attempts >= 3:
            raise HTTPException(409, '当前订单不可处理')
        if action == 'complete' and order.verification_required:
            checks = {check.step: check.status for check in db.scalars(select(FulfillmentCheck).where(FulfillmentCheck.order_id == order.id))}
            if any(checks.get(step) != 'VERIFIED' for step in ('payment','entitlement','renewal_stopped','card_removed')):
                raise HTTPException(409, '付款、订阅权益、停止续费和移除支付方式均须核验后才能完成')
        job.attempts += 1
        status = 'COMPLETED' if action == 'complete' else 'FAILED'
        order.fulfillment_status = status
        job.state = status
        if action == 'complete':
            order.completed_at = now()
        else:
            order.failure_reason = note
            job.last_error = note
    db.add(OrderEvent(order_id=order.id, actor_id=actor.id, action=action, note=note))
    audit(db, actor, f'orders.{action}', order.id, note)
    return order

FULFILLMENT_STEPS = ('payment', 'entitlement', 'renewal_stopped', 'card_removed')

def fulfillment_checks(db, order_id):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, '订单不存在')
    stored = {item.step: item for item in db.scalars(select(FulfillmentCheck).where(FulfillmentCheck.order_id == order_id))}
    return {'order_id': order_id, 'verification_required': order.verification_required,
            'fulfillment_status': order.fulfillment_status,
            'checks': [{'step': step, 'status': stored[step].status if step in stored else 'PENDING',
                        'reference': stored[step].reference if step in stored else None,
                        'actor_id': stored[step].actor_id if step in stored else None,
                        'updated_at': stored[step].updated_at if step in stored else None} for step in FULFILLMENT_STEPS]}

def record_fulfillment_check(db, actor, order_id, payload):
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        raise HTTPException(404, '订单不存在')
    if not order.verification_required:
        raise HTTPException(409, '该订单未启用逐项履约核验')
    if order.payment_status != 'PAID' or order.fulfillment_status not in ('QUEUED', 'PROCESSING'):
        raise HTTPException(409, '当前订单不可更新履约核验')
    existing = {item.step: item for item in db.scalars(select(FulfillmentCheck).where(FulfillmentCheck.order_id == order_id))}
    if any(existing.get(step) is None or existing[step].status != 'VERIFIED' for step in FULFILLMENT_STEPS[:FULFILLMENT_STEPS.index(payload.step)]):
        raise HTTPException(409, '请按付款、订阅权益、停止续费、移除支付方式的顺序核验')
    current = existing.get(payload.step)
    if current and current.status == payload.status and current.reference == payload.reference:
        return fulfillment_checks(db, order_id)
    following = FULFILLMENT_STEPS[FULFILLMENT_STEPS.index(payload.step) + 1:]
    if following:
        db.execute(delete(FulfillmentCheck).where(FulfillmentCheck.order_id == order_id,
                                                   FulfillmentCheck.step.in_(following)))
    if current:
        current.status, current.reference, current.actor_id = payload.status, payload.reference, actor.id
        current.updated_at = now()
    else:
        db.add(FulfillmentCheck(order_id=order_id, step=payload.step, status=payload.status,
                                reference=payload.reference, actor_id=actor.id))
    db.add(OrderEvent(order_id=order_id, actor_id=actor.id, action=f'check.{payload.step}', note=payload.status))
    audit(db, actor, 'orders.check', order_id, f'{payload.step}:{payload.status}')
    db.flush()
    return fulfillment_checks(db, order_id)
