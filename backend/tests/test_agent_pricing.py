from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.core.db import SessionLocal
from app.models import User, Agent, AgentLevel, Order, Product, WalletTransaction
from app.main import app
from .test_commerce import key


def agent_id():
    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.name=='agent'))

def level(client,tokens,name='高级代理'):
    r=client.post('/api/admin/agent-levels',json={'name':name},headers=tokens['admin'])
    assert r.status_code==201,r.text
    return r.json()['id']

def quote(client,tokens):
    return client.get('/api/agent/prices',headers=tokens['agent']).json()[0]

def buy_agent(client,tokens,amount,request_headers=None):
    return client.post('/api/orders',json={'product_id':1,'expected_amount':amount},headers=request_headers or key(tokens['agent']))

def topup_agent(client,tokens,amount=10000):
    assert client.post('/api/me/wallet/demo-recharge',json={'amount':amount},headers=key(tokens['agent'])).status_code==200

def test_level_crud_and_backend_permissions(client,tokens):
    assert client.get('/api/admin/agent-levels').status_code==401
    for name in ['alice','agent']:
        for endpoint in ['/api/admin/agent-levels','/api/admin/agents']:
            assert client.get(endpoint,headers=tokens[name]).status_code==403
        assert client.put(f'/api/admin/agents/{agent_id()}/products/1',json={'price':1},headers=tokens[name]).status_code==403
    lid=level(client,tokens)
    assert lid!=1
    assert client.post('/api/admin/agent-levels',json={'name':'高级代理'},headers=tokens['admin']).status_code==409
    assert client.put(f'/api/admin/agent-levels/{lid}',json={'name':'高级代理·更新','active':False,'sort':10},headers=tokens['admin']).status_code==200
    assert len(client.get('/api/admin/agent-levels',headers=tokens['admin']).json())==2

def test_price_precedence_and_restoring_inheritance(client,tokens):
    uid=agent_id();lid=level(client,tokens)
    assert quote(client,tokens)['effective_price']==800
    assert quote(client,tokens)['price_source']=='agent_default'
    assert client.put(f'/api/admin/agents/{uid}/level',json={'level_id':lid},headers=tokens['admin']).status_code==200
    assert client.put(f'/api/admin/agent-levels/{lid}/prices/1',json={'price':650},headers=tokens['admin']).status_code==200
    assert quote(client,tokens)['effective_price']==650 and quote(client,tokens)['price_source']=='level'
    assert client.put(f'/api/admin/agents/{uid}/products/1',json={'price':500,'allowed':True},headers=tokens['admin']).status_code==200
    assert quote(client,tokens)['effective_price']==500 and quote(client,tokens)['price_source']=='agent_override'
    assert client.put(f'/api/admin/agents/{uid}/products/1',json={'price':None,'allowed':True},headers=tokens['admin']).status_code==200
    assert quote(client,tokens)['effective_price']==650
    assert client.delete(f'/api/admin/agents/{uid}/products/1',headers=tokens['admin']).status_code==200
    assert client.delete(f'/api/admin/agent-levels/{lid}/prices/1',headers=tokens['admin']).status_code==200
    assert quote(client,tokens)['effective_price']==800

def test_override_zero_price_and_actual_wallet_amount(client,tokens):
    topup_agent(client,tokens)
    uid=agent_id()
    assert client.put(f'/api/admin/agents/{uid}/products/1',json={'price':0,'allowed':True},headers=tokens['admin']).status_code==200
    assert quote(client,tokens)['effective_price']==0
    assert buy_agent(client,tokens,0).status_code==201
    assert client.get('/api/me/wallet',headers=tokens['agent']).json()['balance']==10000
    with SessionLocal() as db:
        assert db.scalar(select(Order.amount))==0
        assert db.get(Product,1).stock==99
        assert db.scalar(select(func.count()).select_from(WalletTransaction).where(WalletTransaction.kind=='purchase'))==1

def test_forbidden_product_rejected_server_and_no_side_effect(client,tokens):
    topup_agent(client,tokens);uid=agent_id()
    assert client.put(f'/api/admin/agents/{uid}/products/1',json={'price':500,'allowed':False},headers=tokens['admin']).status_code==200
    decision=quote(client,tokens)
    assert decision['can_purchase'] is False
    assert buy_agent(client,tokens,500).status_code==403
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order))==0
        assert db.get(Product,1).stock==100
    assert client.get('/api/me/wallet',headers=tokens['agent']).json()['balance']==10000

def test_disabled_level_and_forbidden_assignment(client,tokens):
    topup_agent(client,tokens);uid=agent_id()
    assert client.put('/api/admin/agent-levels/1',json={'name':'暂停等级','active':False},headers=tokens['admin']).status_code==200
    assert quote(client,tokens)['can_purchase'] is False
    assert buy_agent(client,tokens,800).status_code==403
    overview=client.get('/api/agent/overview',headers=tokens['agent']).json()
    assert overview['level']=='暂停等级' and overview['level_active'] is False
    assert client.put(f'/api/admin/agents/{uid}/level',json={'level_id':1},headers=tokens['admin']).status_code==409
    assert client.get('/api/me/orders',headers=tokens['agent']).status_code==200
    assert client.get('/api/me/wallet',headers=tokens['agent']).status_code==200

def test_price_change_rejected_before_any_charge_and_replay_stable(client,tokens):
    topup_agent(client,tokens);uid=agent_id()
    h=key(tokens['agent'])
    assert client.put(f'/api/admin/agents/{uid}/products/1',json={'price':700},headers=tokens['admin']).status_code==200
    stale=buy_agent(client,tokens,800,h)
    assert stale.status_code==409 and stale.headers['x-error-code']=='PRICE_CHANGED'
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order))==0
        assert db.get(Product,1).stock==100
    paid=buy_agent(client,tokens,700,h)
    assert paid.status_code==201
    assert client.put(f'/api/admin/agents/{uid}/products/1',json={'price':600,'allowed':False},headers=tokens['admin']).status_code==200
    assert buy_agent(client,tokens,700,h).json()==paid.json()
    assert buy_agent(client,tokens,600,h).status_code==409
    assert client.get('/api/me/wallet',headers=tokens['agent']).json()['balance']==9300

def test_expected_amount_required_strict_and_regular_users_protected(client,tokens):
    for body in [{'product_id':1},{'product_id':1,'expected_amount':True},{'product_id':1,'expected_amount':10.5}]:
        assert client.post('/api/orders',json=body,headers=key(tokens['alice'])).status_code==422
    assert client.post('/api/orders',json={'product_id':1,'expected_amount':999},headers=key(tokens['alice'])).status_code==409

def test_rule_isolation_and_effective_price_not_leaked(client,tokens):
    uid=agent_id()
    assert client.put(f'/api/admin/agents/{uid}/products/1',json={'price':123},headers=tokens['admin']).status_code==200
    public=client.get('/api/products/1').json()
    assert public['price']==1000 and 'override_price' not in public
    assert client.get('/api/agent/prices',headers=tokens['alice']).status_code==403
    assert client.get('/api/agent/prices',headers=tokens['admin']).json()[0]['effective_price']==1000
    with SessionLocal() as db:
        bob=db.scalar(select(User).where(User.name=='bob'));bob.role='agent';db.add(Agent(user_id=bob.id));db.commit()
    # Existing JWT valid role change here is fixture-only; service reads DB role.
    assert client.get('/api/agent/prices',headers=tokens['bob']).json()[0]['effective_price']==800

def test_validation_and_missing_targets(client,tokens):
    uid=agent_id()
    for amount in [-1,True,1.5]:
        assert client.put('/api/admin/agent-levels/1/prices/1',json={'price':amount},headers=tokens['admin']).status_code==422
        assert client.put(f'/api/admin/agents/{uid}/products/1',json={'price':amount},headers=tokens['admin']).status_code==422
    assert client.put('/api/admin/agent-levels/1/prices/9999',json={'price':10},headers=tokens['admin']).status_code==404
    assert client.put(f'/api/admin/agents/{uid}/level',json={'level_id':9999},headers=tokens['admin']).status_code==409
    assert client.put('/api/admin/agents/9999/products/1',json={'price':10},headers=tokens['admin']).status_code==404
    assert client.post('/api/admin/agent-levels',json={'name':'   '},headers=tokens['admin']).status_code==422

def test_admin_queries_pagination_and_audit(client,tokens):
    uid=agent_id()
    lid=level(client,tokens,'批发等级')
    assert client.put(f'/api/admin/agents/{uid}/level',json={'level_id':lid},headers=tokens['admin']).status_code==200
    assert client.put(f'/api/admin/agents/{uid}/products/1',json={'price':500},headers=tokens['admin']).status_code==200
    result=client.get('/api/admin/agents',params={'q':'agent@','level_id':lid,'page_size':1},headers=tokens['admin']).json()
    assert result['total']==1 and result['items'][0]['level_name']=='批发等级'
    assert 'password_hash' not in str(result) and 'token_version' not in str(result)
    result=client.get(f'/api/admin/agents/{uid}/products',headers=tokens['admin']).json()
    assert result['items'][0]['override_price']==500 and result['items'][0]['effective_price']==500
    actions=[item['action'] for item in client.get('/api/admin/audit-logs',headers=tokens['admin']).json()['items']]
    assert {'agent-levels.create','agents.assign-level','agents.product-rule'}<=set(actions)

def test_prepaid_codes_survive_level_disabling(client,tokens):
    uid=agent_id()
    r=client.post('/api/admin/codes/generate',json={'product_id':1,'quantity':1,'owner_id':uid},headers=tokens['admin'])
    assert r.status_code==201;raw=r.json()['codes'][0]
    assert client.put('/api/admin/agent-levels/1',json={'name':'一级代理','active':False},headers=tokens['admin']).status_code==200
    assert client.post('/api/redeem',json={'code':raw},headers=key()).status_code==200

def test_concurrent_price_update_cannot_change_confirmed_charge(client,tokens):
    topup_agent(client,tokens);uid=agent_id()
    def request(i):
        with TestClient(app) as c:
            if i==0:return c.put(f'/api/admin/agents/{uid}/products/1',json={'price':600},headers=tokens['admin']).status_code
            return buy_agent(c,tokens,800).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses=list(pool.map(request,range(4)))
    assert statuses[0]==200
    assert all(s in (201,409) for s in statuses[1:])
    with SessionLocal() as db:
        assert all(o.amount==800 for o in db.scalars(select(Order)))
        total=db.scalar(select(func.coalesce(func.sum(Order.amount),0)))
    assert client.get('/api/me/wallet',headers=tokens['agent']).json()['balance']==10000-total

def test_concurrent_level_price_update_and_purchase(client,tokens):
    topup_agent(client,tokens)
    def request(i):
        with TestClient(app) as c:
            if i==0:return c.put('/api/admin/agent-levels/1/prices/1',json={'price':600},headers=tokens['admin']).status_code
            return buy_agent(c,tokens,800).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses=list(pool.map(request,range(4)))
    assert statuses[0]==200 and all(s in (201,409) for s in statuses[1:])
    with SessionLocal() as db:assert all(o.amount==800 for o in db.scalars(select(Order)))
