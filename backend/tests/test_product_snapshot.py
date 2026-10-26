from uuid import uuid4
from app.core.db import SessionLocal
from app.models import Order


def test_monthly_sku_snapshot_survives_product_edits(client, tokens):
    admin = tokens['admin']
    payload = {'sku': 'CHATGPT_PLUS_MONTHLY', 'name': 'Plus 月度演示', 'description': '下单时权益说明',
               'subscription_months': 1, 'category': '订阅演示', 'original_price': 1200,
               'price': 1000, 'agent_price': 800, 'stock': 5, 'active': True, 'sort': 1,
               'verification_required': False}
    created = client.post('/api/admin/products', json=payload, headers=admin)
    assert created.status_code == 201, created.text
    product_id = created.json()['id']
    assert client.post('/api/admin/products', json=payload, headers=admin).status_code == 409
    topup = client.post('/api/me/wallet/demo-recharge', json={'amount': 1000},
                        headers={**tokens['alice'], 'Idempotency-Key': str(uuid4())})
    assert topup.status_code == 200, topup.text
    order = client.post('/api/orders', json={'product_id': product_id, 'expected_amount': 1000},
                        headers={**tokens['alice'], 'Idempotency-Key': str(uuid4())})
    assert order.status_code == 201, order.text
    order_id = order.json()['order_id']
    assert order.json()['product_sku'] == 'CHATGPT_PLUS_MONTHLY'
    current = client.get('/api/admin/products', headers=admin).json()['items']
    version = next(item['updated_at'] for item in current if item['id'] == product_id)
    updated = {**payload, 'name': 'Plus 新说明', 'description': '后来修改的权益说明', 'price': 1100,
               'expected_updated_at': version}
    response = client.put(f'/api/admin/products/{product_id}', json=updated, headers=admin)
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        snapshot = db.get(Order, order_id)
        assert (snapshot.product_name, snapshot.product_sku, snapshot.product_description,
                snapshot.subscription_months, snapshot.amount) == (
                    'Plus 月度演示', 'CHATGPT_PLUS_MONTHLY', '下单时权益说明', 1, 1000)
    legacy_payload = {key: value for key, value in updated.items() if key not in ('sku', 'subscription_months')}
    legacy_payload['expected_updated_at'] = response.json()['updated_at']
    legacy = client.put(f'/api/admin/products/{product_id}', json=legacy_payload, headers=admin)
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()['sku'] == 'CHATGPT_PLUS_MONTHLY' and legacy.json()['subscription_months'] == 1
    updated['sku'] = 'CHATGPT_PRO_MONTHLY'
    updated['expected_updated_at'] = legacy.json()['updated_at']
    assert client.put(f'/api/admin/products/{product_id}', json=updated, headers=admin).status_code == 409
