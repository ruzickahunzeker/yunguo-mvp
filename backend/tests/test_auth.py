from sqlalchemy import select
from app.core.db import SessionLocal
from app.models import User
from .test_commerce import key, topup, buy


def test_registration_login_password_logout(client,tokens):
    r=client.post('/api/auth/register',json={'email':'new@example.com','name':'新用户','password':'long-password'})
    assert r.status_code==201,r.text
    h={'Authorization':'Bearer '+r.json()['access_token']}
    assert client.get('/api/auth/me',headers=h).status_code==200
    assert client.post('/api/auth/password',json={'current_password':'bad','new_password':'new-password-long'},headers=h).status_code==400
    assert client.post('/api/auth/password',json={'current_password':'long-password','new_password':'new-password-long'},headers=h).status_code==200
    assert client.get('/api/auth/me',headers=h).status_code==401
    r=client.post('/api/auth/login',json={'email':'new@example.com','password':'new-password-long'})
    assert r.status_code==200
    h={'Authorization':'Bearer '+r.json()['access_token']}
    assert client.post('/api/auth/logout',headers=h).status_code==200
    assert client.get('/api/auth/me',headers=h).status_code==401

def test_backend_permissions_and_no_private_fields(client,tokens):
    assert client.get('/api/admin/users').status_code==401
    for name in ['alice','bob','agent']:
        assert client.get('/api/admin/users',headers=tokens[name]).status_code==403
    assert client.get('/api/agent/codes',headers=tokens['alice']).status_code==403
    topup(client,tokens)
    oid=buy(client,tokens).json()['order_id']
    assert client.get(f'/api/me/orders/{oid}/events',headers=tokens['bob']).status_code==404
    assert client.get('/api/me/orders',headers=tokens['bob']).json()['total']==0
    body=client.get('/api/admin/users',headers=tokens['admin']).text
    assert 'password_hash' not in body and 'token_version' not in body
    assert 'lookup_hash' not in client.get('/api/me/orders',headers=tokens['alice']).text

def test_disabled_user_invalidates_token(client,tokens):
    with SessionLocal() as db:
        uid=db.scalar(select(User.id).where(User.name=='alice'))
    assert client.patch(f'/api/admin/users/{uid}',json={'active':False,'role':'user'},headers=tokens['admin']).status_code==200
    assert client.get('/api/me/wallet',headers=tokens['alice']).status_code==401
    assert client.post('/api/auth/login',json={'email':'alice@example.com','password':'correct-password'}).status_code==401

def test_rate_limit_and_strict_money(client,tokens):
    for amount in [True,1.25,-10]:
        assert client.post('/api/me/wallet/demo-recharge',json={'amount':amount},headers=key(tokens['alice'])).status_code==422
    statuses=[client.post('/api/auth/login',json={'email':'alice@example.com','password':'wrong-password'}).status_code for _ in range(11)]
    assert statuses[:10]==[401]*10
    assert statuses[-1]==429

def test_registration_cannot_assign_role_and_admin_self_protection(client,tokens):
    assert client.post('/api/auth/register',json={'email':'evil@example.com','password':'long-password','role':'admin'}).status_code==422
    with SessionLocal() as db:
        uid=db.scalar(select(User.id).where(User.name=='admin'))
    assert client.patch(f'/api/admin/users/{uid}',json={'active':False,'role':'user'},headers=tokens['admin']).status_code==409

def test_idempotency_key_required(client,tokens):
    assert client.post('/api/orders',json={'product_id':1,'expected_amount':1000},headers=tokens['alice']).status_code==422
    assert client.post('/api/orders',json={'product_id':1,'expected_amount':1000},headers={**tokens['alice'],'Idempotency-Key':'short'}).status_code==422
