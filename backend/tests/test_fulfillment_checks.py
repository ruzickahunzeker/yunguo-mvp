from sqlalchemy import select
from uuid import uuid4
from app.core.db import SessionLocal
from app.models import Product, Order, FulfillmentCheck
from app.tasks.worker import run_once


def topup(client, tokens, amount):
    response = client.post('/api/me/wallet/demo-recharge', json={'amount': amount},
                           headers={**tokens['alice'], 'Idempotency-Key': str(uuid4())})
    assert response.status_code == 200, response.text


def buy(client, tokens):
    response = client.post('/api/orders', json={'product_id': 1, 'expected_amount': 1000},
                           headers={**tokens['alice'], 'Idempotency-Key': str(uuid4())})
    assert response.status_code == 201, response.text
    return response


def test_selected_order_needs_all_four_checks_before_manual_completion(client, tokens):
    with SessionLocal() as db:
        db.get(Product, 1).verification_required = True
        db.commit()
    topup(client, tokens, 1000)
    order_id = buy(client, tokens).json()['order_id']
    url = f'/api/admin/orders/{order_id}'
    assert run_once() == 0
    with SessionLocal() as db:
        assert db.get(Order, order_id).fulfillment_status == 'QUEUED'
        db.get(Product, 1).verification_required = False
        db.commit()
    assert client.get(url + '/checks', headers=tokens['alice']).status_code == 403
    assert client.post(url + '/action', json={'action': 'complete', 'note': '尚未核验'}, headers=tokens['admin']).status_code == 409
    assert client.put(url + '/checks', json={'step': 'entitlement', 'status': 'VERIFIED', 'reference': 'receipt_002'}, headers=tokens['admin']).status_code == 409
    steps = ('payment', 'entitlement', 'renewal_stopped', 'card_removed')
    for index, step in enumerate(steps):
        payload = {'step': step, 'status': 'VERIFIED', 'reference': f'receipt_{index:03d}'}
        response = client.put(url + '/checks', json=payload, headers=tokens['admin'])
        assert response.status_code == 200, response.text
        assert response.json()['checks'][index]['status'] == 'VERIFIED'
        assert client.put(url + '/checks', json=payload, headers=tokens['admin']).status_code == 200
    with SessionLocal() as db:
        assert len(db.scalars(select(FulfillmentCheck).where(FulfillmentCheck.order_id == order_id)).all()) == 4
    result = client.post(url + '/action', json={'action': 'complete', 'note': '四项已核验'}, headers=tokens['admin'])
    assert result.status_code == 200 and result.json()['fulfillment_status'] == 'COMPLETED'
    assert client.put(url + '/checks', json={'step': 'payment', 'status': 'FAILED', 'reference': 'receipt_999'}, headers=tokens['admin']).status_code == 409


def test_changed_check_invalidates_later_steps_and_rejects_secret_fields(client, tokens):
    with SessionLocal() as db:
        db.get(Product, 1).verification_required = True
        db.commit()
    topup(client, tokens, 1000)
    order_id = buy(client, tokens).json()['order_id']
    url = f'/api/admin/orders/{order_id}/checks'
    assert client.put(url, json={'step': 'payment', 'status': 'VERIFIED', 'reference': 'receipt_001', 'session': 'secret'}, headers=tokens['admin']).status_code == 422
    assert client.put(url, json={'step': 'payment', 'status': 'VERIFIED', 'reference': 'session_001'}, headers=tokens['admin']).status_code == 422
    for step in ('payment', 'entitlement'):
        assert client.put(url, json={'step': step, 'status': 'VERIFIED', 'reference': 'receipt_001'}, headers=tokens['admin']).status_code == 200
    result = client.put(url, json={'step': 'payment', 'status': 'FAILED', 'reference': 'receipt_002'}, headers=tokens['admin'])
    assert result.status_code == 200
    assert [check['status'] for check in result.json()['checks']] == ['FAILED', 'PENDING', 'PENDING', 'PENDING']
    assert client.post(f'/api/admin/orders/{order_id}/action', json={'action': 'complete', 'note': '仍不能完成'}, headers=tokens['admin']).status_code == 409
    assert client.post(f'/api/admin/orders/{order_id}/action', json={'action': 'fail', 'note': '客户 password secret'}, headers=tokens['admin']).status_code == 422
