import hmac
from fastapi import APIRouter, Request, Query, HTTPException, Response
from sqlalchemy import select, or_
from app.api.deps import DB, Key
from app.models import Product, Order
from app.schemas.requests import Redeem, Lookup
from app.services.commerce import redeem
from app.core.security import digest
from app.core.rate_limit import limit
from app.repositories.queries import row, paginate

router = APIRouter(tags=['公开服务'])

@router.get('/products')
def products(db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), q: str = Query('', max_length=100), category: str = Query('', max_length=60)):
    query = select(Product).where(Product.active.is_(True))
    if q:
        query = query.where(or_(Product.name.icontains(q, autoescape=True), Product.description.icontains(q, autoescape=True)))
    if category:
        query = query.where(Product.category == category)
    return paginate(db, query.order_by(Product.sort, Product.id), page, page_size)

@router.get('/products/{product_id}')
def product(product_id: int, db: DB):
    value = db.get(Product, product_id)
    if not value or not value.active:
        raise HTTPException(404, '商品不存在')
    return row(value)

@router.post('/redeem')
def redeem_code(payload: Redeem, request: Request, db: DB, key: Key, response: Response):
    limit(request, 'redeem', 10)
    response.headers['Cache-Control'] = 'no-store'
    data = redeem(db, payload.code, key)
    db.commit()
    return data

@router.post('/orders/lookup')
def lookup(payload: Lookup, request: Request, db: DB):
    limit(request, 'lookup', 20)
    order = db.get(Order, payload.order_id)
    if not order or not hmac.compare_digest(order.lookup_hash, digest(payload.lookup_token)):
        raise HTTPException(404, '订单不存在或查询凭证错误')
    return row(order, ('lookup_hash', 'idempotency_key', 'user_id'))
