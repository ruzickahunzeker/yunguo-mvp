from datetime import date
from fastapi import APIRouter, Query, Request, Response, HTTPException
from sqlalchemy import select, func
from app.api.deps import DB, CurrentUser, Key, AgentUser
from app.core.config import get_settings
from app.core.rate_limit import limit
from app.models import Order, Wallet, WalletTransaction, OrderEvent, Product, RedeemCode, Agent
from app.schemas.requests import Buy, Recharge, AgentCodePurchase, MockDirectTopup
from app.services.agent_codes import purchase_codes
from app.services.commerce import purchase, demo_recharge, audit
from app.services.pricing import agent_context, quote_for
from app.services.agent_team import team_report
from app.api.reports import filters as report_filters
from app.repositories.queries import row, required, paginate

router = APIRouter(tags=['用户与代理'])

@router.get('/agent/team')
def agent_team(user: AgentUser, db: DB, start: date | None = None, end: date | None = None,
               page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               q: str = Query('', max_length=80)):
    if user.role != 'agent':
        raise HTTPException(403, '请在管理后台查看代理团队')
    query = report_filters(start, end, None, None)
    return team_report(db, user.id, query['start'], query['end'], page, page_size, q)

@router.post('/orders', status_code=201)
def buy(payload: Buy, user: CurrentUser, db: DB, key: Key, request: Request):
    limit(request, f'buy:{user.id}', 30)
    result = purchase(db, user, payload.product_id, key, payload.expected_amount)
    db.commit()
    return result

@router.post('/agent/direct/mock', status_code=201)
def mock_direct_topup(payload: MockDirectTopup, user: AgentUser, db: DB, key: Key, request: Request):
    """Development-only direct-topup simulation; no customer credential is accepted."""
    if not get_settings().mock_direct_topup_enabled or get_settings().app_env == 'production':
        raise HTTPException(503, '模拟直充仅在开发/测试环境开放')
    limit(request, f'agent.direct-mock:{user.id}', 10)
    result = purchase(db, user, payload.product_id, key, payload.expected_amount)
    order = db.get(Order, result['order_id'])
    audit(db, user, 'mock.direct-topup', order.id, f'mock_reference={payload.mock_reference}')
    db.add(OrderEvent(order_id=order.id, action='mock.direct-topup', actor_id=user.id,
                      note='Development-only direct top-up simulation; no customer credential received'))
    db.commit()
    return {**result, 'mode': 'mock', 'mock_reference': payload.mock_reference}

@router.get('/me/orders')
def orders(user: CurrentUser, db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), status: str = '', q: str = Query('', max_length=100)):
    statement = select(Order).where(Order.user_id == user.id)
    if status:
        statement = statement.where(Order.fulfillment_status == status)
    if q:
        statement = statement.where(Order.id.icontains(q, autoescape=True))
    return paginate(db, statement.order_by(Order.created_at.desc()), page, page_size, ('lookup_hash', 'idempotency_key'))

@router.get('/me/orders/{order_id}/events')
def events(order_id: str, user: CurrentUser, db: DB):
    order = required(db, Order, order_id)
    if order.user_id != user.id:
        raise HTTPException(404, '订单不存在')
    return [row(e) for e in db.scalars(select(OrderEvent).where(OrderEvent.order_id == order_id).order_by(OrderEvent.id))]

@router.get('/me/wallet')
def wallet(user: CurrentUser, db: DB):
    return {**row(required(db, Wallet, user.id)), 'demo_recharge_enabled': get_settings().demo_recharge_enabled}

@router.get('/me/transactions')
def transactions(user: CurrentUser, db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    return paginate(db, select(WalletTransaction).where(WalletTransaction.user_id == user.id).order_by(WalletTransaction.id.desc()), page, page_size)

@router.post('/me/wallet/demo-recharge')
def recharge(payload: Recharge, user: CurrentUser, db: DB, key: Key, request: Request):
    limit(request, f'recharge:{user.id}', 10)
    if not get_settings().demo_recharge_enabled:
        raise HTTPException(403, '演示充值未启用')
    result = demo_recharge(db, user, payload.amount, key)
    db.commit()
    return row(result)

@router.get('/agent/overview')
def overview(user: AgentUser, db: DB):
    agent, level = agent_context(db, user)
    return {'level': level.name if level else '管理员' if user.role == 'admin' else '未配置',
        'level_id': level.id if level else None, 'level_active': level.active if level else user.role == 'admin',
        'order_count': db.scalar(select(func.count()).select_from(Order).where(Order.user_id == user.id)),
        'purchase_amount': db.scalar(select(func.coalesce(func.sum(Order.amount), 0)).where(Order.user_id == user.id, Order.payment_status == 'PAID')),
        'code_count': db.scalar(select(func.count()).select_from(RedeemCode).where(RedeemCode.owner_id == user.id)),
        'code_purchase_amount': -db.scalar(select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(WalletTransaction.user_id == user.id, WalletTransaction.kind == 'code_purchase')),
        'wallet': row(required(db, Wallet, user.id))}

@router.get('/agent/prices')
def prices(user: AgentUser, db: DB):
    return [{**row(p), **quote_for(db, p, user).as_dict()} for p in db.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.sort, Product.id))]

@router.get('/agent/codes')
def codes(user: AgentUser, db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    return paginate(db, select(RedeemCode).where(RedeemCode.owner_id == user.id).order_by(RedeemCode.id.desc()), page, page_size, ('code_hash', 'request_key'))

@router.post('/agent/codes/purchase', status_code=201)
def buy_codes(payload: AgentCodePurchase, user: AgentUser, db: DB, key: Key,
              request: Request, response: Response):
    limit(request, f'agent.codes-purchase:{user.id}', 5, 60, per_client=False)
    result = purchase_codes(db, user, payload, key)
    db.commit()
    response.headers['Cache-Control'] = 'no-store'
    return result
