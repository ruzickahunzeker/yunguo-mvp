"""Rehearse a Compose PostgreSQL backup in a disposable, network-isolated container.

No source writes, published ports, persistent restore volumes or retained dumps.
Reports contain counts only. Run from a host with Docker access.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SQL = """
SELECT json_build_object(
 'revision', (SELECT version_num FROM alembic_version),
 'business_tables', (SELECT count(*) FROM information_schema.tables
   WHERE table_schema='public' AND table_type='BASE TABLE' AND table_name<>'alembic_version'),
 'users', (SELECT count(*) FROM users),
 'orders', (SELECT count(*) FROM orders),
 'ledger_entries', (SELECT count(*) FROM wallet_transactions),
 'codes', (SELECT count(*) FROM redeem_codes),
 'wallet_mismatches', (SELECT count(*) FROM wallets w LEFT JOIN
   (SELECT user_id, sum(amount) a, sum(frozen_delta) f FROM wallet_transactions GROUP BY user_id) t
   ON t.user_id=w.user_id WHERE w.balance<>coalesce(t.a,0) OR w.frozen<>coalesce(t.f,0)),
 'missing_jobs', (SELECT count(*) FROM orders o LEFT JOIN fulfillment_jobs j ON j.order_id=o.id
   WHERE j.id IS NULL),
 'purchase_mismatches', (SELECT count(*) FROM orders o WHERE o.source='wallet' AND
   (SELECT count(*) FROM wallet_transactions t WHERE t.order_id=o.id AND t.kind='purchase'
      AND t.user_id=o.user_id AND t.amount=-o.amount AND t.frozen_delta=0)<>1),
 'refund_mismatches', (SELECT count(*) FROM orders o WHERE o.payment_status='REFUNDED' AND
   (o.source<>'wallet' OR (SELECT count(*) FROM wallet_transactions t WHERE t.order_id=o.id
     AND t.kind='refund' AND t.user_id=o.user_id AND t.amount=o.amount AND t.frozen_delta=0)<>1)),
 'code_mismatches', (SELECT count(*) FROM redeem_codes c LEFT JOIN orders o ON o.id=c.order_id
   WHERE (c.status='USED' AND (o.id IS NULL OR o.source<>'code' OR o.product_id<>c.product_id
      OR c.used_at IS NULL)) OR (c.status<>'USED' AND c.order_id IS NOT NULL)),
 'unvalidated_constraints', (SELECT count(*) FROM pg_constraint c JOIN pg_namespace n
   ON n.oid=c.connamespace WHERE n.nspname='public' AND NOT c.convalidated)
);
"""

SOURCE_SCHEMA_SQL = """
SELECT json_build_object(
 'revision', (SELECT version_num FROM alembic_version),
 'business_tables', (SELECT count(*) FROM information_schema.tables
   WHERE table_schema='public' AND table_type='BASE TABLE' AND table_name<>'alembic_version')
);
"""


def run(args, **kwargs):
    result = subprocess.run(args, cwd=ROOT, stderr=subprocess.PIPE, timeout=180, **kwargs)
    if result.returncode:
        # pg_restore diagnostics can contain row contents; do not copy them to reports.
        raise RuntimeError(f'{args[0]} operation failed (exit {result.returncode})')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default=os.environ.get('COMPOSE_PROJECT_NAME', 'yunguo-mvp'))
    parser.add_argument('--report', type=Path, default=ROOT.parent/'yunguo-restore-verification.json')
    args = parser.parse_args()
    report = {'state': 'running', 'started_at': datetime.now(timezone.utc).isoformat(),
              'source_project': args.project, 'scope': 'isolated PostgreSQL logical restore'}
    name = 'yunguo-restore-' + uuid4().hex[:12]
    created = False
    failure = None
    try:
        compose = ['docker', 'compose', '-p', args.project, 'exec', '-T', 'db']
        source_schema = json.loads(run(
            compose+['psql', '-U', 'yunguo', '-d', 'yunguo', '-Atc', SOURCE_SCHEMA_SQL],
            stdout=subprocess.PIPE).stdout)
        revision = source_schema['revision']
        with tempfile.TemporaryDirectory(prefix='yunguo-restore-') as directory:
            dump = Path(directory)/'backup.dump'
            with dump.open('xb') as output:
                os.chmod(dump, 0o600)
                run(compose+['pg_dump', '-U', 'yunguo', '-d', 'yunguo', '-Fc'], stdout=output)
            report['dump_bytes'] = dump.stat().st_size
            with dump.open('rb') as source:
                report['dump_sha256'] = hashlib.file_digest(source, 'sha256').hexdigest()
            # Supply a random password through stdin, never process arguments or a report.
            with tempfile.TemporaryFile() as env:
                env.write(f'POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n'.encode())
                env.seek(0)
                run(['docker', 'create', '--name', name, '--network', 'none',
                     '--tmpfs', '/var/lib/postgresql/data',
                     '--env-file', '/dev/stdin', '-e', 'POSTGRES_USER=yunguo',
                     '-e', 'POSTGRES_DB=yunguo_restore', 'postgres:16-alpine'],
                    stdin=env, stdout=subprocess.PIPE)
            created = True
            run(['docker', 'start', name], stdout=subprocess.PIPE)
            for _ in range(60):
                ready = subprocess.run(['docker', 'exec', name, 'pg_isready', '-U', 'yunguo',
                                        '-d', 'yunguo_restore'], capture_output=True, timeout=10)
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Restore database did not become ready')
            with dump.open('rb') as source:
                run(['docker', 'exec', '-i', name, 'pg_restore', '--exit-on-error', '--no-owner',
                     '-U', 'yunguo', '-d', 'yunguo_restore'], stdin=source, stdout=subprocess.PIPE)
            result = run(['docker', 'exec', name, 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'yunguo',
                          '-d', 'yunguo_restore', '-Atc', SQL], stdout=subprocess.PIPE)
            checks = json.loads(result.stdout)
            report['checks'] = checks
            report['source_schema'] = source_schema
            if (checks['revision'] != source_schema['revision'] or
                    checks['business_tables'] != source_schema['business_tables']):
                raise RuntimeError('Restored schema does not match the source revision/table count')
            if any(value for key, value in checks.items()
                   if key.endswith('_mismatches') or key in ('missing_jobs', 'unvalidated_constraints')):
                raise RuntimeError('Restored business consistency checks failed')
            report['state'] = 'passed'
    except Exception as error:
        failure = error
        report.update(state='failed', error=str(error))
    finally:
        if created:
            cleanup = subprocess.run(['docker', 'rm', '-fv', name], capture_output=True, timeout=60)
            report['temporary_container_removed'] = cleanup.returncode == 0
            if cleanup.returncode:
                report['state'] = 'failed'
                report['cleanup_container'] = name
                failure = RuntimeError('Temporary restore container cleanup failed')
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            output.write(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(f"Restore verification: {report['state']}; report: {args.report}")
    if failure:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
