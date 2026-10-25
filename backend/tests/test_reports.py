import csv
from datetime import datetime, timezone, date
from io import StringIO
from sqlalchemy import select, text
from app.core.db import SessionLocal, engine
from app.models import Order, Product, AuditLog, now
from app.services.reports import sales_report, METRICS

URL='/api/admin/reports/sales'
PERIOD={'start':'2026-01-01','end':'2026-01-03'}

def fixtures():
    with SessionLocal() as db:
        p=Product(name='=SUM(1,2)',price=999999,original_price=999999,stock=0,active=False)
        db.add(p);db.flush();pid=p.id
        entries=[('2026-01-01T00:00:00+00:00',1,'wallet',1000,'PAID','COMPLETED'),
            ('2026-01-01T23:59:59+00:00',1,'wallet',300,'REFUNDED','FAILED'),
            ('2026-01-02T01:00:00+00:00',1,'code',0,'PAID','QUEUED'),
            ('2026-01-03T23:59:59+00:00',pid,'wallet',0,'PAID','CANCELED'),
            ('2026-01-04T00:00:00+00:00',1,'wallet',700,'PAID','PROCESSING'),
            ('2025-12-31T23:59:59+00:00',1,'wallet',900,'PAID','QUEUED')]
        for i,(stamp,product,source,amount,payment,state) in enumerate(entries):
            db.add(Order(id=f'report-{i}',product_id=product,product_name='历史快照',source=source,
                amount=amount,payment_status=payment,fulfillment_status=state,
                idempotency_key=f'report-key-{i}',lookup_hash='private-lookup-hash',created_at=datetime.fromisoformat(stamp)))
        db.commit()
    return pid

def report(client,tokens,**params):
    response=client.get(URL,params={**PERIOD,**params},headers=tokens['admin'])
    assert response.status_code==200,response.text
    return response.json()

def test_report_and_export_backend_permissions(client,tokens):
    for endpoint in (URL,URL+'/export'):
        assert client.get(endpoint).status_code==401
        for name in ('alice','agent'):
            assert client.get(endpoint,headers=tokens[name]).status_code==403

def test_cohort_totals_statuses_and_zero_price(client,tokens):
    fixtures();data=report(client,tokens);s=data['summary']
    assert s==dict(orders=4,wallet_orders=3,code_orders=1,gross_amount=1300,
        refund_amount=300,net_amount=1000,refunded_orders=1,completed_orders=1,
        failed_orders=1,queued_orders=1,processing_orders=0,canceled_orders=1)
    assert data['timezone']=='UTC' and len(data['daily'])==3
    for metric in METRICS:
        assert sum(d[metric] for d in data['daily'])==s[metric]
        assert sum(p[metric] for p in data['products']['items'])==s[metric]
    assert data['products']['items'][1]['gross_amount']==0

def test_source_product_and_utc_day_boundaries(client,tokens):
    pid=fixtures()
    wallet=report(client,tokens,source='wallet')
    assert wallet['summary']['orders']==3 and wallet['summary']['code_orders']==0
    code=report(client,tokens,source='code',product_id=1)
    assert code['summary']['orders']==1 and code['summary']['net_amount']==0
    assert report(client,tokens,start='2026-01-01',end='2026-01-01')['summary']['orders']==2
    assert report(client,tokens,product_id=pid)['summary']['orders']==1
    assert report(client,tokens,product_id=99999)['summary']['orders']==0

def test_zero_fill_and_default_dates(client,tokens):
    data=report(client,tokens)
    assert all(d['orders']==0 for d in data['daily'])
    assert [d['date'] for d in data['daily']]==['2026-01-01','2026-01-02','2026-01-03']
    default=client.get(URL,headers=tokens['admin']).json()
    assert default['end']==now().date().isoformat() and len(default['daily'])==30
    oldest=client.get(URL,params={'end':'0001-01-01'},headers=tokens['admin'])
    assert oldest.status_code==200 and len(oldest.json()['daily'])==1

def test_date_validation_and_bounded_ranges(client,tokens):
    for params in [{'start':'2026-01-03','end':'2026-01-01'},
        {'start':'2025-01-01','end':'2026-01-02'}, {'end':'9999-12-31'},
        {'start':'not-a-date'}, {'source':'anything'}, {'product_id':0},
        {'page':0}, {'page_size':101}]:
        for endpoint in (URL,URL+'/export') if 'page' not in str(params) else (URL,):
            assert client.get(endpoint,params=params,headers=tokens['admin']).status_code==422
    assert len(report(client,tokens,start='2024-01-01',end='2024-12-31')['daily'])==366

def test_product_pagination_sort_and_totals_stay_global(client,tokens):
    fixtures()
    first=report(client,tokens,page_size=1);second=report(client,tokens,page_size=1,page=2)
    assert first['products']['total']==2 and first['products']['items'][0]['product_id']==1
    assert second['products']['items'][0]['net_amount']==0
    assert first['summary']==second['summary'] and first['daily']==second['daily']
    assert report(client,tokens,page=99)['products']['items']==[]

def test_csv_matches_report_audits_and_has_no_credentials(client,tokens):
    fixtures();data=report(client,tokens,source='wallet',product_id=1)
    result=client.get(URL+'/export',params={**PERIOD,'source':'wallet','product_id':1},headers=tokens['admin'])
    assert result.status_code==200 and result.content.startswith(b'\xef\xbb\xbf')
    assert result.headers['cache-control']=='no-store' and result.headers['content-type'].startswith('text/csv')
    assert 'sales-2026-01-01-2026-01-03.csv' in result.headers['content-disposition']
    rows=list(csv.DictReader(StringIO(result.content.decode('utf-8-sig'))))
    assert len(rows)==4 and rows[-1]['date_utc']=='TOTAL'
    assert all(r['filter_source']=='wallet' and r['filter_product_id']=='1' for r in rows)
    for metric in METRICS:
        assert int(rows[-1][metric])==data['summary'][metric]
        assert sum(int(r[metric]) for r in rows[:-1])==data['summary'][metric]
    assert not any(s in result.text for s in ['private-lookup-hash','report-key','@example.com','=SUM','历史快照'])
    with SessionLocal() as db:
        log=db.scalar(select(AuditLog).where(AuditLog.action=='reports.sales-export'))
        assert log.actor_id and 'source=wallet;product_id=1;days=3' in log.detail

def test_export_cross_ip_user_rate_limit(client,tokens):
    for i in range(5):
        assert client.get(URL+'/export',params=PERIOD,headers={**tokens['admin'],'X-Forwarded-For':f'10.0.0.{i}'}).status_code==200
    assert client.get(URL+'/export',params=PERIOD,headers=tokens['admin']).status_code==429
    assert client.get(URL,params=PERIOD,headers=tokens['admin']).status_code==200
    with SessionLocal() as db:
        assert len(db.scalars(select(AuditLog).where(AuditLog.action=='reports.sales-export')).all())==5

def test_large_integer_amount_precision(client,tokens):
    with SessionLocal() as db:
        for i in range(3):
            db.add(Order(id=f'large-{i}',product_id=1,product_name='snapshot',source='wallet',amount=100000000,
                payment_status='REFUNDED' if i==0 else 'PAID',fulfillment_status='FAILED',
                idempotency_key=f'large-key-{i}',lookup_hash='',created_at=datetime(2026,1,1,tzinfo=timezone.utc)))
        db.commit()
    s=report(client,tokens)['summary']
    assert s['gross_amount']==300000000 and s['refund_amount']==100000000 and s['net_amount']==200000000
    assert all(isinstance(v,int) for v in s.values())

def test_postgresql_grouping_uses_utc_even_if_session_timezone_changes(client,tokens):
    fixtures()
    with SessionLocal() as db:
        if engine.dialect.name=='postgresql':db.execute(text("SET LOCAL TIME ZONE 'America/Los_Angeles'"))
        data=sales_report(db,date(2026,1,1),date(2026,1,3))
        assert [d['orders'] for d in data['daily']]==[2,1,1]
