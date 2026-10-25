import csv
import io
import json
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.config import get_settings
from app.models import User, WalletTransaction, AuditLog, Product, RedeemCode
from app.services.commerce import move_wallet


def buy(client,tokens,quantity=2,price=800,request_key=None):
    r=client.post('/api/agent/codes/purchase',headers={**tokens['agent'],'Idempotency-Key':request_key or str(uuid4())},json={'product_id':1,'quantity':quantity,'valid_days':30,'expected_unit_price':price})
    assert r.status_code==201,r.text
    return r.json()


def fund():
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.name=='agent'))
        move_wallet(db,user.id,10000,'fund','adjust');db.commit();return user.id


def report(client,tokens,**params):
    return client.get('/api/admin/reports/code-purchases',headers=tokens['admin'],params=params)


def test_totals_replay_redemption_and_free_allocation_not_counted(client,tokens):
    uid=fund();key=str(uuid4())
    issued=buy(client,tokens,request_key=key)
    buy(client,tokens,request_key=key)
    assert client.post('/api/redeem',headers={'Idempotency-Key':str(uuid4())},json={'code':issued['codes'][0]}).status_code==200
    assert client.post('/api/admin/codes/generate',headers=tokens['admin'],json={'product_id':1,'quantity':3,'owner_id':uid}).status_code==201
    data=report(client,tokens).json()
    assert data['summary']=={'batches':1,'quantity':2,'amount':1600}
    assert sum(row['amount'] for row in data['daily'])==1600
    assert data['agents']==[{'agent_id':uid,'batches':1,'quantity':2,'amount':1600}]
    assert data['products']==[{'product_id':1,'batches':1,'quantity':2,'amount':1600}]
    assert 'detail' not in data and 'code_hash' not in str(data)
    assert report(client,tokens,agent_id=uid,product_id=1).json()['summary']==data['summary']
    assert report(client,tokens,agent_id=uid+100).json()['summary']['batches']==0
    assert report(client,tokens,product_id=999).json()['summary']['batches']==0
    with SessionLocal() as db:
        db.get(User,uid).role='user';db.commit()
    assert report(client,tokens,agent_id=uid).json()['summary']['amount']==1600


def test_zero_price_and_date_boundaries(client,tokens):
    uid=fund()
    client.put(f'/api/admin/agents/{uid}/products/1',headers=tokens['admin'],json={'price':0,'allowed':True}).raise_for_status()
    buy(client,tokens,price=0)
    with SessionLocal() as db:
        tx=db.scalar(select(WalletTransaction).where(WalletTransaction.kind=='code_purchase'))
        tx.created_at=datetime(2026,1,2,0,0,tzinfo=timezone.utc);db.commit()
    data=report(client,tokens,start='2026-01-01',end='2026-01-03').json()
    assert data['summary']=={'batches':1,'quantity':2,'amount':0}
    assert [row['batches'] for row in data['daily']]==[0,1,0]
    assert report(client,tokens,start='2026-01-01',end='2026-01-01').json()['summary']['quantity']==0
    assert report(client,tokens,start='2026-01-03',end='2026-01-03').json()['summary']['quantity']==0


def test_export_contract_no_secrets_and_audit(client,tokens):
    uid=fund();issued=buy(client,tokens)
    r=client.get('/api/admin/reports/code-purchases/export',headers=tokens['admin'],params={'agent_id':uid,'product_id':1})
    assert r.status_code==200 and r.headers['cache-control']=='no-store'
    rows=list(csv.DictReader(io.StringIO(r.text.lstrip('\ufeff'))))
    assert len(rows)==2 and rows[0]['batch_id']==issued['batch_id']
    assert rows[-1]['date_utc']=='TOTAL' and rows[-1]['quantity']=='2' and rows[-1]['amount']=='1600'
    assert rows[0]['filter_agent_id']==str(uid) and rows[0]['filter_product_id']=='1'
    for private in (*issued['codes'],'code_hash','token_version','lookup_hash','agent@example.com','agent-codes:'):
        assert private not in r.text
    with SessionLocal() as db:
        logs=db.scalars(select(AuditLog).where(AuditLog.action=='reports.code-purchases-export')).all()
        assert len(logs)==1 and f'agent_id={uid}' in logs[0].detail


@pytest.mark.parametrize('actor',['alice','agent'])
def test_permissions(client,tokens,actor):
    for endpoint in ('/api/admin/reports/code-purchases','/api/admin/reports/code-purchases/export'):
        assert client.get(endpoint,headers=tokens[actor]).status_code==403
        assert client.get(endpoint).status_code==401


@pytest.mark.parametrize('params',[{'start':'2026-01-03','end':'2026-01-01'},{'start':'2025-01-01','end':'2026-01-02'},
    {'start':'no'},{'agent_id':0},{'product_id':-1},{'end':'9999-12-31'}])
def test_filter_validation(client,tokens,params):
    assert report(client,tokens,**params).status_code==422


@pytest.mark.parametrize('broken',['json','quantity','amount','batch'])
def test_corrupt_records_refuse_instead_of_silent_omission(client,tokens,broken):
    fund();buy(client,tokens)
    with SessionLocal() as db:
        tx=db.scalar(select(WalletTransaction).where(WalletTransaction.kind=='code_purchase'))
        meta=json.loads(tx.note)
        if broken=='json':tx.note='bad'
        elif broken=='amount':tx.amount=-1
        else:
            if broken=='quantity':meta['contract']['quantity']=True
            else:meta['batch_id']='=malicious'
            tx.note=json.dumps(meta)
        db.commit()
    assert report(client,tokens).status_code==409
    assert client.get('/api/admin/reports/code-purchases/export',headers=tokens['admin']).status_code==409
    with SessionLocal() as db:
        assert not db.scalars(select(AuditLog).where(AuditLog.action=='reports.code-purchases-export')).all()


def test_limit_and_shared_export_throttle(client,tokens,monkeypatch):
    from app.services import code_reports
    fund();buy(client,tokens)
    monkeypatch.setattr(code_reports,'MAX_BATCHES',0)
    assert report(client,tokens).status_code==413
    monkeypatch.setattr(code_reports,'MAX_BATCHES',10000)
    monkeypatch.setattr(get_settings(),'trust_proxy',True)
    for i in range(5):
        assert client.get('/api/admin/reports/code-purchases/export',headers={**tokens['admin'],'X-Real-IP':f'192.0.2.{i+1}'}).status_code==200
    r=client.get('/api/admin/reports/code-purchases/export',headers={**tokens['admin'],'X-Real-IP':'192.0.2.99'})
    assert r.status_code==429 and 'retry-after' in r.headers
