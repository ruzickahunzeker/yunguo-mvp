from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from app.core.db import SessionLocal
from app.core.config import get_settings
from app.models import User, Order, FulfillmentJob, PasswordResetToken, EmailVerificationToken, AuditLog, Wallet
from app.services import operations
from .test_commerce import key

URL='/api/admin/operations'
AT=datetime(2026,10,16,12,tzinfo=timezone.utc)

def fixture_orders(monkeypatch):
    monkeypatch.setattr(operations,'now',lambda:AT)
    cases=[('queued-old','QUEUED','QUEUED','PAID','wallet',0,60),
        ('queued-new','QUEUED','QUEUED','PAID','wallet',0,5),
        ('boundary','QUEUED','QUEUED','PAID','code',0,30),
        ('failed','FAILED','FAILED','PAID','wallet',1,90),
        ('exhausted','FAILED','FAILED','PAID','wallet',3,80),
        ('canceled','CANCELED','CANCELED','PAID','wallet',0,70),
        ('card-failed','FAILED','FAILED','PAID','code',1,50),
        ('refunded','FAILED','FAILED','REFUNDED','wallet',3,120),
        ('done','COMPLETED','COMPLETED','PAID','wallet',1,40)]
    with SessionLocal() as db:
        uid=db.scalar(select(User.id).where(User.name=='alice'))
        for oid,status,state,payment,source,attempts,age in cases:
            db.add(Order(id=oid,user_id=uid,product_id=1,product_name='队列测试',source=source,
                amount=0 if source=='code' else 1000,payment_status=payment,fulfillment_status=status,
                lookup_hash='private-lookup',idempotency_key='private-request-'+oid,failure_reason='private-failure',created_at=AT-timedelta(minutes=age)))
            db.flush()
            db.add(FulfillmentJob(order_id=oid,state=state,attempts=attempts,last_error='private-job-error',updated_at=AT-timedelta(minutes=age)))
        db.commit()

def summary(client,tokens,**params):
    r=client.get(URL+'/summary',headers=tokens['admin'],params=params)
    assert r.status_code==200,r.text
    return r.json()

def listed(client,tokens,**params):
    r=client.get(URL+'/orders',headers=tokens['admin'],params=params)
    assert r.status_code==200,r.text
    return r.json()

def test_operations_admin_only(client,tokens):
    for path in ['/summary','/orders']:
        assert client.get(URL+path).status_code==401
        for who in ['alice','agent']:
            assert client.get(URL+path,headers=tokens[who]).status_code==403

def test_empty_summary_counts_modes_and_no_false_liveness(client,tokens):
    data=summary(client,tokens)
    assert data['fulfillment_mode']=='mock'
    assert data['alerts']==[]
    assert data['fulfillment']==dict(queued=0,stale=0,attention=0,exhausted=0,refundable=0,oldest_queued_at=None)
    for stats in data['mail'].values():
        assert stats==dict(enabled=False,queued=0,due=0,waiting=0,expired_queued=0,failed=0)
    assert 'worker_alive' not in data and 'healthy' not in data
    assert listed(client,tokens)['total']==0

def test_counts_threshold_boundary_refunds_and_card_failures(client,tokens,monkeypatch):
    fixture_orders(monkeypatch)
    data=summary(client,tokens)
    assert {k:v for k,v in data['fulfillment'].items() if k!='oldest_queued_at'}==dict(queued=3,stale=2,attention=4,exhausted=1,refundable=3)
    assert datetime.fromisoformat(data['fulfillment']['oldest_queued_at'])==AT-timedelta(minutes=60)
    assert data['observed_at'].startswith('2026-10-16T12:00:00')
    assert summary(client,tokens,stale_minutes=31)['fulfillment']['stale']==1
    assert summary(client,tokens,stale_minutes=61)['fulfillment']['stale']==0
    assert {a['code'] for a in data['alerts']}=={'FULFILLMENT_STALE','ORDER_ATTENTION','RETRY_EXHAUSTED'}

def test_manual_wait_alert_is_informational(client,tokens,monkeypatch):
    fixture_orders(monkeypatch)
    monkeypatch.setattr(get_settings(),'fulfillment_mode','manual')
    data=summary(client,tokens)
    assert data['fulfillment_mode']=='manual'
    assert next(a for a in data['alerts'] if a['code']=='FULFILLMENT_STALE')['severity']=='info'
    monkeypatch.setattr(get_settings(),'fulfillment_mode','mock')
    assert next(a for a in summary(client,tokens)['alerts'] if a['code']=='FULFILLMENT_STALE')['severity']=='warning'

def test_order_categories_and_stable_oldest_first_pagination(client,tokens,monkeypatch):
    fixture_orders(monkeypatch)
    expected={'queued':{'queued-old','queued-new','boundary'},'stale':{'queued-old','boundary'},
        'attention':{'failed','exhausted','canceled','card-failed'},'exhausted':{'exhausted'},'refundable':{'failed','exhausted','canceled'}}
    for kind,ids in expected.items():
        assert {r['order_id'] for r in listed(client,tokens,kind=kind)['items']}==ids
    assert listed(client,tokens,kind='attention',page_size=1)['items'][0]['order_id']=='failed'
    assert listed(client,tokens,kind='attention',page_size=1,page=2)['items'][0]['order_id']=='exhausted'
    assert listed(client,tokens,page=99)['items']==[]

def test_sensitive_fields_never_in_operations_payloads(client,tokens,monkeypatch):
    fixture_orders(monkeypatch)
    raw=str(summary(client,tokens))+str(listed(client,tokens))
    for value in ['private-lookup','private-request','private-job-error','private-failure','lookup_hash','idempotency_key','token_hash','smtp_host','redis_url','database_url','jwt_secret']:
        assert value not in raw

def mail_fixtures(model,uid):
    records=[]
    for i,(status,expiry,used,next_delay,attempts) in enumerate([
        ('QUEUED',60,False,0,0),('QUEUED',60,False,5,1),('QUEUED',0,False,-1,0),
        ('QUEUED',60,True,-1,0),('FAILED',60,False,-1,3),('FAILED',-1,False,-1,3),
        ('SENT',60,False,-1,1),('CANCELED',60,False,-1,0)]):
        args=dict(id=f'{model.__tablename__}-{i}',user_id=uid,auth_version=0,token_hash=f'private-{model.__tablename__}-{i}',expires_at=AT+timedelta(minutes=expiry),used_at=AT if used else None,delivery_status=status,attempts=attempts,next_attempt_at=AT+timedelta(minutes=next_delay),created_at=AT-timedelta(minutes=10))
        if model==EmailVerificationToken:args['email_hash']='private-email-hash'
        records.append(model(**args))
    return records

def test_mail_due_backoff_expired_failed_and_feature_flags(client,tokens,monkeypatch):
    monkeypatch.setattr(operations,'now',lambda:AT)
    with SessionLocal() as db:
        uid=db.scalar(select(User.id).where(User.name=='alice'))
        db.add_all(mail_fixtures(PasswordResetToken,uid)+mail_fixtures(EmailVerificationToken,uid));db.commit()
    data=summary(client,tokens)
    for stats in data['mail'].values():
        assert stats==dict(enabled=False,queued=3,due=1,waiting=1,expired_queued=1,failed=1)
    assert len([a for a in data['alerts'] if a['code']=='MAIL_PAUSED'])==2
    assert not any(a['code']=='MAIL_FAILED' for a in data['alerts'])
    monkeypatch.setattr(get_settings(),'password_reset_enabled',True)
    data=summary(client,tokens)
    assert next(a for a in data['alerts'] if a['code']=='MAIL_FAILED')['purpose']=='password_reset'
    assert next(a for a in data['alerts'] if a['code']=='MAIL_PAUSED')['purpose']=='email_verification'
    assert 'private' not in str(data)

def test_queries_do_not_write_jobs_orders_wallet_or_audit(client,tokens,monkeypatch):
    fixture_orders(monkeypatch)
    with SessionLocal() as db:
        before=([tuple(r) for r in db.execute(select(Order.id,Order.fulfillment_status,Order.payment_status))],
            [tuple(r) for r in db.execute(select(FulfillmentJob.order_id,FulfillmentJob.state,FulfillmentJob.attempts))],
            db.scalar(select(func.count()).select_from(AuditLog)),db.scalar(select(func.sum(Wallet.balance))))
    summary(client,tokens);listed(client,tokens,kind='exhausted')
    with SessionLocal() as db:
        after=([tuple(r) for r in db.execute(select(Order.id,Order.fulfillment_status,Order.payment_status))],
            [tuple(r) for r in db.execute(select(FulfillmentJob.order_id,FulfillmentJob.state,FulfillmentJob.attempts))],
            db.scalar(select(func.count()).select_from(AuditLog)),db.scalar(select(func.sum(Wallet.balance))))
    assert after==before

def test_validation(client,tokens):
    for params in [{'stale_minutes':0},{'stale_minutes':10081},{'stale_minutes':'invalid'}]:
        for path in ['/summary','/orders']:
            assert client.get(URL+path,params=params,headers=tokens['admin']).status_code==422
    for params in [{'page':0},{'page_size':101},{'kind':'invalid'}]:
        assert client.get(URL+'/orders',params=params,headers=tokens['admin']).status_code==422

def test_existing_admin_refund_removes_order_from_attention(client,tokens,monkeypatch):
    monkeypatch.setattr(get_settings(),'fulfillment_mode','manual')
    assert client.post('/api/me/wallet/demo-recharge',json={'amount':2000},headers=key(tokens['alice'])).status_code==200
    buy=client.post('/api/orders',json={'product_id':1,'expected_amount':1000},headers=key(tokens['alice']))
    assert buy.status_code==201
    oid=buy.json()['order_id']
    assert client.post(f'/api/admin/orders/{oid}/action',json={'action':'fail','note':'人工异常验收'},headers=tokens['admin']).status_code==200
    assert summary(client,tokens)['fulfillment']['refundable']==1
    assert client.post(f'/api/admin/orders/{oid}/action',json={'action':'refund','note':'人工退款验收'},headers=tokens['admin']).status_code==200
    assert summary(client,tokens)['fulfillment']['refundable']==0
    assert listed(client,tokens)['total']==0
    assert client.get('/api/me/wallet',headers=tokens['alice']).json()['balance']==2000
