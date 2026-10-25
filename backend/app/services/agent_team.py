"""Administrator-assigned direct agent teams; no recursive hierarchy or commissions."""
from datetime import datetime, time, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select, func, case, true
from app.models import User, Agent, AgentLevel, AgentRelation, Role, Order, WalletTransaction, RedeemCode
from app.services.commerce import audit
from app.services.accounts import locked_account


def assign_parent(db, actor, child_id, payload):
    # A shared hierarchy lock serializes graph edits (including disjoint edges).
    # Row locks on just endpoints do not protect concurrent A->B, B->C edits.
    # NO KEY UPDATE keeps role foreign-key checks compatible with this mutex.
    db.scalar(select(Role).where(Role.name == 'agent').with_for_update(key_share=True))
    actor = locked_account(db, actor)
    if actor.role != 'admin':
        raise HTTPException(403, '需要管理员权限')
    ids = sorted({child_id, *([payload.parent_id] if payload.parent_id else [])})
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids))
        .order_by(User.id).with_for_update(key_share=True).execution_options(populate_existing=True))}
    child = users.get(child_id)
    if not child or child.role != 'agent' or not db.get(Agent, child_id):
        raise HTTPException(404, '代理不存在')
    relation = db.scalar(select(AgentRelation).where(AgentRelation.child_id == child_id))
    before = relation.parent_id if relation else None
    if before != payload.expected_parent_id:
        raise HTTPException(409, '代理归属已变化，请刷新后重新确认')
    if payload.parent_id == before:
        return {'user_id': child_id, 'parent_id': before}
    if payload.parent_id:
        parent = users.get(payload.parent_id)
        if not child.active or not parent or parent.role != 'agent' or not parent.active or not db.get(Agent, parent.id):
            raise HTTPException(409, '只能关联有效代理账号')
        if parent.id == child_id:
            raise HTTPException(409, '不能将代理分配给自己')
        if db.scalar(select(AgentRelation.id).where(AgentRelation.child_id == parent.id)):
            raise HTTPException(409, '上级已属于其他代理，不支持多层关系')
        if db.scalar(select(AgentRelation.id).where(AgentRelation.parent_id == child_id)):
            raise HTTPException(409, '该代理已有名下代理，请先解除关系再设置上级')
        if relation:
            relation.parent_id = parent.id
        else:
            db.add(AgentRelation(parent_id=parent.id, child_id=child_id))
    elif relation:
        db.delete(relation)
    audit(db, actor, 'agents.assign-parent', child_id, f'from={before};to={payload.parent_id}')
    db.flush()
    return {'user_id': child_id, 'parent_id': payload.parent_id}


def team_report(db, parent_id, start, end, page, page_size, q=''):
    lower = datetime.combine(start, time.min, timezone.utc)
    upper = datetime.combine(end + timedelta(days=1), time.min, timezone.utc)
    # Every subquery is grouped before joining, so cards and transactions cannot
    # multiply order revenue. Only direct current membership is visible.
    orders = select(Order.user_id.label('uid'), func.count().label('order_count'),
        func.sum(Order.amount).label('gross_amount'),
        func.sum(case((Order.payment_status == 'REFUNDED', Order.amount), else_=0)).label('refund_amount'))\
        .where(Order.source == 'wallet', Order.created_at >= lower, Order.created_at < upper)\
        .group_by(Order.user_id).subquery()
    spending = select(WalletTransaction.user_id.label('uid'),
        (-func.sum(WalletTransaction.amount)).label('code_purchase_amount'))\
        .where(WalletTransaction.kind == 'code_purchase', WalletTransaction.created_at >= lower,
               WalletTransaction.created_at < upper).group_by(WalletTransaction.user_id).subquery()
    cards = select(RedeemCode.owner_id.label('uid'), func.count().label('code_count'))\
        .group_by(RedeemCode.owner_id).subquery()
    scope = select(User.id, User.name, User.active, AgentLevel.name.label('level_name'),
        func.coalesce(orders.c.order_count, 0).label('order_count'),
        func.coalesce(orders.c.gross_amount, 0).label('gross_amount'),
        func.coalesce(orders.c.refund_amount, 0).label('refund_amount'),
        (func.coalesce(orders.c.gross_amount, 0)-func.coalesce(orders.c.refund_amount, 0)).label('net_amount'),
        func.coalesce(spending.c.code_purchase_amount, 0).label('code_purchase_amount'),
        func.coalesce(cards.c.code_count, 0).label('code_count'))\
        .join(Agent, Agent.user_id == User.id).join(AgentLevel, AgentLevel.id == Agent.level_id)\
        .join(AgentRelation, AgentRelation.child_id == User.id)\
        .outerjoin(orders, orders.c.uid == User.id).outerjoin(spending, spending.c.uid == User.id)\
        .outerjoin(cards, cards.c.uid == User.id)\
        .where(AgentRelation.parent_id == parent_id, User.role == 'agent')
    if q:
        scope = scope.where(User.name.icontains(q, autoescape=True))
    metrics = ('order_count', 'gross_amount', 'refund_amount', 'net_amount', 'code_purchase_amount', 'code_count')
    # Aggregates and page rows are read in one statement/snapshot.
    base = scope.subquery()
    totals = select(func.count().label('total'),
        *[func.coalesce(func.sum(base.c[m]), 0).label(m) for m in metrics]).subquery()
    selected = select(base).order_by(base.c.id).offset((page-1)*page_size).limit(page_size).subquery()
    result = db.execute(select(*[totals.c[k].label('summary_'+k) for k in ('total', *metrics)], selected)
                        .select_from(totals.join(selected, true(), isouter=True)).order_by(selected.c.id)).mappings().all()
    first = result[0]
    return {'items': [{k: r[k] for k in selected.c.keys()} for r in result if r['id'] is not None],
            'total': first['summary_total'], 'summary': {m: first['summary_'+m] for m in metrics},
            'page': page, 'page_size': page_size, 'start': start, 'end': end, 'timezone': 'UTC'}
