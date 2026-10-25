"""Destructive migration test for a dedicated scratch DB only.
Usage: backend cwd, MIGRATION_TEST_DATABASE_URL=<..._test> ../.venv/bin/python ../scripts/check_agent_migration.py
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[1]
def run(url):
    parsed=make_url(url)
    if parsed.get_backend_name()!='sqlite' and not (parsed.database or '').endswith('_test'):
        raise RuntimeError('Dedicated database name must end in _test')
    env={**os.environ,'DATABASE_URL':url}
    if parsed.get_backend_name()=='sqlite' and (not str(parsed.database).endswith('_test.db') or Path(parsed.database).exists()):
        raise RuntimeError('SQLite migration test requires a new scratch file ending in _test.db')
    engine=create_engine(url)
    # Only scratch schema/tables are touched; never use an existing business DB.
    if parsed.get_backend_name()=='postgresql':
        with engine.begin() as c:c.execute(text('DROP SCHEMA public CASCADE'));c.execute(text('CREATE SCHEMA public'))
    def alembic(*args):
        subprocess.run([str(ROOT/'.venv/bin/alembic'),*args],cwd=ROOT/'backend',env=env,check=True)
    alembic('upgrade','6cdb7ffa6ccd')
    with engine.begin() as c:
        c.execute(text("INSERT INTO roles(name,label) VALUES ('agent','代理')"))
        for i,label in [(1,'一级代理'),(2,'历史自定义代理')]:
            c.execute(text('INSERT INTO users(id,email,password_hash,name,role,active,token_version,created_at,updated_at) VALUES (:id,:email,:password,:name,:role,:active,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)'),dict(id=i,email=f'migration-{i}@example.com',password='unused-test-hash',name='migration',role='agent',active=True))
            c.execute(text('INSERT INTO agents(user_id,level,created_at,updated_at) VALUES (:id,:label,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)'),dict(id=i,label=label))
            c.execute(text('INSERT INTO wallets(user_id,balance,frozen,created_at,updated_at) VALUES (:id,0,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)'),dict(id=i))
        c.execute(text('UPDATE wallets SET balance=500 WHERE user_id=1'))
        c.execute(text("INSERT INTO wallet_transactions(user_id,amount,frozen_delta,balance_after,frozen_after,kind,reference,note,order_id,created_at) VALUES (1,500,0,500,0,'adjust','migration-credit','migration fixture',NULL,CURRENT_TIMESTAMP)"))
        # Existing child FK rows make SQLite batch migration meaningful.
        c.execute(text('INSERT INTO agent_relations(parent_id,child_id) VALUES (1,2)'))
    alembic('upgrade','head');alembic('check')
    with engine.connect() as c:
        assert c.execute(text('SELECT a.user_id,l.name FROM agents a JOIN agent_levels l ON l.id=a.level_id ORDER BY a.user_id')).all()==[(1,'一级代理'),(2,'历史自定义代理')]
        assert c.execute(text('SELECT parent_id,child_id FROM agent_relations')).one()==(1,2)
        assert c.execute(text('SELECT SUM(balance) FROM wallets')).scalar()==500
        assert c.execute(text('SELECT SUM(amount) FROM wallet_transactions')).scalar()==500
        assert c.execute(text('SELECT email_verified_at FROM users')).scalars().all()==[None,None]
        assert c.execute(text('SELECT id,first_checked_at,last_checked_at FROM monitor_state')).one()==(1,None,None)
        assert c.execute(text('SELECT COUNT(*) FROM operational_alerts')).scalar()==0
        assert c.execute(text('SELECT COUNT(*) FROM alert_events')).scalar()==0
        assert c.execute(text('SELECT COUNT(*) FROM worker_heartbeats')).scalar()==0
        if parsed.get_backend_name()=='sqlite':assert not c.execute(text('PRAGMA foreign_key_check')).all()
    # Verify the identity sequence does not collide after explicit backfill IDs.
    with engine.begin() as c:
        c.execute(text('INSERT INTO agent_levels(name,active,sort,created_at,updated_at) VALUES (:name,:active,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)'),dict(name='迁移后新等级',active=True))
    alembic('downgrade','6cdb7ffa6ccd')
    with engine.connect() as c:
        assert c.execute(text('SELECT user_id,level FROM agents ORDER BY user_id')).all()==[(1,'一级代理'),(2,'历史自定义代理')]
        assert c.execute(text('SELECT parent_id,child_id FROM agent_relations')).one()==(1,2)
        assert c.execute(text('SELECT SUM(balance) FROM wallets')).scalar()==500
        assert c.execute(text('SELECT SUM(amount) FROM wallet_transactions')).scalar()==500
    alembic('upgrade','head');alembic('check')
    engine.dispose()
    print(f'PASS: {parsed.get_backend_name()} agent tier upgrade/down/up preserves legacy labels, wallets and child foreign keys')

if __name__=='__main__':
    target=os.environ.get('MIGRATION_TEST_DATABASE_URL')
    if target:run(target)
    else:
        with tempfile.TemporaryDirectory(prefix='yunguo-migration-') as tmp:run(f'sqlite:///{tmp}/migration_test.db')
