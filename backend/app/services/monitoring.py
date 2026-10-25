"""Durable site alerts. No external notifications, network probes or auto-repair."""
from datetime import timedelta, timezone
from sqlalchemy import select
from fastapi import HTTPException
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.models import WorkerHeartbeat, MonitorState, OperationalAlert, AlertEvent, now
from app.services.operations import summary
from app.services.commerce import audit

def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

def heartbeat(service):
    if service not in ('fulfillment', 'mail', 'monitor'):
        raise ValueError('Unknown service')
    with SessionLocal() as db:
        # Native upsert allows more than one replica to report the same service.
        if engine.dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        at = now()
        db.execute(insert(WorkerHeartbeat).values(service=service, last_seen_at=at)
            .on_conflict_do_update(index_elements=['service'], set_={'last_seen_at': at},
                where=WorkerHeartbeat.last_seen_at <= at))
        db.commit()

def worker_status(db, at=None):
    at = at or now()
    settings = get_settings()
    records = {item.service: utc(item.last_seen_at) for item in db.scalars(select(WorkerHeartbeat))}
    checked = db.get(MonitorState, 1)
    first = utc(checked.first_checked_at) if checked else None
    result = []
    for service in ('fulfillment', 'mail', 'monitor'):
        expected = (settings.fulfillment_mode == 'mock' if service == 'fulfillment' else
            settings.password_reset_enabled or settings.email_verification_enabled if service == 'mail' else settings.monitor_enabled)
        seen = records.get(service)
        if not expected:
            status = 'NOT_REQUIRED'
        elif seen:
            status = 'RECENT' if (at-seen).total_seconds() <= settings.worker_stale_seconds else 'STALE'
        else:
            status = 'UNKNOWN' if first is None else 'MISSING' if (at-first).total_seconds() > settings.worker_stale_seconds else 'STARTING'
        result.append({'service': service, 'status': status, 'last_seen_at': seen,
            'timeout_seconds': settings.worker_stale_seconds})
    return result

def inspect(db):
    settings = get_settings()
    state = db.get(MonitorState, 1)
    return {'enabled': settings.monitor_enabled, 'interval_seconds': settings.monitor_interval_seconds,
        'stale_minutes': settings.monitor_stale_minutes, 'first_checked_at': utc(state.first_checked_at) if state else None,
        'last_checked_at': utc(state.last_checked_at) if state else None,
        'workers': worker_status(db)}

def reconcile(db, sample, workers, at):
    active = {(a['code'], a.get('purpose', 'platform')): a for a in sample['alerts']}
    for worker in workers:
        if worker['service'] != 'monitor' and worker['status'] in ('STALE', 'MISSING'):
            active[('WORKER_STALE', worker['service'])] = {'severity': 'warning', 'count': 1}
    existing = {(a.code, a.scope): a for a in db.scalars(select(OperationalAlert).order_by(OperationalAlert.id).with_for_update())}
    for key, value in active.items():
        alert = existing.get(key)
        if alert is None:
            alert = OperationalAlert(code=key[0], scope=key[1], severity=value['severity'], count=value['count'],
                status='OPEN', occurrences=1, first_seen_at=at, last_seen_at=at)
            db.add(alert); db.flush()
            db.add(AlertEvent(alert_id=alert.id, action='OPENED', created_at=at))
        else:
            if alert.status == 'RESOLVED':
                alert.status = 'OPEN'; alert.occurrences += 1; alert.resolved_at = None
                db.add(AlertEvent(alert_id=alert.id, action='REOPENED', created_at=at))
            alert.last_seen_at = at; alert.count = value['count']; alert.severity = value['severity']
    for key, alert in existing.items():
        if key not in active and alert.status != 'RESOLVED':
            alert.status = 'RESOLVED'; alert.count = 0; alert.resolved_at = at
            db.add(AlertEvent(alert_id=alert.id, action='RESOLVED', created_at=at))

def run_once():
    settings = get_settings()
    if not settings.monitor_enabled:
        return 0
    with SessionLocal() as db:
        if engine.dialect.name == 'sqlite':
            db.connection().exec_driver_sql('BEGIN IMMEDIATE')
        # Seeded by migration/CLI. One row serializes multiple monitor replicas.
        state = db.scalar(select(MonitorState).where(MonitorState.id == 1).with_for_update())
        if state is None:
            raise RuntimeError('Run migrations and seed before monitor')
        at = now()
        if state.first_checked_at is None:
            state.first_checked_at = at
        state.last_checked_at = at
        db.flush()
        sample = summary(db, settings.monitor_stale_minutes)
        reconcile(db, sample, worker_status(db, at), at)
        db.commit()
    heartbeat('monitor')
    return 1

def acknowledge(db, actor, identity, note, expected_occurrences):
    alert = db.scalar(select(OperationalAlert).where(OperationalAlert.id == identity).with_for_update())
    if not alert:
        raise HTTPException(404, '告警不存在')
    if alert.occurrences != expected_occurrences:
        raise HTTPException(409, '告警已再次发生，请刷新后重新确认')
    if alert.status == 'RESOLVED':
        raise HTTPException(409, '告警已恢复，请刷新列表')
    if alert.status == 'OPEN':
        alert.status = 'ACKNOWLEDGED'
        db.add(AlertEvent(alert_id=alert.id, action='ACKNOWLEDGED', actor_id=actor.id, note=note))
        audit(db, actor, 'alerts.acknowledge', alert.id, note)
    return alert
