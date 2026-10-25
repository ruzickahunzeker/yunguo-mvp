from typing import Literal
from fastapi import APIRouter, Query, Request
from app.api.deps import Admin, DB
from app.services import operations
from app.services import monitoring
from app.models import OperationalAlert, AlertEvent
from app.repositories.queries import paginate, required, row
from app.schemas.requests import AlertAcknowledge
from app.core.rate_limit import limit
from sqlalchemy import select

router = APIRouter(prefix='/admin/operations', tags=['运行状态'])

@router.get('/summary')
def summary(actor: Admin, db: DB, stale_minutes: int = Query(30, ge=1, le=10080)):
    return operations.summary(db, stale_minutes)

@router.get('/orders')
def orders(actor: Admin, db: DB,
    kind: Literal['queued', 'stale', 'attention', 'exhausted', 'refundable'] = 'attention',
    stale_minutes: int = Query(30, ge=1, le=10080),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    return operations.orders(db, kind, stale_minutes, page, page_size)

@router.get('/monitor')
def monitor_status(actor: Admin, db: DB):
    return monitoring.inspect(db)

@router.get('/alerts')
def alerts(actor: Admin, db: DB,
    status: Literal['active', 'OPEN', 'ACKNOWLEDGED', 'RESOLVED'] = 'active',
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    statement = select(OperationalAlert)
    statement = statement.where(OperationalAlert.status != 'RESOLVED') if status == 'active' else statement.where(OperationalAlert.status == status)
    return paginate(db, statement.order_by(OperationalAlert.last_seen_at.desc(), OperationalAlert.id.desc()), page, page_size)

@router.get('/alerts/{alert_id}/events')
def alert_events(alert_id: int, actor: Admin, db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    required(db, OperationalAlert, alert_id)
    return paginate(db, select(AlertEvent).where(AlertEvent.alert_id == alert_id).order_by(AlertEvent.id.desc()), page, page_size)

@router.post('/alerts/{alert_id}/acknowledge')
def acknowledge(alert_id: int, payload: AlertAcknowledge, actor: Admin, db: DB, request: Request):
    limit(request, f'alerts.acknowledge:{actor.id}', 20, 60, per_client=False)
    alert = monitoring.acknowledge(db, actor, alert_id, payload.note, payload.expected_occurrences)
    db.commit()
    return row(alert)
