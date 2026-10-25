import csv
from datetime import date, timezone
from io import StringIO
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from app.api.deps import Admin, DB
from app.core.rate_limit import limit
from app.repositories.queries import paginate, row
from app.services.audit_logs import selection, csv_text, COLUMNS, EXPORT_LIMIT
from app.services.commerce import audit

router = APIRouter(prefix='/admin/audit-logs', tags=['操作日志'])

def filters(start: date | None = None, end: date | None = None,
    actor_id: int | None = Query(None, ge=1, le=2147483647),
    action: str | None = Query(None, min_length=1, max_length=60),
    target: str | None = Query(None, min_length=1, max_length=100),
    snapshot_id: int | None = Query(None, ge=0)):
    if (start is None) != (end is None):
        raise HTTPException(422, '请同时提供开始和结束UTC日期')
    if start is not None and (start > end or (end-start).days >= 366 or end == date.max):
        raise HTTPException(422, '请选择不超过366天且开始不晚于结束的UTC日期范围')
    return dict(start=start, end=end, actor_id=actor_id, action=action, target=target, snapshot_id=snapshot_id)

Filters = Annotated[dict, Depends(filters)]

@router.get('')
def logs(actor: Admin, db: DB, query: Filters,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    statement, ceiling = selection(db, **query)
    result = paginate(db, statement, page, page_size)
    for item in result['items']:
        item['created_at'] = item['created_at'].astimezone(timezone.utc)
    return {**result, 'snapshot_id': ceiling}

@router.get('/export')
def export_logs(actor: Admin, db: DB, query: Filters, request: Request):
    limit(request, f'audit.export:{actor.id}', 5, 60, per_client=False)
    statement, ceiling = selection(db, **query)
    records = db.scalars(statement.limit(EXPORT_LIMIT+1)).all()
    if len(records) > EXPORT_LIMIT:
        raise HTTPException(413, '匹配日志超过10000条，请缩小日期或筛选范围后导出')
    output = StringIO(newline='')
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow([*COLUMNS, 'snapshot_id'])
    for record in records:
        data = row(record)
        data['created_at'] = data['created_at'].astimezone(timezone.utc).isoformat()
        writer.writerow([*[csv_text(data[name]) for name in COLUMNS], ceiling])
    # Do not copy free-form filter text into a new log; use only bounded metadata.
    audit(db, actor, 'audit.export', 'audit-logs',
        f"snapshot_id={ceiling};rows={len(records)};start={query['start']};end={query['end']};actor_id={query['actor_id']};action_filtered={bool(query['action'])};target_filtered={bool(query['target'])}")
    db.commit()
    return Response('\ufeff'+output.getvalue(), media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="audit-logs-{ceiling}.csv"',
            'X-Audit-Snapshot': str(ceiling), 'X-Export-Rows': str(len(records))})
