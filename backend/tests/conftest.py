import os
import tempfile
from pathlib import Path
import pytest

TEST_DIR = tempfile.TemporaryDirectory(prefix='yunguo-tests-')
os.environ.update(APP_ENV='test', DATABASE_URL=os.environ.get('TEST_DATABASE_URL',f'sqlite:///{TEST_DIR.name}/test.db'),
    PASSWORD_RESET_ENABLED='false', EMAIL_VERIFICATION_ENABLED='false', REQUIRE_VERIFIED_EMAIL_FOR_PURCHASE='false', SMTP_HOST='', SMTP_USERNAME='', SMTP_PASSWORD='',
    JWT_SECRET='test-jwt-'+'a'*56, CODE_PEPPER='test-pepper-'+'b'*56, REDIS_URL='', DEMO_RECHARGE_ENABLED='true', FULFILLMENT_MODE='mock')
from sqlalchemy.engine import make_url
if os.environ.get('TEST_DATABASE_URL'):
    database_name = make_url(os.environ['TEST_DATABASE_URL']).database or ''
    if not database_name.endswith('_test'):
        raise RuntimeError('TEST_DATABASE_URL database must end in _test; tests delete all data')
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.core.db import Base, engine, SessionLocal
from app.main import app
from app.cli import seed_basics
from app.core.security import hash_password, token_for
from app.core import rate_limit
from app.models import User, Wallet, Product, ProductPrice, Agent

@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    rate_limit._buckets.clear()
    with SessionLocal() as db:
        seed_basics(db)
        for name,role in [('admin','admin'),('alice','user'),('bob','user'),('agent','agent')]:
            user=User(email=f'{name}@example.com',name=name,role=role,password_hash=hash_password('correct-password'))
            db.add(user);db.flush();db.add(Wallet(user_id=user.id))
            if role=='agent':db.add(Agent(user_id=user.id))
        p=Product(name='演示套餐',description='mock only',price=1000,original_price=1500,stock=100)
        db.add(p);db.flush();db.add(ProductPrice(product_id=p.id,role='agent',price=800));db.commit()
    yield

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture
def tokens():
    with SessionLocal() as db:
        return {u.name:{'Authorization':'Bearer '+token_for(u)} for u in db.scalars(select(User))}
