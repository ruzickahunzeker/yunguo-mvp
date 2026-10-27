import argparse
import getpass
import os
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import Role, User, Wallet, Product, ProductPrice, SystemSetting, AuditLog, AgentLevel, MonitorState

def seed_basics(db):
    if not db.get(MonitorState, 1):
        db.add(MonitorState(id=1))
    if not db.get(AgentLevel, 1):
        db.add(AgentLevel(id=1, name='一级代理'))
    for name, label in [('user','普通用户'),('agent','代理商'),('admin','管理员')]:
        if not db.get(Role, name):
            db.add(Role(name=name, label=label))
    for key in ['sales_enabled','redemption_enabled']:
        if not db.get(SystemSetting, key):
            db.add(SystemSetting(key=key,value='true'))
    db.flush()

def main():
    parser = argparse.ArgumentParser(description='初始化数据与管理员维护（在迁移之后执行）')
    parser.add_argument('command', choices=['seed','create-admin','reset-password','reconcile','cleanup-resets','cleanup-verifications'])
    parser.add_argument('--email')
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.command in ('seed','create-admin'):
            seed_basics(db)
        if args.command == 'seed':
            for name, description, price, agent, sku, months, verify in [
                ('ChatGPT 基础体验 · 演示','体验数字服务的完整购买与交付流程。仅模拟开通，无真实订阅权益。',4900,3900,None,None,False),
                ('ChatGPT Plus 月度 · 演示','月度订阅服务的演示套餐，用于验证订单、钱包及履约。',14900,12900,None,None,False),
                ('团队协作服务 · 演示','面向团队场景的数字服务演示。实际授权渠道待正式接入。',29900,25900,None,None,False),
                ('ChatGPT Go 月度 · 待配置','首批真实商品草稿；权益、价格和授权渠道待确认。保持下架。',0,0,'CHATGPT_GO_MONTHLY',1,True),
                ('ChatGPT Plus 月度 · 待配置','首批真实商品草稿；权益、价格和授权渠道待确认。保持下架。',0,0,'CHATGPT_PLUS_MONTHLY',1,True),
                ('ChatGPT Pro 月度 · 待配置','首批真实商品草稿；权益、价格和授权渠道待确认。保持下架。',0,0,'CHATGPT_PRO_MONTHLY',1,True)]:
                if not db.scalar(select(Product.id).where(Product.name == name)) and (not sku or not db.scalar(select(Product.id).where(Product.sku == sku))):
                    product = Product(name=name,description=description,sku=sku,subscription_months=months,
                                      original_price=price+3000 if price else 0,price=price,stock=1000,
                                      active=not bool(sku),verification_required=verify)
                    db.add(product)
                    db.flush()
                    db.add(ProductPrice(product_id=product.id,role='agent',price=agent))
            db.commit()
            print('角色、业务开关及演示商品初始化完成（可重复执行）')
        elif args.command in ('create-admin','reset-password'):
            from pydantic import TypeAdapter, EmailStr
            email = str(TypeAdapter(EmailStr).validate_python(args.email or os.environ.get('ADMIN_EMAIL') or input('Email: '))).lower()
            password = os.environ.get('ADMIN_PASSWORD') or getpass.getpass('Password (10+ chars): ')
            if not 10 <= len(password) <= 128:
                parser.error('Password must be 10–128 characters')
            user = db.scalar(select(User).where(User.email == email))
            if args.command == 'create-admin':
                if user:
                    parser.error('Account exists; refusing to silently promote or replace it')
                user = User(email=email,password_hash=hash_password(password),role='admin',name='平台管理员')
                db.add(user)
                db.flush()
                db.add(Wallet(user_id=user.id))
                db.add(AuditLog(actor_id=user.id,action='cli.create-admin',target=str(user.id)))
            else:
                if not user:
                    parser.error('Account does not exist')
                user.password_hash=hash_password(password)
                user.token_version += 1
                db.add(AuditLog(actor_id=user.id,action='cli.reset-password',target=str(user.id),detail='Operator must verify identity before CLI reset'))
            db.commit()
            print('账号操作完成，密码未输出')
        elif args.command in ('cleanup-resets', 'cleanup-verifications'):
            from datetime import timedelta
            from sqlalchemy import delete
            from app.models import PasswordResetToken, EmailVerificationToken, now
            model = PasswordResetToken if args.command == 'cleanup-resets' else EmailVerificationToken
            result = db.execute(delete(model).where(model.expires_at < now()-timedelta(days=7)))
            db.commit()
            print({'removed_expired_credential_records': result.rowcount})
        elif args.command == 'reconcile':
            from app.models import WalletTransaction
            from sqlalchemy import func
            mismatches=[]
            for wallet in db.scalars(select(Wallet)):
                available, frozen = db.execute(select(func.coalesce(func.sum(WalletTransaction.amount),0),func.coalesce(func.sum(WalletTransaction.frozen_delta),0)).where(WalletTransaction.user_id==wallet.user_id)).one()
                if (available,frozen)!=(wallet.balance,wallet.frozen):
                    mismatches.append(wallet.user_id)
            print({'mismatched_user_ids':mismatches})
            if mismatches:
                raise SystemExit(1)

if __name__ == '__main__':
    main()
