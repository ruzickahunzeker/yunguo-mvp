"""Order-cohort reports: UTC creation date, current payment/fulfillment state.

All totals and breakdowns derive from one aggregate SELECT, so a concurrent refund
cannot produce different totals in different sections of the same response.
"""
from datetime import datetime, timezone, time, timedelta
from sqlalchemy import select, func, case
from app.models import Order

METRICS = ('orders', 'wallet_orders', 'code_orders', 'gross_amount',
    'refund_amount', 'net_amount', 'refunded_orders', 'completed_orders',
    'failed_orders', 'queued_orders', 'processing_orders', 'canceled_orders')

def empty_metrics():
    return dict.fromkeys(METRICS, 0)

def sales_report(db, start, end, source=None, product_id=None, page=1, page_size=20):
    wallet = Order.source == 'wallet'
    refunded = Order.payment_status == 'REFUNDED'
    stamp = func.timezone('UTC', Order.created_at) if db.bind.dialect.name == 'postgresql' else Order.created_at
    day = func.date(stamp)
    # Avoid joining mutable product names/prices: report immutable order amounts.
    statement = select(day.label('day'), Order.product_id,
        func.count().label('orders'),
        func.sum(case((wallet, 1), else_=0)).label('wallet_orders'),
        func.sum(case((Order.source == 'code', 1), else_=0)).label('code_orders'),
        func.sum(case((wallet, Order.amount), else_=0)).label('gross_amount'),
        func.sum(case((wallet & refunded, Order.amount), else_=0)).label('refund_amount'),
        func.sum(case((refunded, 1), else_=0)).label('refunded_orders'),
        *[func.sum(case((Order.fulfillment_status == state, 1), else_=0)).label(name)
          for state, name in [('COMPLETED','completed_orders'), ('FAILED','failed_orders'),
            ('QUEUED','queued_orders'), ('PROCESSING','processing_orders'), ('CANCELED','canceled_orders')]])
    # YYYY-MM-DD values are compared against timestamps at UTC day boundaries.
    statement = statement.where(
        Order.created_at >= datetime.combine(start, time.min, timezone.utc),
        Order.created_at < datetime.combine(end + timedelta(days=1), time.min, timezone.utc))
    if source:
        statement = statement.where(Order.source == source)
    if product_id is not None:
        statement = statement.where(Order.product_id == product_id)
    result = db.execute(statement.group_by(day, Order.product_id)).mappings().all()
    summary = empty_metrics()
    daily = {}
    cursor = start
    while cursor <= end:
        daily[cursor.isoformat()] = {'date': cursor.isoformat(), **empty_metrics()}
        cursor += timedelta(days=1)
    products = {}
    for item in result:
        values = {name: int(item[name]) for name in METRICS if name != 'net_amount'}
        values['net_amount'] = values['gross_amount'] - values['refund_amount']
        product = products.setdefault(item['product_id'], {'product_id': item['product_id'], **empty_metrics()})
        for target in (summary, daily[str(item['day'])], product):
            for name in METRICS:
                target[name] += values[name]
    products = sorted(products.values(), key=lambda value: (-value['net_amount'], value['product_id']))
    return {'start': start, 'end': end, 'timezone': 'UTC', 'source': source,
        'product_id': product_id, 'summary': summary, 'daily': list(daily.values()),
        'products': {'items': products[(page-1)*page_size:page*page_size],
            'total': len(products), 'page': page, 'page_size': page_size}}
