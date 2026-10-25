import csv
from datetime import date, timedelta
from io import StringIO
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from app.api.deps import Admin, DB
from app.core.rate_limit import limit
from app.models import now
from app.services.commerce import audit
from app.services.reports import sales_report, METRICS
from app.services.code_reports import procurement_report

router = APIRouter(prefix='/admin/reports', tags=['统计报表'])

def filters(start: date | None = None, end: date | None = None,
    source: Literal['wallet', 'code'] | None = None,
    product_id: int | None = Query(None, ge=1)):
    end = end or now().date()
    start = start or end - timedelta(days=min(29, end.toordinal()-1))
    if start > end or (end-start).days >= 366 or end >= date.max:
        raise HTTPException(422, '请选择不超过366天且开始不晚于结束的UTC日期范围')
    return {'start': start, 'end': end, 'source': source, 'product_id': product_id}

Filters = Annotated[dict, Depends(filters)]

def code_filters(start: date | None = None, end: date | None = None,
    agent_id: int | None = Query(None, ge=1, le=2_147_483_647),
    product_id: int | None = Query(None, ge=1, le=2_147_483_647)):
    dates = filters(start, end, None, product_id)
    return {'start': dates['start'], 'end': dates['end'], 'agent_id': agent_id, 'product_id': product_id}

CodeFilters = Annotated[dict, Depends(code_filters)]

@router.get('/sales')
def sales(actor: Admin, db: DB, query: Filters,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    return sales_report(db, **query, page=page, page_size=page_size)

@router.get('/sales/export')
def export_sales(actor: Admin, db: DB, query: Filters, request: Request):
    limit(request, f'reports.export:{actor.id}', 5, 60, per_client=False)
    data = sales_report(db, **query)
    output = StringIO(newline='')
    writer = csv.writer(output)
    metadata = [query['source'] or 'all', query['product_id'] or 'all']
    writer.writerow(['date_utc', *METRICS, 'filter_source', 'filter_product_id'])
    for item in data['daily']:
        writer.writerow([item['date'], *[item[name] for name in METRICS], *metadata])
    writer.writerow(['TOTAL', *[data['summary'][name] for name in METRICS], *metadata])
    audit(db, actor, 'reports.sales-export', 'sales',
        f"start={query['start']};end={query['end']};source={query['source'] or 'all'};product_id={query['product_id']};days={len(data['daily'])}")
    db.commit()
    return Response('\ufeff'+output.getvalue(), media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="sales-{query["start"]}-{query["end"]}.csv"'})

@router.get('/code-purchases')
def code_purchases(actor: Admin, db: DB, query: CodeFilters):
    data = procurement_report(db, **query)
    data.pop('detail')
    return data

@router.get('/code-purchases/export')
def export_code_purchases(actor: Admin, db: DB, query: CodeFilters, request: Request):
    limit(request, f'reports.code-purchases-export:{actor.id}', 5, 60, per_client=False)
    data=procurement_report(db, **query)
    output=StringIO(newline=''); writer=csv.writer(output)
    writer.writerow(['date_utc','batch_id','agent_id','product_id','batches','quantity','amount','filter_agent_id','filter_product_id'])
    for item in data['detail']:
        writer.writerow([item[k] for k in ('date','batch_id','agent_id','product_id')]+[1,item['quantity'],item['amount'],query['agent_id'] or 'all',query['product_id'] or 'all'])
    writer.writerow(['TOTAL','','','',data['summary']['batches'],data['summary']['quantity'],data['summary']['amount'],query['agent_id'] or 'all',query['product_id'] or 'all'])
    audit(db,actor,'reports.code-purchases-export','code-purchases',f"start={query['start']};end={query['end']};agent_id={query['agent_id']};product_id={query['product_id']}")
    db.commit()
    return Response('\ufeff'+output.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="code-purchases-{query["start"]}-{query["end"]}.csv"'})
