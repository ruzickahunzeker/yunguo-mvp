"""Read-only queue diagnostics. Counts do not imply worker liveness."""
from datetime import timedelta, timezone
from sqlalchemy import select, func, case
from app.core.config import get_settings
from app.models import Order, FulfillmentJob, PasswordResetToken, EmailVerificationToken, now
from app.repositories.queries import row

def conditions(cutoff):
    paid = Order.payment_status == 'PAID'
    queued = paid & (Order.fulfillment_status == 'QUEUED') & (FulfillmentJob.state == 'QUEUED')
    return {
        'queued': queued,
        'stale': queued & (FulfillmentJob.updated_at <= cutoff),
        'attention': paid & Order.fulfillment_status.in_(['FAILED', 'CANCELED']),
        'exhausted': paid & (Order.fulfillment_status == 'FAILED') & (FulfillmentJob.attempts >= 3),
        'refundable': paid & (Order.source == 'wallet') & Order.fulfillment_status.in_(['FAILED', 'CANCELED']),
    }

def email_summary(db, model, at, enabled):
    queued = (model.delivery_status == 'QUEUED') & model.used_at.is_(None)
    live = queued & (model.expires_at > at)
    expressions = {
        'queued': queued,
        'due': live & (model.next_attempt_at <= at) & (model.attempts < 3),
        'waiting': live & (model.next_attempt_at > at) & (model.attempts < 3),
        'expired_queued': queued & (model.expires_at <= at),
        'failed': (model.delivery_status == 'FAILED') & model.used_at.is_(None) & (model.expires_at > at),
    }
    counts = db.execute(select(*[func.coalesce(func.sum(case((test, 1), else_=0)), 0).label(name)
        for name, test in expressions.items()])).mappings().one()
    return {'enabled': enabled, **{key: int(value) for key, value in counts.items()}}

def summary(db, stale_minutes):
    at = now()
    rules = conditions(at-timedelta(minutes=stale_minutes))
    values = db.execute(select(*[func.coalesce(func.sum(case((test, 1), else_=0)), 0).label(name)
        for name, test in rules.items()], func.min(case((rules['queued'], FulfillmentJob.updated_at), else_=None)).label('oldest_queued_at'))
        .select_from(Order).join(FulfillmentJob, Order.id == FulfillmentJob.order_id)).mappings().one()
    values = dict(values)
    oldest = values.pop('oldest_queued_at')
    if oldest and oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    settings = get_settings()
    mail = {
        'password_reset': email_summary(db, PasswordResetToken, at, settings.password_reset_enabled),
        'email_verification': email_summary(db, EmailVerificationToken, at, settings.email_verification_enabled),
    }
    alerts = []
    if values['stale']:
        alerts.append({'code': 'FULFILLMENT_STALE', 'severity': 'info' if settings.fulfillment_mode == 'manual' else 'warning',
            'count': int(values['stale'])})
    if values['attention']:
        alerts.append({'code': 'ORDER_ATTENTION', 'severity': 'warning', 'count': int(values['attention'])})
    if values['exhausted']:
        alerts.append({'code': 'RETRY_EXHAUSTED', 'severity': 'warning', 'count': int(values['exhausted'])})
    for purpose, stats in mail.items():
        if stats['enabled'] and stats['failed']:
            alerts.append({'code': 'MAIL_FAILED', 'purpose': purpose, 'severity': 'warning', 'count': stats['failed']})
        if not stats['enabled'] and stats['due']:
            alerts.append({'code': 'MAIL_PAUSED', 'purpose': purpose, 'severity': 'info', 'count': stats['due']})
    return {'observed_at': at, 'stale_minutes': stale_minutes,
        'fulfillment_mode': settings.fulfillment_mode,
        'fulfillment': {**{name: int(value) for name, value in values.items()}, 'oldest_queued_at': oldest},
        'mail': mail, 'alerts': alerts}

def orders(db, kind, stale_minutes, page, page_size):
    rule = conditions(now()-timedelta(minutes=stale_minutes))[kind]
    base = select(Order, FulfillmentJob).join(FulfillmentJob, Order.id == FulfillmentJob.order_id).where(rule)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    records = db.execute(base.order_by(FulfillmentJob.updated_at, FulfillmentJob.id)
        .offset((page-1)*page_size).limit(page_size)).all()
    items = []
    for order, job in records:
        # Explicit fields only. Never return request/lookup hashes or task errors.
        items.append({'order_id': order.id, 'product_name': order.product_name, 'source': order.source,
            'amount': order.amount, 'payment_status': order.payment_status,
            'fulfillment_status': order.fulfillment_status, 'job_state': job.state,
            'attempts': job.attempts, 'updated_at': row(job)['updated_at']})
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}
