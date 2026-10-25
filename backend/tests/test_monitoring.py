from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.core.config import get_settings, Settings
from app.core.db import SessionLocal
from app.main import app
from app.models import WorkerHeartbeat, MonitorState, OperationalAlert, AlertEvent, User, AuditLog
from app.services import monitoring

AT=datetime(2026,10,17,0,tzinfo=timezone.utc)
URL='/api/admin/operations'

def sample(code='ORDER_ATTENTION',count=2):
    return {'alerts':[{'code':code,'count':count,'severity':'warning'}]}

def freeze(monkeypatch):
    monkeypatch.setattr(monitoring,'now',lambda:AT)

def reconcile(value,at=AT):
    with SessionLocal() as db:
        monitoring.reconcile(db,value,[],at);db.commit()
        return db.scalar(select(OperationalAlert.id))

def alert(db):
    return db.scalar(select(OperationalAlert))

def request_ack(client,tokens,identity,occurrence=1,note='已安排人工核查'):
    return client.post(f'{URL}/alerts/{identity}/acknowledge',headers=tokens['admin'],json={'note':note,'expected_occurrences':occurrence})

def test_permissions_for_monitor_alerts_events_and_ack(client,tokens):
    identity=reconcile(sample())
    for path in ['/monitor','/alerts',f'/alerts/{identity}/events']:
        assert client.get(URL+path).status_code==401
        for role in ['alice','agent']:
            assert client.get(URL+path,headers=tokens[role]).status_code==403
    for role in ['alice','agent']:
        assert client.post(f'{URL}/alerts/{identity}/acknowledge',headers=tokens[role],json={'note':'test','expected_occurrences':1}).status_code==403

def test_heartbeat_upsert_does_not_regress_and_multiple_replicas(monkeypatch):
    freeze(monkeypatch);monitoring.heartbeat('fulfillment')
    monkeypatch.setattr(monitoring,'now',lambda:AT-timedelta(seconds=1));monitoring.heartbeat('fulfillment')
    with SessionLocal() as db:
        assert monitoring.utc(db.get(WorkerHeartbeat,'fulfillment').last_seen_at)==AT
        assert db.scalar(select(func.count()).select_from(WorkerHeartbeat))==1
    freeze(monkeypatch)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:monitoring.heartbeat('fulfillment'),range(4)))
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(WorkerHeartbeat))==1
    import pytest
    with pytest.raises(ValueError):monitoring.heartbeat('external')

def test_worker_starting_missing_stale_recovery_and_optional_modes(monkeypatch):
    freeze(monkeypatch)
    with SessionLocal() as db:
        assert next(x for x in monitoring.worker_status(db) if x['service']=='fulfillment')['status']=='UNKNOWN'
        state=db.get(MonitorState,1);state.first_checked_at=AT;db.commit()
        statuses={x['service']:x['status'] for x in monitoring.worker_status(db)}
        assert statuses=={'fulfillment':'STARTING','mail':'NOT_REQUIRED','monitor':'STARTING'}
        assert monitoring.worker_status(db,AT+timedelta(seconds=60))[0]['status']=='STARTING'
        assert monitoring.worker_status(db,AT+timedelta(seconds=61))[0]['status']=='MISSING'
    monitoring.heartbeat('fulfillment')
    with SessionLocal() as db:
        assert monitoring.worker_status(db,AT+timedelta(seconds=60))[0]['status']=='RECENT'
        assert monitoring.worker_status(db,AT+timedelta(seconds=61))[0]['status']=='STALE'
    monkeypatch.setattr(get_settings(),'fulfillment_mode','manual')
    with SessionLocal() as db:assert monitoring.worker_status(db)[0]['status']=='NOT_REQUIRED'

def test_monitor_deduplicates_ack_resolve_and_reopen(client,tokens):
    identity=reconcile(sample())
    reconcile(sample(count=5),AT+timedelta(seconds=15))
    with SessionLocal() as db:
        assert alert(db).count==5 and alert(db).occurrences==1
        assert db.scalar(select(func.count()).select_from(AlertEvent))==1
    assert request_ack(client,tokens,identity).status_code==200
    assert request_ack(client,tokens,identity).status_code==200
    reconcile(sample(count=3))
    with SessionLocal() as db:
        assert alert(db).status=='ACKNOWLEDGED'
        assert db.scalar(select(func.count()).select_from(AlertEvent).where(AlertEvent.action=='ACKNOWLEDGED'))==1
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=='alerts.acknowledge'))==1
    reconcile({'alerts':[]},AT+timedelta(seconds=30))
    assert request_ack(client,tokens,identity).status_code==409
    reconcile(sample(),AT+timedelta(seconds=45))
    assert request_ack(client,tokens,identity).status_code==409
    assert request_ack(client,tokens,identity,occurrence=2).status_code==200
    with SessionLocal() as db:
        assert alert(db).status=='ACKNOWLEDGED' and alert(db).occurrences==2
        assert alert(db).resolved_at is None
        events=db.scalars(select(AlertEvent.action).order_by(AlertEvent.id)).all()
        assert events==['OPENED','ACKNOWLEDGED','RESOLVED','REOPENED','ACKNOWLEDGED']

def test_run_once_monitor_state_heartbeat_and_disabled_read_only(monkeypatch):
    freeze(monkeypatch)
    monkeypatch.setattr(monitoring,'summary',lambda *a:sample())
    assert monitoring.run_once()==1
    assert monitoring.run_once()==1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(OperationalAlert))==1
        assert monitoring.utc(db.get(MonitorState,1).last_checked_at)==AT
        assert db.get(WorkerHeartbeat,'monitor')
    monkeypatch.setattr(get_settings(),'monitor_enabled',False)
    assert monitoring.run_once()==0
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(AlertEvent))==1

def test_missing_worker_alert_startup_grace_and_recovery(monkeypatch):
    freeze(monkeypatch)
    monkeypatch.setattr(monitoring,'summary',lambda *a:{'alerts':[]})
    monitoring.run_once()
    monkeypatch.setattr(monitoring,'now',lambda:AT+timedelta(seconds=61))
    monitoring.run_once()
    with SessionLocal() as db:
        record=alert(db);assert record.code=='WORKER_STALE' and record.scope=='fulfillment'
    monitoring.heartbeat('fulfillment');monitoring.run_once()
    with SessionLocal() as db:assert alert(db).status=='RESOLVED'

def test_parallel_monitor_samples_only_one_open_event(monkeypatch):
    freeze(monkeypatch)
    monkeypatch.setattr(monitoring,'summary',lambda *a:sample())
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:monitoring.run_once(),range(4)))
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(OperationalAlert))==1
        assert db.scalar(select(func.count()).select_from(AlertEvent))==1

def test_concurrent_acknowledgement_is_single_event(client,tokens):
    identity=reconcile(sample())
    def acknowledge(_):
        with TestClient(app) as c:return request_ack(c,tokens,identity).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:assert list(pool.map(acknowledge,range(4)))==[200]*4
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AlertEvent).where(AlertEvent.action=='ACKNOWLEDGED'))==1
        assert db.scalar(select(func.count()).select_from(AuditLog))==1

def test_pagination_filters_event_scope_and_validation(client,tokens):
    identity=reconcile(sample())
    reconcile({'alerts':sample()['alerts']+[{'code':'MAIL_FAILED','purpose':'password_reset','severity':'warning','count':1}]})
    response=client.get(URL+'/alerts',params={'page_size':1},headers=tokens['admin'])
    assert response.status_code==200 and response.json()['total']==2 and len(response.json()['items'])==1
    assert request_ack(client,tokens,identity).status_code==200
    assert client.get(URL+'/alerts',params={'status':'ACKNOWLEDGED'},headers=tokens['admin']).json()['total']==1
    events=client.get(f'{URL}/alerts/{identity}/events',headers=tokens['admin']).json()
    assert events['total']==2 and all(e['alert_id']==identity for e in events['items'])
    assert client.get(f'{URL}/alerts/99999/events',headers=tokens['admin']).status_code==404
    assert request_ack(client,tokens,99999).status_code==404
    for body in [{'note':'   ','expected_occurrences':1},{'note':'ok','expected_occurrences':1},{'note':'valid','expected_occurrences':True},{'note':'valid'}]:
        assert client.post(f'{URL}/alerts/{identity}/acknowledge',headers=tokens['admin'],json=body).status_code==422
    for params in [{'status':'bad'},{'page':0},{'page_size':101}]:
        assert client.get(URL+'/alerts',params=params,headers=tokens['admin']).status_code==422

def test_no_sensitive_values_or_external_calls_and_monitor_never_self_alerts(client,tokens,monkeypatch):
    freeze(monkeypatch);monitoring.run_once()
    for path in ['/monitor','/alerts']:
        result=client.get(URL+path,headers=tokens['admin'])
        assert result.status_code==200 and result.headers['cache-control']=='no-store'
        for secret in ['smtp_host','redis_url','jwt_secret','token_hash','@example.com','database_url','hostname','process_id']:
            assert secret not in result.text
    with SessionLocal() as db:
        assert not db.scalar(select(OperationalAlert).where(OperationalAlert.scope=='monitor'))

def test_monitor_configuration_intervals():
    import pytest
    config=dict(_env_file=None,jwt_secret='a'*48,code_pepper='b'*48)
    for values in [{'worker_stale_seconds':30,'worker_heartbeat_seconds':20}, {'worker_stale_seconds':60,'monitor_interval_seconds':60},{'monitor_interval_seconds':0},{'monitor_stale_minutes':10081}]:
        with pytest.raises(ValueError):Settings(**config,**values)
    assert Settings(**config).worker_stale_seconds==60
