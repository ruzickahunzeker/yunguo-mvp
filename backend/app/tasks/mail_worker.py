"""Shared durable SMTP delivery for domain-separated, single-use credentials.
A crash can redeliver the same link; consuming it remains atomic and single-use.
Each purpose has its own transaction so one failed delivery cannot undo another.
"""
import argparse
import time
from datetime import timedelta
from sqlalchemy import select, update
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.models import PasswordResetToken, EmailVerificationToken, User, now
from app.services.mailer import send_reset_email, send_verification_email
from app.services.password_reset import raw_token
from app.services.email_verification import raw_token as verification_token, eligible

def deliver_one(model, make_token, sender, recipient_valid):
    with SessionLocal() as db:
        if engine.dialect.name == 'sqlite':
            db.connection().exec_driver_sql('BEGIN IMMEDIATE')
        db.execute(update(model).where(model.delivery_status == 'QUEUED',
            model.expires_at <= now()).values(delivery_status='CANCELED'))
        record = db.scalar(select(model).where(model.delivery_status == 'QUEUED',
            model.used_at.is_(None), model.expires_at > now(), model.attempts < 3,
            model.next_attempt_at <= now()).order_by(model.created_at)
            .with_for_update(skip_locked=True).limit(1))
        if not record:
            db.commit()
            return 0
        user = db.get(User, record.user_id)
        if not recipient_valid(user, record):
            record.delivery_status = 'CANCELED'
        else:
            record.attempts += 1
            try:
                sender(user.email, make_token(record))
                record.delivery_status = 'SENT'
                record.last_error = None
            except Exception:
                record.last_error = 'SMTP_DELIVERY_FAILED'
                record.delivery_status = 'FAILED' if record.attempts >= 3 else 'QUEUED'
                record.next_attempt_at = now() + timedelta(seconds=30 * 2 ** (record.attempts-1))
        db.commit()
        return 1

def run_once():
    settings = get_settings()
    count = 0
    if settings.password_reset_enabled:
        count += deliver_one(PasswordResetToken, raw_token, send_reset_email,
            lambda user, record: bool(user and user.active and user.token_version == record.auth_version))
    if settings.email_verification_enabled:
        count += deliver_one(EmailVerificationToken, verification_token, send_verification_email, eligible)
    return count

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    from app.services.monitoring import heartbeat
    last_beat = 0
    while True:
        processed = run_once()
        if time.monotonic()-last_beat >= get_settings().worker_heartbeat_seconds:
            heartbeat('mail')
            last_beat = time.monotonic()
        if args.once:
            return
        if not processed:
            time.sleep(2)

if __name__ == '__main__':
    main()
