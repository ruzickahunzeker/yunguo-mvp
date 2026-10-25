from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import select, func
import pytest
from app.main import app
from app.core.db import SessionLocal
from app.core.security import hash_password, token_for
from app.models import User, Agent, Wallet, AgentRelation, AuditLog, Order, WalletTransaction, RedeemCode, now
from app.services.commerce import move_wallet, purchase, issue_codes
from app.schemas.requests import CodeBatch


def members():
    with SessionLocal() as db:
        for name in ('alice','bob'):
            user=db.scalar(select(User).where(User.name==name));user.role='agent';db.add(Agent(user_id=user.id))
        db.commit()
        return {u.name:u.id for u in db.scalars(select(User))}


def assign(client,tokens,child,parent,expected=None):
    return client.put(f'/api/admin/agents/{child}/parent',headers=tokens['admin'],json={'parent_id':parent,'expected_parent_id':expected})


def second_admin():
    with SessionLocal() as db:
        user=User(email='team-admin@example.com',name='team-admin',role='admin',password_hash=hash_password('correct-password'))
        db.add(user);db.flush();db.add(Wallet(user_id=user.id));db.commit()
        return {'admin':{'Authorization':'Bearer '+token_for(user)}}


def test_assignment_visibility_privacy_and_unlink(client,tokens):
    ids=members()
    assert assign(client,tokens,ids['alice'],ids['agent']).status_code==200
    with SessionLocal() as db:
        a=db.get(User,ids['alice']);move_wallet(db,a.id,5000,'fund','adjust')
        purchase(db,a,1,'a'*20,800)
        issue_codes(db,db.get(User,ids['admin']),CodeBatch(product_id=1,quantity=3,owner_id=a.id))
        move_wallet(db,a.id,-1600,'cards','code_purchase')
        db.commit()
    r=client.get('/api/agent/team',headers=tokens['agent']);assert r.status_code==200,r.text
    data=r.json();assert data['total']==1
    row=data['items'][0];assert row['id']==ids['alice']
    assert row['order_count']==1 and row['net_amount']==800 and row['code_count']==3 and row['code_purchase_amount']==1600
    assert data['summary']['net_amount']==800
    for private in ('email','password_hash','token_version','balance','lookup_hash','code_hash','idempotency_key'):
        assert private not in row
    assert client.get('/api/agent/team',headers=tokens['bob']).json()['total']==0
    assert assign(client,tokens,ids['alice'],None,ids['agent']).status_code==200
    assert client.get('/api/agent/team',headers=tokens['agent']).json()['total']==0
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=='agents.assign-parent'))==2


def test_no_self_cycles_depth_or_stale_forms(client,tokens):
    ids=members();a,b,c=ids['agent'],ids['alice'],ids['bob']
    assert assign(client,tokens,a,a).status_code==409
    assert assign(client,tokens,b,a).status_code==200
    assert assign(client,tokens,b,a).status_code==409 # old form
    assert assign(client,tokens,b,a,a).status_code==200 # no duplicate audit
    assert assign(client,tokens,a,b).status_code==409
    assert assign(client,tokens,c,b).status_code==409
    assert assign(client,tokens,a,c).status_code==409
    assert assign(client,tokens,b,c,a).status_code==200
    assert client.get('/api/agent/team',headers=tokens['agent']).json()['total']==0
    assert client.get('/api/agent/team',headers=tokens['bob']).json()['total']==1


@pytest.mark.parametrize('actor',['alice','agent'])
def test_member_cannot_assign_or_access_admin_teams(client,tokens,actor):
    ids=members()
    assert client.put(f'/api/admin/agents/{ids["alice"]}/parent',headers=tokens[actor],json={'parent_id':ids['agent'],'expected_parent_id':None}).status_code==403
    assert client.get(f'/api/admin/agents/{ids["agent"]}/team',headers=tokens[actor]).status_code==403


def test_ordinary_user_blocked_and_parameter_cannot_select_other_parent(client,tokens):
    assert client.get('/api/agent/team',headers=tokens['alice']).status_code==403
    ids=members();assert assign(client,tokens,ids['alice'],ids['agent']).status_code==200
    assert client.get('/api/agent/team',params={'parent_id':ids['agent']},headers=tokens['bob']).json()['total']==0
    assert client.get('/api/agent/team',headers=tokens['admin']).status_code==403


def test_disabled_role_changed_and_invalid_targets(client,tokens):
    ids=members()
    with SessionLocal() as db:
        db.get(User,ids['alice']).active=False;db.commit()
    assert assign(client,tokens,ids['alice'],ids['agent']).status_code==409
    assert assign(client,tokens,ids['bob'],999999).status_code==409
    assert assign(client,tokens,999999,ids['agent']).status_code==404
    with SessionLocal() as db:
        db.get(User,ids['alice']).active=True;db.commit()
    assert assign(client,tokens,ids['alice'],ids['agent']).status_code==200
    with SessionLocal() as db:
        db.get(User,ids['alice']).role='user';db.commit()
    assert client.get('/api/agent/team',headers=tokens['agent']).json()['total']==0


def test_dates_refund_pagination_no_join_multiplication(client,tokens):
    ids=members()
    for child in ('alice','bob'):assert assign(client,tokens,ids[child],ids['agent']).status_code==200
    with SessionLocal() as db:
        a=db.get(User,ids['alice']);move_wallet(db,a.id,5000,'fund','adjust')
        order_id=purchase(db,a,1,'z'*20,800)['order_id']
        order=db.get(Order,order_id);order.created_at=datetime(2026,1,2,tzinfo=timezone.utc);order.payment_status='REFUNDED'
        issue_codes(db,db.get(User,ids['admin']),CodeBatch(product_id=1,quantity=4,owner_id=a.id))
        db.commit()
    params={'start':'2026-01-02','end':'2026-01-02','page_size':1}
    data=client.get('/api/agent/team',params=params,headers=tokens['agent']).json()
    assert data['total']==2 and len(data['items'])==1
    assert data['summary']['order_count']==1 and data['summary']['gross_amount']==800
    assert data['summary']['refund_amount']==800 and data['summary']['net_amount']==0
    assert data['summary']['code_count']==4 # inventory is current, not date filtered
    later=client.get('/api/agent/team',params={**params,'page':3},headers=tokens['agent']).json()
    assert later['items']==[] and later['total']==2 and later['summary']==data['summary']
    zero=client.get('/api/agent/team',params={**params,'end':'2026-01-01'},headers=tokens['agent'])
    assert zero.status_code==422
    assert client.get('/api/agent/team',params={'start':'bad'},headers=tokens['agent']).status_code==422
    assert client.get('/api/agent/team',params={'q':'%_'},headers=tokens['agent']).json()['total']==0
    admin=client.get(f'/api/admin/agents/{ids["agent"]}/team',params=params,headers=tokens['admin'])
    assert admin.status_code==200 and admin.json()['summary']==data['summary']


def test_concurrent_edges_cannot_make_chain(client,tokens):
    ids=members();other=second_admin()
    def request(item):
        index,pair=item
        with TestClient(app) as c:return assign(c,tokens if index==0 else other,*pair).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        result=list(pool.map(request,enumerate([(ids['alice'],ids['agent']),(ids['bob'],ids['alice'])])))
    assert sorted(result)==[200,409]
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(AgentRelation))==1


def test_concurrent_reassignment_stale_state_single_winner(client,tokens):
    ids=members();other=second_admin()
    def request(item):
        index,parent=item
        with TestClient(app) as c:return assign(c,tokens if index==0 else other,ids['alice'],parent).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        result=list(pool.map(request,enumerate([ids['agent'],ids['bob']])))
    assert sorted(result)==[200,409]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AgentRelation))==1
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=='agents.assign-parent'))==1
