from datetime import datetime, timezone
from fastapi import APIRouter, Query, HTTPException, Response
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from app.api.deps import DB, Admin, Key
from app.models import (User, Product, ProductPrice, RedeemCode, Order, Wallet, WalletTransaction,
    AuditLog, Agent, SystemSetting, OrderEvent, FulfillmentJob, now)
from app.schemas.requests import ProductInput, ProductUpdate, CodeBatch, CodeVoid, UserUpdate, WalletAdjust, OrderAction, FulfillmentCheckInput, SettingsUpdate
from app.services.commerce import audit, issue_codes, move_wallet, order_action, fulfillment_checks, record_fulfillment_check
from app.repositories.queries import required, row, paginate

router = APIRouter(prefix='/admin', tags=['管理员'])

@router.get('/dashboard')
def dashboard(actor: Admin, db: DB):
    paid = Order.payment_status == 'PAID'
    counts = db.execute(select(Order.fulfillment_status, func.count()).group_by(Order.fulfillment_status)).all()
    trend = db.execute(select(func.date(Order.created_at), func.count(), func.sum(Order.amount)).where(paid).group_by(func.date(Order.created_at)).order_by(func.date(Order.created_at).desc()).limit(14)).all()
    return {'users': db.scalar(select(func.count()).select_from(User)), 'orders': db.scalar(select(func.count()).select_from(Order)),
        'revenue': db.scalar(select(func.coalesce(func.sum(Order.amount), 0)).where(paid)),
        'available_codes': db.scalar(select(func.count()).select_from(RedeemCode).where(RedeemCode.status == 'UNUSED', RedeemCode.expires_at > now())),
        'statuses': dict(counts), 'trend': [{'date': str(d), 'orders': c, 'amount': a} for d, c, a in reversed(trend)],
        'recent_orders': [row(o, ('lookup_hash', 'idempotency_key')) for o in db.scalars(select(Order).order_by(Order.created_at.desc()).limit(8))]}

@router.get('/users')
def users(actor: Admin, db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), q: str = Query('', max_length=100), role: str = ''):
    statement = select(User)
    if q:
        statement = statement.where(User.email.icontains(q, autoescape=True))
    if role:
        statement = statement.where(User.role == role)
    return paginate(db, statement.order_by(User.id.desc()), page, page_size, ('password_hash', 'token_version'))

@router.patch('/users/{user_id}')
def edit_user(user_id: int, payload: UserUpdate, actor: Admin, db: DB):
    # Lock all administrators in stable order so concurrent demotions cannot remove the last admin.
    admins = db.scalars(select(User).where(User.role == 'admin', User.active.is_(True)).order_by(User.id).with_for_update(key_share=True)).all()
    user = db.scalar(select(User).where(User.id == user_id).with_for_update(key_share=True).execution_options(populate_existing=True))
    if not user:
        raise HTTPException(404, '账号不存在')
    if user.id == actor.id and (not payload.active or payload.role != 'admin'):
        raise HTTPException(409, '不能停用或降级当前管理员')
    if user.role == 'admin' and user.active and (not payload.active or payload.role != 'admin') and len(admins) <= 1:
        raise HTTPException(409, '必须保留至少一名有效管理员')
    user.active, user.role = payload.active, payload.role
    user.token_version += 1
    if user.role == 'agent' and not db.get(Agent, user.id):
        db.add(Agent(user_id=user.id))
    audit(db, actor, 'users.update', user_id, f'role={user.role};active={user.active}')
    db.commit()
    return row(user, ('password_hash', 'token_version'))

@router.get('/products')
def products(actor: Admin, db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    result = paginate(db, select(Product).order_by(Product.sort, Product.id), page, page_size)
    for item in result['items']:
        item['agent_price'] = db.scalar(select(ProductPrice.price).where(ProductPrice.product_id == item['id'], ProductPrice.role == 'agent'))
    return result

def save_product(db, payload, actor, value=None):
    requested_sku = payload.sku if 'sku' in payload.model_fields_set else (value.sku if value else None)
    if value is not None and value.sku is not None and requested_sku != value.sku:
        raise HTTPException(409, 'SKU 已绑定商品，不能修改或清空')
    if requested_sku and db.scalar(select(Product.id).where(Product.sku == requested_sku, Product.id != (value.id if value else -1))):
        raise HTTPException(409, 'SKU 已被其他商品使用')
    data = payload.model_dump(exclude={'agent_price','expected_updated_at'})
    if value is not None:
        for optional in ('sku', 'subscription_months'):
            if optional not in payload.model_fields_set:
                data.pop(optional)
    if value is None:
        value = Product(**data)
        db.add(value)
        db.flush()
    else:
        for key, item in data.items():
            setattr(value, key, item)
    price = db.scalar(select(ProductPrice).where(ProductPrice.product_id == value.id, ProductPrice.role == 'agent'))
    if price:
        price.price = payload.agent_price
    else:
        db.add(ProductPrice(product_id=value.id, role='agent', price=payload.agent_price))
    audit(db, actor, 'products.save', value.id)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if 'sku' in str(exc.orig).lower():
            raise HTTPException(409, 'SKU 已被其他商品使用') from None
        raise
    return {**row(value), 'agent_price': payload.agent_price}

@router.post('/products', status_code=201)
def create_product(payload: ProductInput, actor: Admin, db: DB):
    return save_product(db, payload, actor)

@router.put('/products/{product_id}')
def edit_product(product_id: int, payload: ProductUpdate, actor: Admin, db: DB):
    value = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if not value:
        raise HTTPException(404, '商品不存在')
    current = value.updated_at.replace(tzinfo=timezone.utc) if value.updated_at.tzinfo is None else value.updated_at
    expected = payload.expected_updated_at
    if expected.tzinfo is None or current != expected:
        raise HTTPException(409, '商品或库存已变化，请刷新后重新编辑')
    return save_product(db, payload, actor, value)

@router.post('/codes/generate', status_code=201)
def generate(payload: CodeBatch, actor: Admin, db: DB, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    data = issue_codes(db, actor, payload)
    db.commit()
    return data

@router.get('/codes')
def codes(actor: Admin, db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), status: str = '', product_id: int | None = None):
    statement = select(RedeemCode)
    if status == 'EXPIRED':
        statement = statement.where(RedeemCode.status == 'UNUSED', RedeemCode.expires_at <= now())
    elif status:
        statement = statement.where(RedeemCode.status == status)
        if status == 'UNUSED':
            statement = statement.where(RedeemCode.expires_at > now())
    if product_id:
        statement = statement.where(RedeemCode.product_id == product_id)
    return paginate(db, statement.order_by(RedeemCode.id.desc()), page, page_size, ('code_hash', 'request_key'))

@router.post('/codes/void')
def void(payload: CodeVoid, actor: Admin, db: DB):
    changed = db.execute(update(RedeemCode).where(RedeemCode.id.in_(payload.ids), RedeemCode.status == 'UNUSED')
        .values(status='VOID').returning(RedeemCode.id)).scalars().all()
    # Reserved inventory stays reserved; administrators can reconcile explicitly.
    audit(db, actor, 'codes.void', ','.join(map(str, changed))[:100], f'count={len(changed)}')
    db.commit()
    return {'changed': len(changed)}

@router.get('/orders')
def orders(actor: Admin, db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), status: str = '', q: str = Query('', max_length=100), product_id: int | None = None, start: datetime | None = None, end: datetime | None = None):
    statement = select(Order)
    if status:
        statement = statement.where(Order.fulfillment_status == status)
    if q:
        statement = statement.where(Order.id.icontains(q, autoescape=True))
    if product_id:
        statement = statement.where(Order.product_id == product_id)
    if start:
        statement = statement.where(Order.created_at >= start)
    if end:
        statement = statement.where(Order.created_at <= end)
    return paginate(db, statement.order_by(Order.created_at.desc()), page, page_size, ('lookup_hash', 'idempotency_key'))

@router.get('/orders/{order_id}/events')
def events(order_id: str, actor: Admin, db: DB):
    required(db, Order, order_id)
    return [row(e) for e in db.scalars(select(OrderEvent).where(OrderEvent.order_id == order_id).order_by(OrderEvent.id))]

@router.get('/orders/{order_id}/checks')
def checks(order_id: str, actor: Admin, db: DB):
    return fulfillment_checks(db, order_id)

@router.put('/orders/{order_id}/checks')
def set_check(order_id: str, payload: FulfillmentCheckInput, actor: Admin, db: DB):
    data = record_fulfillment_check(db, actor, order_id, payload)
    db.commit()
    return data

@router.post('/orders/{order_id}/action')
def action(order_id: str, payload: OrderAction, actor: Admin, db: DB):
    data = order_action(db, actor, order_id, payload.action, payload.note)
    db.commit()
    return row(data, ('lookup_hash', 'idempotency_key'))

@router.get('/wallets')
def wallets(actor: Admin, db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    return paginate(db, select(Wallet).order_by(Wallet.user_id), page, page_size)

@router.get('/wallets/{user_id}/transactions')
def ledger(user_id: int, actor: Admin, db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    return paginate(db, select(WalletTransaction).where(WalletTransaction.user_id == user_id).order_by(WalletTransaction.id.desc()), page, page_size)

@router.post('/wallets/{user_id}/adjust')
def adjust(user_id: int, payload: WalletAdjust, actor: Admin, db: DB, key: Key):
    amount, frozen = payload.amount, 0
    if payload.operation in ('freeze', 'unfreeze'):
        if amount <= 0:
            raise HTTPException(422, '冻结或解冻金额必须为正数')
        amount, frozen = (-amount, amount) if payload.operation == 'freeze' else (amount, -amount)
    data = move_wallet(db, user_id, amount, f'admin:{actor.id}:{key}', payload.operation, payload.note, frozen_delta=frozen)
    audit(db, actor, 'wallets.' + payload.operation, user_id, f'amount={payload.amount};note={payload.note}')
    db.commit()
    return row(data)

@router.get('/settings')
def settings(actor: Admin, db: DB):
    return {s.key: s.value == 'true' for s in db.scalars(select(SystemSetting))}

@router.put('/settings')
def settings_update(payload: SettingsUpdate, actor: Admin, db: DB):
    for key, val in payload.model_dump().items():
        setting = db.get(SystemSetting, key)
        if setting:
            setting.value = str(val).lower()
        else:
            db.add(SystemSetting(key=key, value=str(val).lower()))
    audit(db, actor, 'settings.update', 'business', str(payload.model_dump()))
    db.commit()
    return payload
