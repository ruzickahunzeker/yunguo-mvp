from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import app
from app.core.db import SessionLocal
from app.core.security import digest
from app.models import Order, Wallet, WalletTransaction, RedeemCode, Product, User, FulfillmentJob, now
from app.tasks.worker import run_once


def key(headers=None, value=None):
    return {**(headers or {}),'Idempotency-Key':value or str(uuid4())}

def topup(client,tokens,amount=10000):
    r=client.post('/api/me/wallet/demo-recharge',json={'amount':amount},headers=key(tokens['alice']))
    assert r.status_code==200,r.text

def generate(client,tokens,quantity=1,**kwargs):
    r=client.post('/api/admin/codes/generate',json={'product_id':1,'quantity':quantity,**kwargs},headers=tokens['admin'])
    assert r.status_code==201,r.text
    return r.json()['codes']

def buy(client,tokens,headers=None):
    return client.post('/api/orders',json={'product_id':1,'expected_amount':1000},headers=headers or key(tokens['alice']))

def test_purchase_idempotency_and_worker(client,tokens):
    topup(client,tokens)
    h=key(tokens['alice'])
    a,b=buy(client,tokens,h),buy(client,tokens,h)
    assert a.status_code==b.status_code==201
    assert a.json()==b.json()
    assert client.get('/api/me/wallet',headers=tokens['alice']).json()['balance']==9000
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order))==1
        assert db.get(Product,1).stock==99
    assert run_once()==1
    assert run_once()==0
    r=client.post('/api/orders/lookup',json={'order_id':a.json()['order_id'],'lookup_token':a.json()['lookup_token']})
    assert r.json()['fulfillment_status']=='COMPLETED'

def test_insufficient_wallet_rolls_back_everything(client,tokens):
    r=buy(client,tokens)
    assert r.status_code==409
    with SessionLocal() as db:
        assert db.get(Product,1).stock==100
        assert db.scalar(select(func.count()).select_from(Order))==0
        assert db.scalar(select(func.count()).select_from(FulfillmentJob))==0
        assert db.scalar(select(func.count()).select_from(WalletTransaction))==0

def test_redeem_hash_once_and_receipt_privacy(client,tokens):
    raw=generate(client,tokens)[0]
    with SessionLocal() as db:
        code=db.scalar(select(RedeemCode))
        assert code.code_hash==digest(raw)
        assert raw not in str(code.__dict__)
    h=key()
    a=client.post('/api/redeem',json={'code':raw.lower()},headers=h)
    b=client.post('/api/redeem',json={'code':raw},headers=h)
    assert a.status_code==b.status_code==200
    assert a.json()==b.json()
    assert a.json()['product_name']=='演示套餐'
    assert a.json()['amount']==0
    assert a.json()['created_at']
    assert client.post('/api/redeem',json={'code':raw},headers=key()).status_code==400
    assert client.post('/api/orders/lookup',json={'order_id':a.json()['order_id'],'lookup_token':'x'*64}).status_code==404
    assert client.post('/api/orders/lookup',json={'order_id':a.json()['order_id']}).status_code==422
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order))==1
        assert db.get(Product,1).stock==99

def test_concurrent_redeem_single_winner(client,tokens):
    raw=generate(client,tokens)[0]
    def request(_):
        with TestClient(app) as c:
            return c.post('/api/redeem',json={'code':raw},headers=key()).status_code
    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses=list(pool.map(request,range(6)))
    assert statuses.count(200)==1
    assert statuses.count(400)==5
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order))==1

def test_expired_void_and_down_product_rejected(client,tokens):
    expired,void,down=generate(client,tokens,3)
    with SessionLocal() as db:
        c=db.scalar(select(RedeemCode).where(RedeemCode.code_hash==digest(expired)));c.expires_at=now()-timedelta(days=1)
        v=db.scalar(select(RedeemCode).where(RedeemCode.code_hash==digest(void)));v.status='VOID';db.commit()
    for raw in [expired,void]:
        assert client.post('/api/redeem',json={'code':raw},headers=key()).status_code==400
    with SessionLocal() as db:
        db.get(Product,1).active=False;db.commit()
    assert client.post('/api/redeem',json={'code':down},headers=key()).status_code==400
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order))==0
        assert db.scalar(select(RedeemCode.status).where(RedeemCode.code_hash==digest(down)))=='UNUSED'

def test_recharge_repeat_and_payload_mismatch(client,tokens):
    h=key(tokens['alice'])
    a=client.post('/api/me/wallet/demo-recharge',json={'amount':1000},headers=h)
    b=client.post('/api/me/wallet/demo-recharge',json={'amount':1000},headers=h)
    assert a.json()==b.json()
    assert client.post('/api/me/wallet/demo-recharge',json={'amount':2000},headers=h).status_code==409
    assert client.get('/api/me/wallet',headers=tokens['alice']).json()['balance']==1000

def test_refund_repeat_and_retry_state_machine(client,tokens):
    topup(client,tokens)
    order=buy(client,tokens).json()['order_id']
    url=f'/api/admin/orders/{order}/action'
    assert client.post(url,json={'action':'refund','note':'禁止提前退款'},headers=tokens['admin']).status_code==409
    assert client.post(url,json={'action':'fail','note':'模拟人工失败'},headers=tokens['admin']).status_code==200
    for _ in range(2):
        assert client.post(url,json={'action':'refund','note':'人工审核退款'},headers=tokens['admin']).status_code==200
    assert client.get('/api/me/wallet',headers=tokens['alice']).json()['balance']==10000
    assert client.post(url,json={'action':'retry','note':'退款后不可重试'},headers=tokens['admin']).status_code==409
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.kind=='refund'))==1

def test_freeze_unfreeze_and_ledger(client,tokens):
    topup(client,tokens,2000)
    with SessionLocal() as db:
        uid=db.scalar(select(User.id).where(User.name=='alice'))
    url=f'/api/admin/wallets/{uid}/adjust'
    h=key(tokens['admin'])
    payload={'amount':1500,'operation':'freeze','note':'核验冻结资金'}
    assert client.post(url,json=payload,headers=h).status_code==200
    assert client.post(url,json=payload,headers=h).status_code==200
    assert buy(client,tokens).status_code==409
    assert client.post(url,json={'amount':1500,'operation':'unfreeze','note':'完成核验解冻'},headers=key(tokens['admin'])).status_code==200
    assert buy(client,tokens).status_code==201
    with SessionLocal() as db:
        wallet=db.get(Wallet,uid)
        amount,frozen=db.execute(select(func.sum(WalletTransaction.amount),func.sum(WalletTransaction.frozen_delta)).where(WalletTransaction.user_id==uid)).one()
        assert (wallet.balance,wallet.frozen)==(amount,frozen)==(1000,0)

def test_agent_price_and_stock_reservation(client,tokens):
    assert client.post('/api/me/wallet/demo-recharge',json={'amount':1000},headers=key(tokens['agent'])).status_code==200
    r=client.post('/api/orders',json={'product_id':1,'expected_amount':800},headers=key(tokens['agent']))
    assert r.status_code==201
    assert client.get('/api/me/wallet',headers=tokens['agent']).json()['balance']==200
    with SessionLocal() as db:
        uid=db.scalar(select(User.id).where(User.name=='agent'))
    generate(client,tokens,2,owner_id=uid)
    assert client.get('/api/agent/codes',headers=tokens['agent']).json()['total']==2
    with SessionLocal() as db:
        assert db.get(Product,1).stock==97

def test_concurrent_wallet_no_overdraw(client,tokens):
    topup(client,tokens,1000)
    def request(_):
        with TestClient(app) as c:
            return buy(c,tokens).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses=list(pool.map(request,range(4)))
    assert statuses.count(201)==1
    assert statuses.count(409)==3
    assert client.get('/api/me/wallet',headers=tokens['alice']).json()['balance']==0

def test_business_flags(client,tokens):
    topup(client,tokens)
    raw=generate(client,tokens)[0]
    assert client.put('/api/admin/settings',json={'sales_enabled':False,'redemption_enabled':False},headers=tokens['admin']).status_code==200
    assert buy(client,tokens).status_code==409
    assert client.post('/api/redeem',json={'code':raw},headers=key()).status_code==409

def test_retry_limit_and_completed_refund_block(client,tokens):
    topup(client,tokens)
    oid=buy(client,tokens).json()['order_id'];url=f'/api/admin/orders/{oid}/action'
    for i in range(3):
        assert client.post(url,json={'action':'fail','note':'人工模拟失败'},headers=tokens['admin']).status_code==200
        expected=200 if i<2 else 409
        assert client.post(url,json={'action':'retry','note':'人工确认重试'},headers=tokens['admin']).status_code==expected
    oid2=buy(client,tokens).json()['order_id']
    assert run_once()==1
    assert client.post(f'/api/admin/orders/{oid2}/action',json={'action':'refund','note':'已完成不可退'},headers=tokens['admin']).status_code==409

def test_concurrent_same_purchase_key_once(client,tokens):
    topup(client,tokens,2000)
    h=key(tokens['alice'])
    def request(_):
        with TestClient(app) as c:
            return buy(c,tokens,h)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses=list(pool.map(request,range(4)))
    # A racing uniqueness conflict is retryable with the exact same key.
    assert all(r.status_code in (201,409) for r in responses)
    successes=[r.json()['order_id'] for r in responses if r.status_code==201]
    assert len(set(successes))==1
    assert buy(client,tokens,h).json()['order_id']==successes[0]
    assert client.get('/api/me/wallet',headers=tokens['alice']).json()['balance']==1000
    with SessionLocal() as db:
        assert db.get(Product,1).stock==99
        assert db.scalar(select(func.count()).select_from(Order))==1

def test_last_stock_concurrent_buy_and_batch(client,tokens):
    topup(client,tokens,10000)
    with SessionLocal() as db:
        db.get(Product,1).stock=1;db.commit()
    def request(i):
        with TestClient(app) as c:
            if i%2:
                return c.post('/api/admin/codes/generate',json={'product_id':1,'quantity':1},headers=tokens['admin']).status_code
            return buy(c,tokens).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses=list(pool.map(request,range(4)))
    assert statuses.count(201)==1
    with SessionLocal() as db:
        assert db.get(Product,1).stock==0
        assert db.scalar(select(func.count()).select_from(Order))+db.scalar(select(func.count()).select_from(RedeemCode))==1

def test_concurrent_refund_only_one_credit(client,tokens):
    topup(client,tokens,1000)
    oid=buy(client,tokens).json()['order_id']
    url=f'/api/admin/orders/{oid}/action'
    assert client.post(url,json={'action':'fail','note':'模拟故障退款'},headers=tokens['admin']).status_code==200
    def request(_):
        with TestClient(app) as c:
            return c.post(url,json={'action':'refund','note':'核实故障退款'},headers=tokens['admin']).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses=list(pool.map(request,range(4)))
    assert statuses==[200]*4
    assert client.get('/api/me/wallet',headers=tokens['alice']).json()['balance']==1000
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.kind=='refund'))==1

def test_manual_mode_leaves_job_and_admin_can_complete(client,tokens,monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(),'fulfillment_mode','manual')
    topup(client,tokens,1000)
    oid=buy(client,tokens).json()['order_id']
    assert run_once()==0
    r=client.post(f'/api/admin/orders/{oid}/action',json={'action':'complete','note':'人工核实交付完成'},headers=tokens['admin'])
    assert r.status_code==200 and r.json()['fulfillment_status']=='COMPLETED'

def test_public_code_query_and_admin_audit_do_not_expose_hash(client,tokens):
    raw=generate(client,tokens)[0]
    text=client.get('/api/admin/codes',headers=tokens['admin']).text
    assert 'code_hash' not in text and 'request_key' not in text and raw not in text
    logs=client.get('/api/admin/audit-logs',headers=tokens['admin']).text
    assert raw not in logs

def test_production_config_rejects_insecure_modes():
    import pytest
    from app.core.config import Settings
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Settings(_env_file=None,app_env='production',database_url='sqlite:///bad.db',jwt_secret='a'*40,code_pepper='b'*40,redis_url='',demo_recharge_enabled=True)

def test_stale_product_edit_does_not_restore_sold_stock(client,tokens):
    product=client.get('/api/admin/products',headers=tokens['admin']).json()['items'][0]
    payload={k:product[k] for k in ['name','description','category','original_price','price','agent_price','stock','active','sort']}
    payload['expected_updated_at']=product['updated_at']
    topup(client,tokens,1000)
    assert buy(client,tokens).status_code==201
    assert client.put('/api/admin/products/1',json=payload,headers=tokens['admin']).status_code==409
    current=client.get('/api/admin/products',headers=tokens['admin']).json()['items'][0]
    payload['expected_updated_at']=current['updated_at'];payload['stock']=current['stock'];payload['name']='更新套餐名称'
    assert client.put('/api/admin/products/1',json=payload,headers=tokens['admin']).status_code==200
    with SessionLocal() as db:
        assert db.get(Product,1).stock==99
