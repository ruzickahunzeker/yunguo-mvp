from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import app
from app.core.db import SessionLocal
from app.core.config import get_settings
from app.core.security import digest
from app.models import Wallet, WalletTransaction, Product, RedeemCode, User, AgentLevel, AgentProductRule, SystemSetting, AuditLog
from app.services.commerce import move_wallet


def fund(tokens, amount=10000):
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.name=='agent'))
        move_wallet(db,user.id,amount,'test-funding','adjust')
        db.commit()


def purchase(client,tokens,**changes):
    payload={'product_id':1,'quantity':2,'valid_days':30,'expected_unit_price':800}
    payload.update(changes.pop('payload',{}))
    return client.post('/api/agent/codes/purchase',json=payload,
        headers={**tokens[changes.pop('actor','agent')],'Idempotency-Key':changes.pop('key',str(uuid4()))})


def test_paid_issuance_private_delivery_replay_and_redeem_no_second_charge(client,tokens):
    fund(tokens)
    key=str(uuid4())
    first=purchase(client,tokens,key=key)
    assert first.status_code==201,first.text
    data=first.json();assert len(data['codes'])==2 and data['charged_amount']==1600
    assert first.headers['cache-control']=='no-store'
    replay=purchase(client,tokens,key=key).json()
    assert replay['replayed'] and replay['codes']==[] and replay['batch_id']==data['batch_id']
    assert purchase(client,tokens,key=key,payload={'quantity':3}).status_code==409
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.name=='agent'))
        assert db.get(Wallet,user.id).balance==8400 and db.get(Product,1).stock==98
        stored=db.scalars(select(RedeemCode)).all()
        assert all(c.owner_id==user.id and c.code_hash==digest(raw) for c,raw in zip(stored,data['codes']))
        assert db.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.kind=='code_purchase'))==1
        assert not any(raw in str(db.scalars(select(AuditLog.detail)).all()) for raw in data['codes'])
    assert client.post('/api/redeem',headers={'Idempotency-Key':str(uuid4())},json={'code':data['codes'][0]}).status_code==200
    assert client.get('/api/me/wallet',headers=tokens['agent']).json()['balance']==8400
    assert 'code_hash' not in client.get('/api/agent/codes',headers=tokens['agent']).text


@pytest.mark.parametrize('actor',['alice','admin'])
def test_non_agents_cannot_purchase_cards(client,tokens,actor):
    assert purchase(client,tokens,actor=actor).status_code==403


@pytest.mark.parametrize('failure',['balance','stock','price','level','permission','sales','verification','product'])
def test_rejections_atomic_no_codes_or_charge(client,tokens,monkeypatch,failure):
    if failure!='balance':fund(tokens)
    with SessionLocal() as db:
        if failure=='stock':db.get(Product,1).stock=1
        if failure=='price':db.get(Product,1).price=2000
        if failure=='level':db.get(AgentLevel,1).active=False
        if failure=='permission':
            user=db.scalar(select(User).where(User.name=='agent'))
            db.add(AgentProductRule(agent_id=user.id,product_id=1,allowed=False))
        if failure=='sales':db.get(SystemSetting,'sales_enabled').value='false'
        if failure=='product':db.get(Product,1).active=False
        db.commit()
    if failure=='verification':monkeypatch.setattr(get_settings(),'require_verified_email_for_purchase',True)
    r=purchase(client,tokens,payload={'expected_unit_price':999} if failure=='price' else {})
    assert r.status_code in (403,409),r.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(RedeemCode))==0
        assert db.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.kind=='code_purchase'))==0
        assert db.get(Product,1).stock==(1 if failure=='stock' else 100)
        assert not db.scalars(select(AuditLog).where(AuditLog.action=='codes.generate')).all()


def test_override_price_zero_cost_and_replay_after_permission_change(client,tokens):
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.name=='agent'))
        rule=AgentProductRule(agent_id=user.id,product_id=1,price=0)
        db.add(rule);db.commit()
    key=str(uuid4())
    r=purchase(client,tokens,key=key,payload={'expected_unit_price':0})
    assert r.status_code==201 and r.json()['charged_amount']==0
    with SessionLocal() as db:
        db.scalar(select(AgentProductRule)).allowed=False;db.commit()
    assert purchase(client,tokens,key=key,payload={'expected_unit_price':0}).json()['replayed']
    assert purchase(client,tokens,payload={'expected_unit_price':0}).status_code==403


def test_concurrent_same_key_only_one_delivery_and_debit(client,tokens):
    fund(tokens);key=str(uuid4())
    def request(_):
        with TestClient(app) as c:return purchase(c,tokens,key=key)
    with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(request,range(2)))
    assert all(r.status_code==201 for r in responses)
    assert sorted(len(r.json()['codes']) for r in responses)==[0,2]
    with SessionLocal() as db:
        assert db.get(Product,1).stock==98
        assert db.scalar(select(func.count()).select_from(RedeemCode))==2
        user=db.scalar(select(User).where(User.name=='agent'))
        assert db.get(Wallet,user.id).balance==8400


def test_distinct_requests_cannot_overspend(client,tokens):
    fund(tokens,1600)
    def request(_):
        with TestClient(app) as c:return purchase(c,tokens).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(request,range(2)))
    assert sorted(statuses)==[201,409]
    with SessionLocal() as db:
        assert db.get(Product,1).stock==98
        assert db.scalar(select(func.count()).select_from(RedeemCode))==2


@pytest.mark.parametrize('payload',[{'quantity':True},{'quantity':1.5},{'quantity':501},{'valid_days':False},
    {'expected_unit_price':800.0},{'owner_id':1}])
def test_strict_contract(client,tokens,payload):
    assert purchase(client,tokens,payload=payload).status_code==422
