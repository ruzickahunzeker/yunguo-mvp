from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import app
from app.core.config import get_settings, Settings
from app.core.db import SessionLocal
from app.core.security import digest, verify_password
from app.models import PasswordResetToken, User, AuditLog, now
from app.services.password_reset import raw_token
from app.tasks import mail_worker
import pytest
from pydantic import ValidationError

@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), 'password_reset_enabled', True)
    monkeypatch.setattr(get_settings(), 'smtp_host', '127.0.0.1')
    monkeypatch.setattr(get_settings(), 'smtp_security', 'none')

def request_reset(client, email='alice@example.com'):
    return client.post('/api/auth/forgot-password',json={'email':email})

def get_raw():
    with SessionLocal() as db:
        return raw_token(db.scalar(select(PasswordResetToken).order_by(PasswordResetToken.created_at.desc())))

def consume(client, token, password='a-new-secure-password'):
    return client.post('/api/auth/reset-password',json={'token':token,'new_password':password})

def test_disabled_recovery_no_queue(client):
    assert client.get('/api/auth/features').json()=={'password_reset_enabled':False,'email_verification_enabled':False,'require_verified_email_for_purchase':False}
    assert request_reset(client).status_code==503
    assert consume(client,'a'*64).status_code==503
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PasswordResetToken))==0

def test_neutral_response_and_durable_hashed_token(client,enabled):
    known=request_reset(client)
    unknown=request_reset(client,'unknown@example.com')
    assert known.status_code==unknown.status_code==202
    assert known.json()==unknown.json()
    with SessionLocal() as db:
        record=db.scalar(select(PasswordResetToken))
        assert record.delivery_status=='QUEUED'
        assert record.token_hash==digest(raw_token(record))
        assert raw_token(record) not in str(record.__dict__)
        assert raw_token(record) not in known.text
        assert db.scalar(select(func.count()).select_from(PasswordResetToken))==1

def test_reset_single_use_revokes_sessions_and_audits(client,tokens,enabled):
    assert request_reset(client).status_code==202
    token=get_raw()
    assert consume(client,token).status_code==200
    assert consume(client,token).status_code==400
    assert client.get('/api/me/wallet',headers=tokens['alice']).status_code==401
    assert client.post('/api/auth/login',json={'email':'alice@example.com','password':'correct-password'}).status_code==401
    assert client.post('/api/auth/login',json={'email':'alice@example.com','password':'a-new-secure-password'}).status_code==200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=='auth.password-reset'))==1
        assert token not in str(db.scalar(select(AuditLog)).__dict__)

def test_reissue_expires_old_and_unknown_expired_same_error(client,enabled):
    assert request_reset(client).status_code==202
    first=get_raw()
    assert request_reset(client).status_code==202
    second=get_raw()
    assert first!=second
    with SessionLocal() as db:
        record=db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash==digest(second)))
        record.expires_at=now()-timedelta(seconds=1);db.commit()
    errors=[consume(client,t).json() for t in (first,second,'f'*64)]
    assert errors[0]==errors[1]==errors[2]

def test_disabled_account_and_version_changes_reject_reset(client,tokens,enabled):
    request_reset(client);token=get_raw()
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.name=='alice'));user.active=False;db.commit()
    assert consume(client,token).status_code==400
    response=request_reset(client)
    assert response.status_code==202
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PasswordResetToken))==1
        user=db.scalar(select(User).where(User.name=='alice'));user.active=True;user.token_version+=1;db.commit()
    assert consume(client,token).status_code==400

def test_concurrent_reset_one_winner(client,enabled):
    request_reset(client);token=get_raw()
    def run(i):
        with TestClient(app) as c:
            return consume(c,token,f'different-password-{i}').status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses=list(pool.map(run,range(4)))
    assert statuses.count(200)==1
    assert statuses.count(400)==3
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.name=='alice'))
        assert user.token_version==1
        assert sum(verify_password(f'different-password-{i}',user.password_hash) for i in range(4))==1

def test_mail_worker_delivers_reconstructed_token_once(client,enabled,monkeypatch):
    request_reset(client)
    captured=[]
    monkeypatch.setattr(mail_worker,'send_reset_email',lambda email,token:captured.append((email,token)))
    assert mail_worker.run_once()==1
    assert mail_worker.run_once()==0
    assert captured==[('alice@example.com',get_raw())]
    with SessionLocal() as db:
        record=db.scalar(select(PasswordResetToken))
        assert record.attempts==1 and record.delivery_status=='SENT'

def test_delivery_failure_bounded_and_sanitized(client,enabled,monkeypatch):
    request_reset(client)
    def failure(*args):
        raise RuntimeError('password=secret recipient=alice@example.com token='+get_raw())
    monkeypatch.setattr(mail_worker,'send_reset_email',failure)
    for expected in range(1,4):
        assert mail_worker.run_once()==1
        with SessionLocal() as db:
            record=db.scalar(select(PasswordResetToken))
            assert record.attempts==expected and record.last_error=='SMTP_DELIVERY_FAILED'
            assert record.delivery_status==('FAILED' if expected==3 else 'QUEUED')
            assert 'alice' not in str(record.__dict__)
            record.next_attempt_at=now()-timedelta(seconds=1);db.commit()
    assert mail_worker.run_once()==0

def test_worker_skips_expired_and_changed_auth_version(client,enabled):
    request_reset(client)
    with SessionLocal() as db:
        record=db.scalar(select(PasswordResetToken));record.expires_at=now()-timedelta(seconds=1);db.commit()
    with patch.object(mail_worker,'send_reset_email') as send:
        assert mail_worker.run_once()==0
        send.assert_not_called()
    request_reset(client)
    with SessionLocal() as db:
        db.scalar(select(User).where(User.name=='alice')).token_version+=1;db.commit()
    with patch.object(mail_worker,'send_reset_email') as send:
        assert mail_worker.run_once()==1
        send.assert_not_called()

def test_recovery_rate_limit_by_email_even_across_clients(client,enabled,monkeypatch):
    from app.core import rate_limit
    monkeypatch.setattr(get_settings(),'trust_proxy',True)
    for i in range(3):
        assert client.post('/api/auth/forgot-password',json={'email':'alice@example.com'},headers={'X-Real-IP':f'192.0.2.{i+1}'}).status_code==202
    assert client.post('/api/auth/forgot-password',json={'email':'ALICE@example.com'},headers={'X-Real-IP':'192.0.2.9'}).status_code==429

def test_production_recovery_requires_tls_and_origin():
    values=dict(_env_file=None,app_env='production',database_url='postgresql+psycopg://example/test',redis_url='redis://localhost',demo_recharge_enabled=False,jwt_secret='a'*40,code_pepper='b'*40,password_reset_enabled=True,smtp_host='smtp.example.com')
    for origin,security in [('http://shop.example.com','starttls'),('https://shop.example.com','none'),('https://shop.example.com/path','starttls')]:
        with pytest.raises(ValidationError):
            Settings(**values,public_base_url=origin,smtp_security=security)

def test_validation_errors_never_reflect_reset_token(client,enabled):
    token='f'*64
    r=client.post('/api/auth/reset-password',json={'token':token,'new_password':'x'})
    assert r.status_code==422 and token not in r.text

def test_development_limiter_preserves_longer_windows(monkeypatch):
    from fastapi import Request, HTTPException
    from app.core import rate_limit
    request=Request({'type':'http','client':('192.0.2.1',1234),'headers':[]})
    moment=[1000.0]
    monkeypatch.setattr(rate_limit.time,'monotonic',lambda:moment[0])
    rate_limit.limit(request,'long-window',1,900)
    moment[0]=1100.0
    rate_limit.limit(request,'short-window',5,60)
    with pytest.raises(HTTPException) as error:
        rate_limit.limit(request,'long-window',1,900)
    assert error.value.status_code==429
