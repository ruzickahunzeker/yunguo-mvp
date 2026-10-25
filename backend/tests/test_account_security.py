from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
import pytest
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core import rate_limit
from app.core.security import verify_password
from app.main import app
from app.models import User, AuditLog
from app.services.accounts import locked_account


def test_account_attempt_limit_shared_across_ips_normalized_and_private(client,monkeypatch):
    monkeypatch.setattr(get_settings(),'trust_proxy',True)
    for i in range(20):
        response=client.post('/api/auth/login',headers={'X-Real-IP':f'192.0.2.{i+1}'},json={'email':'ALICE@example.com' if i%2 else 'alice@example.com','password':'wrong-password'})
        assert response.status_code==401
    response=client.post('/api/auth/login',headers={'X-Real-IP':'192.0.2.100'},json={'email':'alice@example.com','password':'correct-password'})
    assert response.status_code==429 and 'retry-after' in response.headers
    assert not any('@' in bucket or 'wrong-password' in bucket for bucket in rate_limit._buckets)
    assert client.post('/api/auth/login',headers={'X-Real-IP':'192.0.2.101'},json={'email':'bob@example.com','password':'correct-password'}).status_code==200

def test_unknown_accounts_same_response_and_shared_limiter(client,monkeypatch):
    monkeypatch.setattr(get_settings(),'trust_proxy',True)
    for i in range(20):
        r=client.post('/api/auth/login',headers={'X-Real-IP':f'192.0.2.{i+1}'},json={'email':'unknown@example.com','password':'wrong-password'})
        assert r.status_code==401
        assert r.json()['detail']=='邮箱或密码错误，或账号已停用'
    assert client.post('/api/auth/login',headers={'X-Real-IP':'192.0.2.99'},json={'email':'unknown@example.com','password':'wrong-password'}).status_code==429

def test_password_change_limit_before_hashing_and_no_mutation(client,tokens,monkeypatch):
    monkeypatch.setattr(get_settings(),'trust_proxy',True)
    for i in range(5):
        assert client.post('/api/auth/password',headers={**tokens['alice'],'X-Real-IP':f'192.0.2.{i+1}'},json={'current_password':'incorrect','new_password':'new-password-long'}).status_code==400
    assert client.post('/api/auth/password',headers={**tokens['alice'],'X-Real-IP':'192.0.2.99'},json={'current_password':'correct-password','new_password':'new-password-long'}).status_code==429
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.name=='alice'))
        assert verify_password('correct-password',user.password_hash)
        assert user.token_version==0
        assert not db.scalars(select(AuditLog).where(AuditLog.action=='auth.password-changed')).all()

@pytest.mark.parametrize('mutation',['version','disable','missing'])
def test_locked_account_rejects_state_changed_since_authentication(mutation):
    with SessionLocal() as before:
        user=before.scalar(select(User).where(User.name=='alice'))
        identity=user.id
        with SessionLocal() as other:
            current=other.get(User,identity)
            if mutation=='version':current.token_version+=1
            elif mutation=='disable':current.active=False
            else:
                # Keep financial foreign keys intact; emulate a missing result at read.
                before.expunge(user)
                user.id=999999
            other.commit()
        with pytest.raises(HTTPException) as result:locked_account(before,user)
        assert result.value.status_code==401


def test_profile_password_logout_audit_no_sensitive_text(client,tokens):
    h=tokens['alice']
    r=client.patch('/api/auth/me',headers=h,json={'name':'private-display-name'})
    assert r.status_code==200 and r.json()['name']=='private-display-name'
    r=client.post('/api/auth/password',headers=h,json={'current_password':'correct-password','new_password':'private-new-password'})
    assert r.status_code==200
    assert client.get('/api/auth/me',headers=h).status_code==401
    fresh=client.post('/api/auth/login',json={'email':'alice@example.com','password':'private-new-password'})
    token={'Authorization':'Bearer '+fresh.json()['access_token']}
    assert client.post('/api/auth/logout',headers=token).status_code==200
    with SessionLocal() as db:
        logs=db.scalars(select(AuditLog).order_by(AuditLog.id)).all()
        assert [e.action for e in logs]==['auth.profile-updated','auth.password-changed','auth.logout']
        assert all(e.actor_id and e.target==str(e.actor_id) for e in logs)
        assert not any(word in str([e.detail for e in logs]) for word in ['correct-password','private-new-password','private-display-name'])


def test_concurrent_password_changes_one_winner(client,tokens):
    def change(i):
        with TestClient(app) as c:
            return c.post('/api/auth/password',headers=tokens['alice'],json={'current_password':'correct-password','new_password':f'replacement-password-{i}'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(change,range(2)))
    assert statuses.count(200)==1 and all(s in (200,401) for s in statuses)
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.name=='alice'))
        assert user.token_version==1
        assert len(db.scalars(select(AuditLog).where(AuditLog.action=='auth.password-changed')).all())==1
