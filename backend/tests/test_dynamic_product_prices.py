from uuid import uuid4
from sqlalchemy import select
from app.core.db import SessionLocal
from app.models import Product, ProductPrice, Order, AuditLog, User, Agent


def h(token):
    return {**token, 'Idempotency-Key': str(uuid4())}


def test_retail_and_default_agent_prices_change_for_new_orders_only(client, tokens):
    admin = tokens['admin']
    product = client.get('/api/admin/products', headers=admin).json()['items'][0]
    payload = {key: product[key] for key in ('name', 'description', 'category', 'original_price', 'price', 'agent_price', 'stock', 'active', 'sort')}
    payload.update(price=1000, agent_price=800, expected_updated_at=product['updated_at'])
    updated = client.put('/api/admin/products/1', json=payload, headers=admin)
    assert updated.status_code == 200, updated.text
    recharge = client.post('/api/me/wallet/demo-recharge', json={'amount': 3000}, headers=h(tokens['alice']))
    assert recharge.status_code == 200
    first = client.post('/api/orders', json={'product_id': 1, 'expected_amount': 1000}, headers=h(tokens['alice']))
    assert first.status_code == 201
    current = client.get('/api/admin/products', headers=admin).json()['items'][0]
    payload.update(price=1200, agent_price=900, stock=current['stock'], expected_updated_at=current['updated_at'])
    changed = client.put('/api/admin/products/1', json=payload, headers=admin)
    assert changed.status_code == 200, changed.text
    second = client.post('/api/orders', json={'product_id': 1, 'expected_amount': 1200}, headers=h(tokens['alice']))
    assert second.status_code == 201
    assert client.post('/api/orders', json={'product_id': 1, 'expected_amount': 1000}, headers=h(tokens['alice'])).status_code == 409
    with SessionLocal() as db:
        orders = db.scalars(select(Order).order_by(Order.created_at)).all()
        assert [order.amount for order in orders] == [1000, 1200]
        assert db.scalar(select(Product).where(Product.id == 1)).price == 1200
        assert db.scalar(select(ProductPrice.price).where(ProductPrice.product_id == 1, ProductPrice.role == 'agent')) == 900
        audit = db.scalar(select(AuditLog).where(AuditLog.action == 'products.save').order_by(AuditLog.id.desc()))
        assert audit and 'price=1000->1200' in audit.detail and 'agent_price=800->900' in audit.detail

