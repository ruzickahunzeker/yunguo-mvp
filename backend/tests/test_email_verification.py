from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from pydantic import ValidationError
from app.main import app
from app.core.config import get_settings, Settings
from app.core.db import SessionLocal
from app.core.security import digest
from app.models import EmailVerificationToken, PasswordResetToken, User, Order, Product, AuditLog, now
from app.services.email_verification import raw_token
from app.tasks import mail_worker
from .test_commerce import key, topup, buy

@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(),'email_verification_enabled',True)
    monkeypatch.setattr(get_settings(),'smtp_host','127.0.0.1')
    monkeypatch.setattr(get_settings(),'smtp_security','none')

def request(client,tokens,name='alice'):
    return client.post('/api/auth/verification/request',headers=tokens[name])

def credential(name='alice'):
    with SessionLocal() as db:
        uid=db.scalar(select(User.id).where(User.name==name))
        return raw_token(db.scalar(select(EmailVerificationToken).where(EmailVerificationToken.user_id==uid).order_by(EmailVerificationToken.created_at.desc())))

def verify(client,token):
    return client.post('/api/auth/verify-email',json={'token':token})

def test_disabled_no_queue_and_request_requires_login(client,tokens):
    assert client.post('/api/auth/verification/request').status_code==401
    assert request(client,tokens).status_code==503
    assert verify(client,'a'*64).status_code==503
    assert client.get('/api/auth/me',headers=tokens['alice']).json()['email_verified_at'] is None
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(EmailVerificationToken))==0

def test_registration_queues_hash_only_without_verifying(client,enabled):
    r=client.post('/api/auth/register',json={'email':'fresh@example.com','password':'a-strong-test-password','name':'fresh'})
    assert r.status_code==201 and r.json()['user']['email_verified_at'] is None
    with SessionLocal() as db:
        record=db.scalar(select(EmailVerificationToken))
        assert record.delivery_status=='QUEUED'
        assert record.token_hash==digest(raw_token(record))
        assert raw_token(record) not in str(record.__dict__) and raw_token(record) not in r.text
        assert record.email_hash==digest('fresh@example.com')

def test_single_use_sets_status_and_audits_without_role_or_session_change(client,tokens,enabled):
    assert request(client,tokens).status_code==202
    token=credential()
    assert verify(client,token).status_code==200
    assert verify(client,token).status_code==400
    me=client.get('/api/auth/me',headers=tokens['alice'])
    assert me.status_code==200 and me.json()['email_verified_at'] is not None
    assert me.json()['role']=='user'
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.name=='alice'))
        assert user.token_version==0
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=='auth.email-verified'))==1
        assert token not in str(db.scalar(select(AuditLog)).__dict__)
    assert request(client,tokens).json()['message']=='邮箱已验证，无需重复发送'
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(EmailVerificationToken))==1

def test_reissue_invalidates_old_token_and_expiry_is_uniform(client,tokens,enabled):
    request(client,tokens);first=credential()
    request(client,tokens);second=credential()
    assert first!=second
    with SessionLocal() as db:
        db.scalar(select(EmailVerificationToken).where(EmailVerificationToken.token_hash==digest(second))).expires_at=now()-timedelta(seconds=1)
        db.commit()
    responses=[verify(client,t) for t in [first,second,'f'*64]]
    assert all(r.status_code==400 for r in responses)
    assert responses[0].json()==responses[1].json()==responses[2].json()

def test_concurrent_confirmation_single_winner(client,tokens,enabled):
    request(client,tokens);token=credential()
    def run(_):
        with TestClient(app) as c:return verify(c,token).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:statuses=list(pool.map(run,range(4)))
    assert statuses.count(200)==1 and statuses.count(400)==3
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=='auth.email-verified'))==1

def test_disabled_account_or_changed_version_and_email_reject(client,tokens,enabled):
    request(client,tokens);token=credential()
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.name=='alice'));user.active=False;db.commit()
    assert verify(client,token).status_code==400
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.name=='alice'));user.active=True;user.token_version+=1;db.commit()
    assert verify(client,token).status_code==400
    # Fixture-only direct email mutation proves the link is also bound to address.
    request(client,tokens,'bob');token=credential('bob')
    with SessionLocal() as db:
        db.scalar(select(User).where(User.name=='bob')).email='changed@example.com';db.commit()
    assert verify(client,token).status_code==400

def test_optional_purchase_gate_and_existing_request_replay(client,tokens,enabled,monkeypatch):
    topup(client,tokens)
    original_headers=key(tokens['alice'])
    old=buy(client,tokens,original_headers)
    assert old.status_code==201
    monkeypatch.setattr(get_settings(),'require_verified_email_for_purchase',True)
    assert buy(client,tokens).status_code==403
    assert buy(client,tokens,original_headers).json()==old.json()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order))==1
        assert db.get(Product,1).stock==99
    request(client,tokens);assert verify(client,credential()).status_code==200
    assert buy(client,tokens).status_code==201
    assert client.get('/api/me/wallet',headers=tokens['alice']).json()['balance']==8000

def test_gate_does_not_block_history_or_prepaid_redemption(client,tokens,enabled,monkeypatch):
    monkeypatch.setattr(get_settings(),'require_verified_email_for_purchase',True)
    assert client.get('/api/me/orders',headers=tokens['alice']).status_code==200
    assert client.get('/api/me/wallet',headers=tokens['alice']).status_code==200
    codes=client.post('/api/admin/codes/generate',json={'product_id':1,'quantity':1},headers=tokens['admin']).json()['codes']
    assert client.post('/api/redeem',json={'code':codes[0]},headers=key()).status_code==200

def test_mail_worker_shared_delivery_and_purpose_separation(client,tokens,enabled,monkeypatch):
    monkeypatch.setattr(get_settings(),'password_reset_enabled',True)
    request(client,tokens)
    assert client.post('/api/auth/forgot-password',json={'email':'alice@example.com'}).status_code==202
    delivered=[]
    monkeypatch.setattr(mail_worker,'send_reset_email',lambda email,token:delivered.append(('reset',email,token)))
    monkeypatch.setattr(mail_worker,'send_verification_email',lambda email,token:delivered.append(('verify',email,token)))
    assert mail_worker.run_once()==2
    assert mail_worker.run_once()==0
    reset_token=next(item[2] for item in delivered if item[0]=='reset')
    email_token=next(item[2] for item in delivered if item[0]=='verify')
    assert reset_token!=email_token
    assert verify(client,reset_token).status_code==400
    assert client.post('/api/auth/reset-password',json={'token':email_token,'new_password':'a-new-strong-password'}).status_code==400
    assert verify(client,email_token).status_code==200

def test_delivery_failures_are_sanitized_bounded_and_obsolete_skipped(client,tokens,enabled,monkeypatch):
    request(client,tokens)
    def failure(*args):raise RuntimeError('private@example.com SMTP_PASSWORD=secret')
    monkeypatch.setattr(mail_worker,'send_verification_email',failure)
    for i in range(3):
        assert mail_worker.run_once()==1
        with SessionLocal() as db:
            record=db.scalar(select(EmailVerificationToken))
            assert record.attempts==i+1 and record.last_error=='SMTP_DELIVERY_FAILED'
            assert record.delivery_status==('FAILED' if i==2 else 'QUEUED')
            assert 'secret' not in str(record.__dict__)
            record.next_attempt_at=now()-timedelta(seconds=1);db.commit()
    assert mail_worker.run_once()==0
    request(client,tokens)
    with SessionLocal() as db:
        db.scalar(select(User).where(User.name=='alice')).token_version+=1;db.commit()
    with patch.object(mail_worker,'send_verification_email') as send:
        assert mail_worker.run_once()==1;send.assert_not_called()

def test_resend_global_user_limit_and_validation_redaction(client,tokens,enabled,monkeypatch):
    monkeypatch.setattr(get_settings(),'trust_proxy',True)
    for i in range(3):
        assert client.post('/api/auth/verification/request',headers={**tokens['alice'],'X-Real-IP':f'192.0.2.{i+1}'}).status_code==202
    assert client.post('/api/auth/verification/request',headers={**tokens['alice'],'X-Real-IP':'192.0.2.9'}).status_code==429
    token='secret-token-not-valid'
    r=verify(client,token)
    assert r.status_code==422 and token not in r.text

def test_config_rejects_gate_without_delivery_and_unencrypted_production():
    values=dict(_env_file=None,jwt_secret='a'*40,code_pepper='b'*40,password_reset_enabled=False)
    with pytest.raises(ValidationError):Settings(**values,email_verification_enabled=False,require_verified_email_for_purchase=True)
    with pytest.raises(ValidationError):Settings(**values,email_verification_enabled=True,smtp_host='')
    with pytest.raises(ValidationError):Settings(**values,app_env='production',database_url='postgresql+psycopg://example/test',redis_url='redis://localhost',demo_recharge_enabled=False,email_verification_enabled=True,smtp_host='localhost',smtp_security='none',public_base_url='https://shop.example.com')
