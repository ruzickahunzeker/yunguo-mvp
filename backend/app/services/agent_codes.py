"""Agent-funded card issuance. Raw codes are returned once, never persisted."""
import json
from fastapi import HTTPException
from sqlalchemy import select
from app.models import Product, WalletTransaction
from app.core.config import get_settings
from app.core.security import digest
from app.schemas.requests import CodeBatch
from app.services.accounts import locked_account
from app.services.commerce import audit, enabled, issue_codes, move_wallet
from app.services.pricing import agent_context, quote_for, assert_confirmed


def purchase_codes(db, user, payload, key):
    # Serialize same-account purchases before checking their idempotency record.
    user = locked_account(db, user)
    if user.role != 'agent':
        raise HTTPException(403, '仅代理账号可扣款采购卡密')
    reference = f'agent-codes:{user.id}:{digest(key)}'
    previous = db.scalar(select(WalletTransaction).where(WalletTransaction.reference == reference))
    contract = {'product_id': payload.product_id, 'quantity': payload.quantity,
                'valid_days': payload.valid_days, 'unit_price': payload.expected_unit_price}
    if previous:
        saved = json.loads(previous.note)
        if saved['contract'] != contract:
            raise HTTPException(409, '幂等键已用于不同发卡请求')
        return {'batch_id': saved['batch_id'], 'codes': [], 'quantity': payload.quantity,
                'charged_amount': -previous.amount, 'replayed': True,
                'notice': '此批次已扣款生成，不会重复扣款。完整卡密仅首次返回，请核对已保存文件和卡密库存。'}
    enabled(db, 'sales_enabled')
    if get_settings().require_verified_email_for_purchase and user.email_verified_at is None:
        raise HTTPException(403, '请先验证注册邮箱，再采购卡密')
    context = agent_context(db, user, lock=True)
    product = db.scalar(select(Product).where(Product.id == payload.product_id)
                        .with_for_update(key_share=True).execution_options(populate_existing=True))
    if not product or not product.active:
        raise HTTPException(409, '商品不存在或已下架')
    quote = quote_for(db, product, user, context)
    assert_confirmed(quote, payload.expected_unit_price)
    total = quote.effective_price * payload.quantity
    # All mutations share the caller's transaction; insufficient funds roll back issuance.
    result = issue_codes(db, user, CodeBatch(product_id=product.id, quantity=payload.quantity,
                                           valid_days=payload.valid_days, owner_id=user.id))
    metadata = json.dumps({'batch_id': result['batch_id'], 'contract': contract}, separators=(',', ':'))
    move_wallet(db, user.id, -total, reference, 'code_purchase', note=metadata)
    audit(db, user, 'agent.codes-purchased', result['batch_id'],
          f'quantity={payload.quantity};unit_price={quote.effective_price};total={total}')
    return {**result, 'quantity': payload.quantity, 'charged_amount': total, 'replayed': False}
