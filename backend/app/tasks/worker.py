"""Durable queue worker; mock fulfillment is atomic, so a crash rolls back the claim.
Manual mode leaves queued jobs for administrator actions. No external API calls.
"""
import argparse
import time
from sqlalchemy import select
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.models import FulfillmentJob, Order, OrderEvent, now
from app.services.fulfillment import adapter_for

def run_once():
    if get_settings().fulfillment_mode != 'mock':
        return 0
    with SessionLocal() as db:
        if engine.dialect.name == 'sqlite':
            db.connection().exec_driver_sql('BEGIN IMMEDIATE')
        job = db.scalar(select(FulfillmentJob).where(FulfillmentJob.state == 'QUEUED', FulfillmentJob.attempts < 3)
            .order_by(FulfillmentJob.id).with_for_update(skip_locked=True).limit(1))
        if not job:
            return 0
        order = db.scalar(select(Order).where(Order.id == job.order_id).with_for_update())
        if order.payment_status != 'PAID' or order.fulfillment_status != 'QUEUED':
            job.state = 'CANCELED'
        else:
            result = adapter_for('mock').fulfill(order.id)
            job.attempts += 1
            job.state = result.status
            order.fulfillment_status = result.status
            order.completed_at = now()
            db.add(OrderEvent(order_id=order.id, action='mock.completed', note=result.note))
        db.commit()
        return 1

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    from app.services.monitoring import heartbeat
    last_beat = 0
    while True:
        processed = run_once()
        if time.monotonic()-last_beat >= get_settings().worker_heartbeat_seconds:
            heartbeat('fulfillment')
            last_beat = time.monotonic()
        if args.once:
            return
        if not processed:
            time.sleep(2)

if __name__ == '__main__':
    main()
