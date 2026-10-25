"""Agent card procurement debits, separate from order revenue. Bounded snapshot read."""
import json
import re
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from app.models import WalletTransaction
from app.schemas.requests import AgentCodePurchase

MAX_BATCHES = 10_000
METRICS = ('batches', 'quantity', 'amount')


def procurement_report(db, start, end, agent_id=None, product_id=None):
    lower = datetime.combine(start, time.min, timezone.utc)
    upper = datetime.combine(end + timedelta(days=1), time.min, timezone.utc)
    statement = select(WalletTransaction).where(WalletTransaction.kind == 'code_purchase',
        WalletTransaction.created_at >= lower, WalletTransaction.created_at < upper)
    if agent_id is not None:
        statement = statement.where(WalletTransaction.user_id == agent_id)
    # One SELECT fixes the set of debits for every total and breakdown.
    rows = db.scalars(statement.order_by(WalletTransaction.created_at, WalletTransaction.id)
                      .limit(MAX_BATCHES + 1)).all()
    if len(rows) > MAX_BATCHES:
        raise HTTPException(413, '采购批次超过10000条，请缩小日期范围或按代理筛选')
    def bucket():
        return dict.fromkeys(METRICS, 0)
    daily = defaultdict(bucket)
    agents = defaultdict(bucket)
    products = defaultdict(bucket)
    detail = []
    for tx in rows:
        try:
            metadata = json.loads(tx.note)
            contract = metadata['contract']
            parsed = AgentCodePurchase(product_id=contract['product_id'], quantity=contract['quantity'],
                valid_days=contract['valid_days'], expected_unit_price=contract['unit_price'])
            batch = metadata['batch_id']
            if not isinstance(batch, str) or not re.fullmatch(r'[a-f0-9]{24}', batch):
                raise ValueError('invalid batch')
            if tx.amount != -parsed.quantity * parsed.expected_unit_price or tx.frozen_delta != 0:
                raise ValueError('inconsistent charge')
        except (KeyError, TypeError, ValueError, ValidationError):
            raise HTTPException(409, f'采购流水 #{tx.id} 的批次信息或金额不一致，请先核对账务') from None
        if product_id is not None and parsed.product_id != product_id:
            continue
        stamp = tx.created_at
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        day = stamp.astimezone(timezone.utc).date().isoformat()
        amount = -tx.amount
        for item in (daily[day], agents[tx.user_id], products[parsed.product_id]):
            item['batches'] += 1
            item['quantity'] += parsed.quantity
            item['amount'] += amount
        detail.append({'date': day, 'batch_id': batch, 'agent_id': tx.user_id,
                       'product_id': parsed.product_id, 'quantity': parsed.quantity, 'amount': amount})
    daily_rows = []
    cursor = start
    while cursor <= end:
        daily_rows.append({'date': cursor.isoformat(), **daily[cursor.isoformat()]})
        cursor += timedelta(days=1)
    summary = {metric: sum(item[metric] for item in daily.values()) for metric in METRICS}
    return {'start': start, 'end': end, 'timezone': 'UTC', 'agent_id': agent_id, 'product_id': product_id,
        'summary': summary, 'daily': daily_rows,
        'agents': sorted([{'agent_id': uid, **value} for uid, value in agents.items()], key=lambda x: (-x['amount'], x['agent_id'])),
        'products': sorted([{'product_id': pid, **value} for pid, value in products.items()], key=lambda x: (-x['amount'], x['product_id'])),
        'detail': detail}
