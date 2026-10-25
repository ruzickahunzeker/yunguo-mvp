import pytest
from sqlalchemy import select, func
from app.core.config import get_settings, Settings
from app.core.db import SessionLocal
from app.models import Order, OrderEvent, WalletTransaction


def test_mock_direct_topup_requires_test_switch_and_never_accepts_credentials(client,tokens,monkeypatch):
    monkeypatch.setattr(get_settings(), 'mock_direct_topup_enabled', False)
    r=client.post('/api/agent/direct/mock',headers={**tokens['agent'],'Idempotency-Key':'mock-direct-1234567890abcdef'},json={'product_id':1,'expected_amount':800,'mock_reference':'mock-customer-1234567890ab'})
    assert r.status_code==503
    r=client.post('/api/agent/direct/mock',headers={**tokens['agent'],'Idempotency-Key':'mock-direct-1234567890abcdef'},json={'product_id':1,'expected_amount':800,'mock_reference':'sess_live_1234567890123456'})
    assert r.status_code==422


def test_mock_direct_topup_is_development_only_and_audited(client,tokens,monkeypatch):
    settings=get_settings();monkeypatch.setattr(settings,'mock_direct_topup_enabled',True);monkeypatch.setattr(settings,'app_env','test')
    assert client.post('/api/me/wallet/demo-recharge',headers={**tokens['agent'],'Idempotency-Key':'mock-fund-abcdef123456'},json={'amount':1000}).status_code==200
    r=client.post('/api/agent/direct/mock',headers={**tokens['agent'],'Idempotency-Key':'mock-direct-abcdef1234567890'},json={'product_id':1,'expected_amount':800,'mock_reference':'mock-customer-abcdef123456'})
    assert r.status_code==201,r.text
    assert r.json()['mode']=='mock'
    with SessionLocal() as db:
        order=db.get(Order,r.json()['order_id'])
        assert order and db.scalar(select(func.count()).select_from(OrderEvent).where(OrderEvent.order_id==order.id,OrderEvent.action=='mock.direct-topup'))==1
        assert db.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.order_id==order.id))==1


def test_production_config_rejects_mock_direct_topup():
    with pytest.raises(Exception):
        Settings(_env_file=None,app_env='production',database_url='postgresql+psycopg://x/x',redis_url='redis://x',demo_recharge_enabled=False,mock_direct_topup_enabled=True,jwt_secret='a'*40,code_pepper='b'*40)
