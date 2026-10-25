"""Run only against a new, disposable Compose stack. Creates test accounts/orders.
Usage from project root: .venv/bin/python scripts/smoke_compose.py
No credentials, tokens or full card codes are printed or saved.
"""
import json
import os
import csv
from io import StringIO
import secrets
import subprocess
import time
from uuid import uuid4
import httpx


def request_key(token):
    return {'Authorization': 'Bearer '+token, 'Idempotency-Key': str(uuid4())}

def exercise_monitor_recovery(client, token):
    """Opt-in only: stop this disposable stack's worker, then always restart it."""
    def state():
        response=client.get('/api/admin/operations/monitor',headers=request_key(token))
        assert response.status_code==200
        return {w['service']:w['status'] for w in response.json()['workers']}
    def find_alert(status):
        response=client.get('/api/admin/operations/alerts',params={'status':status},headers=request_key(token))
        assert response.status_code==200
        return next((a for a in response.json()['items'] if a['code']=='WORKER_STALE' and a['scope']=='fulfillment'),None)
    subprocess.run(['docker','compose','stop','worker'],check=True,capture_output=True)
    try:
        deadline=time.monotonic()+110
        found=None
        while time.monotonic()<deadline:
            found=find_alert('OPEN')
            if state()['fulfillment']=='STALE' and found:
                break
            time.sleep(1)
        assert found and state()['fulfillment']=='STALE'
        identity=found['id']
        print('PASS: actual stopped fulfillment process becomes STALE and creates persistent worker alert',flush=True)
    finally:
        subprocess.run(['docker','compose','start','worker'],check=True,capture_output=True)
    deadline=time.monotonic()+50
    while time.monotonic()<deadline:
        found=find_alert('RESOLVED')
        if state()['fulfillment']=='RECENT' and found and found['id']==identity:
            break
        time.sleep(1)
    assert found and found['id']==identity and state()['fulfillment']=='RECENT'
    print('PASS: restarted worker reports fresh heartbeat and same alert automatically resolves',flush=True)


def main():
    with httpx.Client(base_url=os.environ.get('SMOKE_BASE_URL','http://127.0.0.1:8080'), timeout=15) as client:
        response=client.get('/')
        assert response.status_code==200 and '云果' in response.text
        assert "default-src 'self'" in response.headers['content-security-policy']
        for path in ['/products/1','/redeem','/lookup','/me/orders','/admin/dashboard','/admin/reports','/admin/audit-logs','/admin/operations','/admin/monitoring']:
            assert client.get(path).status_code==200
        health=client.get('/api/health')
        assert health.status_code==200 and health.json()['status']=='ok'
        products=client.get('/api/products').json()['items']
        assert products
        product=products[0]
        # Initialize a temporary QA administrator with a fresh random password via
        # the supported CLI. Pass password only through stdin to docker exec.
        password=secrets.token_urlsafe(24)
        admin_email=f'qa-admin-{uuid4().hex[:10]}@example.com'
        script="""
import json, os, sys
from app.cli import main
payload=json.loads(sys.stdin.read())
os.environ['ADMIN_PASSWORD']=payload['password']
sys.argv=['cli','create-admin','--email',payload['email']]
main()
"""
        subprocess.run(['docker','compose','exec','-T','api','python','-c',script],
            input=json.dumps({'email':admin_email,'password':password}),text=True,capture_output=True,check=True)
        auth=client.post('/api/auth/login',json={'email':admin_email,'password':password})
        assert auth.status_code==200
        admin_token=auth.json()['access_token']
        user=client.post('/api/auth/register',json={'email':f'qa-user-{uuid4().hex[:10]}@example.com','password':secrets.token_urlsafe(24),'name':'容器验收用户'})
        assert user.status_code==201
        token=user.json()['access_token']
        recharge=client.post('/api/me/wallet/demo-recharge',json={'amount':100000},headers=request_key(token))
        assert recharge.status_code==200
        purchase_headers=request_key(token)
        order=client.post('/api/orders',json={'product_id':product['id'],'expected_amount':product['price']},headers=purchase_headers)
        assert order.status_code==201
        assert client.post('/api/orders',json={'product_id':product['id'],'expected_amount':product['price']},headers=purchase_headers).json()==order.json()
        assert client.get('/api/me/wallet',headers=request_key(token)).json()['balance']==100000-product['price']
        codes=client.post('/api/admin/codes/generate',json={'product_id':product['id'],'quantity':1},headers=request_key(admin_token))
        assert codes.status_code==201
        code=codes.json()['codes'][0]
        redeem_headers={'Idempotency-Key':str(uuid4())}
        redemption=client.post('/api/redeem',json={'code':code},headers=redeem_headers)
        assert redemption.status_code==200
        assert client.post('/api/redeem',json={'code':code},headers=redeem_headers).json()==redemption.json()
        receipt=redemption.json()
        for _ in range(20):
            state=client.post('/api/orders/lookup',json={'order_id':receipt['order_id'],'lookup_token':receipt['lookup_token']})
            assert state.status_code==200
            if state.json()['fulfillment_status']=='COMPLETED':
                break
            time.sleep(.5)
        assert state.json()['fulfillment_status']=='COMPLETED'
        assert client.get('/api/admin/users',headers=request_key(token)).status_code==403
        assert client.get('/api/admin/dashboard',headers=request_key(admin_token)).status_code==200
        report=client.get('/api/admin/reports/sales',headers=request_key(admin_token))
        assert report.status_code==200
        report=report.json()
        assert report['timezone']=='UTC' and len(report['daily'])==30
        for metric in ('orders','gross_amount','refund_amount','net_amount'):
            assert sum(day[metric] for day in report['daily'])==report['summary'][metric]
        export=client.get('/api/admin/reports/sales/export',headers=request_key(admin_token))
        assert export.status_code==200 and export.headers['cache-control']=='no-store'
        daily=list(csv.DictReader(StringIO(export.content.decode('utf-8-sig'))))
        assert daily[-1]['date_utc']=='TOTAL'
        for metric in ('orders','gross_amount','refund_amount','net_amount'):
            assert int(daily[-1][metric])==report['summary'][metric]
        assert client.get('/api/admin/reports/sales',headers=request_key(token)).status_code==403
        assert client.get('/api/admin/reports/sales/export',headers=request_key(token)).status_code==403
        audit_data=client.get('/api/admin/audit-logs',params={'action':'codes.generate'},headers=request_key(admin_token))
        assert audit_data.status_code==200
        audit_data=audit_data.json()
        audit_file=client.get('/api/admin/audit-logs/export',params={'action':'codes.generate','snapshot_id':audit_data['snapshot_id']},headers=request_key(admin_token))
        assert audit_file.status_code==200 and audit_file.headers['cache-control']=='no-store'
        audit_rows=list(csv.DictReader(StringIO(audit_file.content.decode('utf-8-sig'))))
        assert len(audit_rows)==audit_data['total'] and len(audit_rows)>0
        assert all(item['action']=='codes.generate' and int(item['id'])<=audit_data['snapshot_id'] for item in audit_rows)
        assert client.get('/api/admin/audit-logs',headers=request_key(token)).status_code==403
        assert client.get('/api/admin/audit-logs/export',headers=request_key(token)).status_code==403
        print('PASS: audit filters, ID ceiling, CSV row count, no-store and admin-only access')
        operation=client.get('/api/admin/operations/summary',headers=request_key(admin_token))
        assert operation.status_code==200 and operation.headers['cache-control']=='no-store'
        operation=operation.json()
        assert operation['fulfillment_mode']=='mock' and operation['stale_minutes']==30
        assert set(operation['mail'])=={'password_reset','email_verification'}
        for kind in ('queued','attention','refundable','exhausted','stale'):
            result=client.get('/api/admin/operations/orders',params={'kind':kind},headers=request_key(admin_token))
            assert result.status_code==200 and 'total' in result.json()
            assert 'lookup_hash' not in result.text and 'idempotency_key' not in result.text
        for path in ('/summary','/orders'):
            assert client.get('/api/admin/operations'+path,headers=request_key(token)).status_code==403
        print('PASS: operations modes, queue summary/categories, no-store and admin-only access')
        for _ in range(20):
            monitor=client.get('/api/admin/operations/monitor',headers=request_key(admin_token))
            assert monitor.status_code==200
            monitor=monitor.json()
            workers={w['service']:w['status'] for w in monitor['workers']}
            if workers['fulfillment']=='RECENT' and workers['monitor']=='RECENT':
                break
            time.sleep(1)
        assert workers['fulfillment']=='RECENT' and workers['monitor']=='RECENT'
        assert monitor['last_checked_at'] is not None
        assert client.get('/api/admin/operations/alerts',headers=request_key(admin_token)).status_code==200
        for path in ('/monitor','/alerts'):
            assert client.get('/api/admin/operations'+path,headers=request_key(token)).status_code==403
        print('PASS: real fulfillment/monitor process heartbeats and persisted alert endpoints')
        if os.environ.get('SMOKE_MONITOR_RECOVERY')=='true':
            exercise_monitor_recovery(client,admin_token)
        print('PASS: report UTC totals/daily, CSV monetary totals, no-store and backend role isolation')
        print('PASS: Nginx SPA routes/CSP, health, CLI administrator, registration/login, Redis-limited API, wallet recharge/purchase idempotency, card generation/redemption, worker completion, role isolation')
    result=subprocess.run(['docker','compose','exec','-T','api','python','-m','app.cli','reconcile'],text=True,capture_output=True,check=True)
    assert "'mismatched_user_ids': []" in result.stdout
    print('PASS: container wallet ledger reconciliation')

if __name__=='__main__':
    main()
