"""Reset an isolated SQLite database to a disposable demo baseline.

This command deliberately refuses production, PostgreSQL, and an omitted
confirmation flag. It is for local acceptance environments only.
"""
import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset a disposable demo database")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", "sqlite:///./demo-reset.db"))
    parser.add_argument("--confirm-demo-reset", action="store_true")
    args = parser.parse_args()
    if os.environ.get("APP_ENV", "development").lower() == "production":
        parser.error("refusing to reset a production environment")
    if not args.confirm_demo_reset:
        parser.error("pass --confirm-demo-reset; this deletes the selected database")
    if not args.database_url.startswith("sqlite:"):
        parser.error("demo reset only supports an isolated SQLite database")

    os.environ["DATABASE_URL"] = args.database_url
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("JWT_SECRET", "demo-reset-jwt-" + secrets.token_hex(32))
    os.environ.setdefault("CODE_PEPPER", "demo-reset-pepper-" + secrets.token_hex(32))
    os.environ.setdefault("REDIS_URL", "")
    from sqlalchemy import select
    from app.cli import seed_basics
    from app.core.db import Base, SessionLocal, engine
    from app.core.security import hash_password
    from app.models import Agent, Product, ProductPrice, User, Wallet

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_basics(db)
        for name, role in (("demo-admin", "admin"), ("demo-agent", "agent"), ("demo-user", "user")):
            user = User(email=f"{name}@example.test", name=name, role=role,
                        password_hash=hash_password(secrets.token_urlsafe(18)))
            db.add(user)
            db.flush()
            db.add(Wallet(user_id=user.id))
            if role == "agent":
                db.add(Agent(user_id=user.id))
        db.add(Product(name="演示套餐", description="仅用于本地验收，不代表真实订阅权益。",
                       price=1000, original_price=1500, stock=100, active=True))
        db.flush()
        db.add(ProductPrice(product_id=db.scalar(select(Product.id).order_by(Product.id.desc())),
                            role="agent", price=800))
        db.commit()
    print({"status": "reset", "database": args.database_url, "accounts": 3,
           "note": "demo passwords are random and intentionally not displayed"})


if __name__ == "__main__":
    main()
