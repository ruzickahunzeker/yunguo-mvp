"""Read-only audit selection and spreadsheet-safe, bounded exports."""
from datetime import datetime, time, timedelta, timezone
from sqlalchemy import select, func
from app.models import AuditLog

EXPORT_LIMIT = 10000
COLUMNS = ('id', 'actor_id', 'action', 'target', 'detail', 'created_at')

def selection(db, start=None, end=None, actor_id=None, action=None, target=None, snapshot_id=None):
    ceiling = db.scalar(select(func.coalesce(func.max(AuditLog.id), 0)))
    ceiling = ceiling if snapshot_id is None else min(snapshot_id, ceiling)
    statement = select(AuditLog).where(AuditLog.id <= ceiling)
    if start is not None:
        statement = statement.where(
            AuditLog.created_at >= datetime.combine(start, time.min, timezone.utc),
            AuditLog.created_at < datetime.combine(end + timedelta(days=1), time.min, timezone.utc))
    if actor_id is not None:
        statement = statement.where(AuditLog.actor_id == actor_id)
    if action:
        statement = statement.where(AuditLog.action == action)
    if target:
        statement = statement.where(AuditLog.target.icontains(target, autoescape=True))
    return statement.order_by(AuditLog.id.desc()), ceiling

def csv_text(value):
    """Quote formula initiators even when hidden behind whitespace/BOM/control chars.

    CSV quoting alone does not prevent spreadsheet formula execution.
    """
    value = str(value)
    offset = 0
    while offset < len(value) and (value[offset].isspace() or ord(value[offset]) <= 32 or value[offset] == '\ufeff'):
        offset += 1
    probe = value[offset:]
    if probe.startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')):
        return "'" + value
    return value
