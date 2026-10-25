import csv
from datetime import datetime, timezone
from io import StringIO
from sqlalchemy import select, func
from app.core.db import SessionLocal
from app.models import AuditLog, User

URL='/api/admin/audit-logs'
PERIOD={'start':'2026-01-01','end':'2026-01-03'}

def fixtures():
    with SessionLocal() as db:
        users={u.name:u.id for u in db.scalars(select(User))}
        for stamp,actor,action,target,detail in [
            ('2025-12-31T23:59:59+00:00','admin','products.save','old','before'),
            ('2026-01-01T00:00:00+00:00','admin','products.save','ITEM%_one','first'),
            ('2026-01-02T12:00:00+00:00','alice','auth.email-verified','account','verified'),
            ('2026-01-03T23:59:59+00:00','admin','products.save','item%_two','last'),
            ('2026-01-04T00:00:00+00:00','admin','products.save','later','after')]:
            db.add(AuditLog(actor_id=users[actor],action=action,target=target,detail=detail,created_at=datetime.fromisoformat(stamp)))
        db.commit()
    return users

def get(client,tokens,**params):
    result=client.get(URL,params=params,headers=tokens['admin'])
    assert result.status_code==200,result.text
    return result.json()

def test_list_and_export_backend_permissions(client,tokens):
    for path in [URL,URL+'/export']:
        assert client.get(path).status_code==401
        for name in ['alice','agent']:
            assert client.get(path,headers=tokens[name]).status_code==403

def test_default_compatibility_order_and_page_validation(client,tokens):
    fixtures();data=get(client,tokens,page_size=2)
    assert data['total']==5 and [r['id'] for r in data['items']]==[5,4]
    assert set(data)=={'items','total','page','page_size','snapshot_id'}
    assert data['snapshot_id']==5
    assert [r['id'] for r in get(client,tokens,page=2,page_size=2)['items']]==[3,2]
    assert get(client,tokens,page=99)['items']==[]
    for params in [{'page':0},{'page_size':101}]:
        assert client.get(URL,params=params,headers=tokens['admin']).status_code==422

def test_utc_date_filters_include_boundaries_and_actor_and_action(client,tokens):
    users=fixtures();data=get(client,tokens,**PERIOD)
    assert [r['id'] for r in data['items']]==[4,3,2]
    result=get(client,tokens,**PERIOD,actor_id=users['admin'],action='products.save')
    assert [r['id'] for r in result['items']]==[4,2]
    assert get(client,tokens,**PERIOD,action='products')['total']==0
    assert get(client,tokens,actor_id=99999)['total']==0
    assert get(client,tokens,**PERIOD)['items'][0]['created_at'].endswith('+00:00')

def test_target_literal_wildcards_case_and_sql_text(client,tokens):
    fixtures()
    assert get(client,tokens,target='%_')['total']==2
    assert get(client,tokens,target='ITEM%_ONE')['items'][0]['id']==2
    assert get(client,tokens,target="' OR 1=1 --")['total']==0
    assert get(client,tokens,target='no match')['total']==0

def test_snapshot_upper_bound_survives_new_logs_and_export_self_record(client,tokens):
    users=fixtures();first=get(client,tokens,page_size=2)
    with SessionLocal() as db:
        db.add(AuditLog(actor_id=users['admin'],action='later',target='new',detail=''))
        db.commit()
    second=get(client,tokens,page_size=2,page=2,snapshot_id=first['snapshot_id'])
    assert [r['id'] for r in second['items']]==[3,2] and second['total']==5
    assert get(client,tokens)['total']==6
    response=client.get(URL+'/export',params={'snapshot_id':5},headers=tokens['admin'])
    records=list(csv.DictReader(StringIO(response.content.decode('utf-8-sig'))))
    assert [r['id'] for r in records]==['5','4','3','2','1']
    assert not any(r['action']=='audit.export' for r in records)
    assert get(client,tokens,snapshot_id=5)['total']==5
    assert get(client,tokens)['total']==7

def test_snapshot_zero_empty_and_future_clamped(client,tokens):
    assert get(client,tokens)['snapshot_id']==0
    response=client.get(URL+'/export',params={'snapshot_id':0},headers=tokens['admin'])
    assert list(csv.DictReader(StringIO(response.content.decode('utf-8-sig'))))==[]
    assert get(client,tokens,snapshot_id=0)['total']==0
    assert get(client,tokens,snapshot_id=999999)['snapshot_id']==1

def test_filter_validation(client,tokens):
    for params in [{'start':'2026-01-01'}, {'end':'2026-01-01'},
        {'start':'2026-01-03','end':'2026-01-01'},
        {'start':'2025-01-01','end':'2026-01-02'},
        {'start':'9999-12-31','end':'9999-12-31'},
        {'start':'invalid','end':'2026-01-01'},
        {'actor_id':0},{'actor_id':2**63},{'snapshot_id':-1},{'action':''},{'target':''},
        {'action':'a'*61},{'target':'a'*101}]:
        for path in [URL,URL+'/export']:
            assert client.get(path,params=params,headers=tokens['admin']).status_code==422
    assert get(client,tokens,start='2024-01-01',end='2024-12-31')['total']==0

def test_csv_safe_text_multiline_bom_and_audited_filters(client,tokens):
    users=fixtures()
    inputs=['=SUM(1,2)','  +cmd','\ufeff@formula','-1+2','\tplain','\rline','\nline','quote,"comma"\ntext','普通中文','<script>alert(1)</script>']
    with SessionLocal() as db:
        for value in inputs:
            db.add(AuditLog(actor_id=users['admin'],action='test.csv',target=value,detail=value,created_at=datetime(2026,1,2,tzinfo=timezone.utc)))
        db.commit()
    result=client.get(URL+'/export',params={**PERIOD,'action':'test.csv'},headers=tokens['admin'])
    assert result.status_code==200 and result.content.startswith(b'\xef\xbb\xbf')
    assert result.headers['cache-control']=='no-store'
    assert result.headers['content-type'].startswith('text/csv')
    assert result.headers['x-export-rows']==str(len(inputs))
    assert 'audit-logs-15.csv' in result.headers['content-disposition']
    records=list(csv.DictReader(StringIO(result.content.decode('utf-8-sig'))))
    assert len(records)==len(inputs)
    for raw,record in zip(reversed(inputs),records):
        expected="'"+raw if raw in inputs[:7] else raw
        assert record['detail']==expected and record['target']==expected
        assert record['created_at'].endswith('+00:00')
    with SessionLocal() as db:
        log=db.scalar(select(AuditLog).where(AuditLog.action=='audit.export'))
        assert log.actor_id==users['admin'] and 'rows=10' in log.detail
        assert 'action_filtered=True' in log.detail
        assert 'test.csv' not in log.detail
    assert not any(s in result.text for s in ['password_hash','token_version','@example.com'])

def test_export_cap_rejects_without_truncation_or_success_audit(client,tokens,monkeypatch):
    fixtures();monkeypatch.setattr(__import__('app.api.audit_logs',fromlist=['x']),'EXPORT_LIMIT',2)
    result=client.get(URL+'/export',headers=tokens['admin'])
    assert result.status_code==413
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=='audit.export'))==0
    # Exactly at the limit succeeds.
    assert client.get(URL+'/export',params={'snapshot_id':2},headers=tokens['admin']).status_code==200

def test_export_account_rate_limit_and_read_no_write(client,tokens):
    fixtures()
    before=get(client,tokens)['total']
    for i in range(5):
        result=client.get(URL+'/export',headers={**tokens['admin'],'X-Forwarded-For':f'10.0.0.{i}'})
        assert result.status_code==200
    assert client.get(URL+'/export',headers=tokens['admin']).status_code==429
    assert get(client,tokens)['total']==before+5


def test_csv_unicode_whitespace_and_control_formula_prefixes():
    from app.services.audit_logs import csv_text
    for value in ['\u00a0=SUM(1,2)', '\x00@cmd', '\u2003+1', '\ufeff -1', '\ttext', '\rtext', '\ntext']:
        assert csv_text(value)=="'"+value
    for value in ['normal', '普通中文', 'a,b\ntext', '123', "'already quoted"]:
        assert csv_text(value)==value
