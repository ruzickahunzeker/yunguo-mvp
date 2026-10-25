"""Single-level distribution with configurable tiers; no commission hierarchy.
Mutations lock User -> Agent -> Level, then inspect product. Purchases use the
same ordering, and a product row lock stabilizes fallback/retail price and stock.
PostgreSQL NO KEY UPDATE permits concurrent foreign-key references/audit writes.
"""
from dataclasses import dataclass
from fastapi import HTTPException
from sqlalchemy import select
from app.models import Agent, AgentLevel, AgentLevelPrice, AgentProductRule, ProductPrice

@dataclass(frozen=True)
class Quote:
    effective_price: int
    can_purchase: bool
    price_source: str
    restriction: str = ''

    def as_dict(self):
        return self.__dict__

def agent_context(db, user, lock=False):
    if user.role != 'agent':
        return None, None
    query = select(Agent).where(Agent.user_id == user.id)
    if lock:
        query = query.with_for_update(key_share=True).execution_options(populate_existing=True)
    agent = db.scalar(query)
    if not agent:
        return None, None
    query = select(AgentLevel).where(AgentLevel.id == agent.level_id)
    if lock:
        query = query.with_for_update(read=True).execution_options(populate_existing=True)
    return agent, db.scalar(query)

def quote_for(db, product, user, context=None):
    if user.role != 'agent':
        return Quote(product.price, product.active, 'retail', '' if product.active else '商品已下架')
    agent, level = context if context is not None else agent_context(db, user)
    if not agent or not level:
        return Quote(product.price, False, 'unavailable', '代理资料尚未配置，请联系管理员')
    fallback = db.scalar(select(ProductPrice.price).where(ProductPrice.product_id == product.id, ProductPrice.role == 'agent'))
    amount, source = (fallback, 'agent_default') if fallback is not None else (product.price, 'retail')
    level_price = db.scalar(select(AgentLevelPrice.price).where(AgentLevelPrice.level_id == level.id, AgentLevelPrice.product_id == product.id))
    if level_price is not None:
        amount, source = level_price, 'level'
    rule = db.scalar(select(AgentProductRule).where(AgentProductRule.agent_id == agent.user_id, AgentProductRule.product_id == product.id))
    if rule and rule.price is not None:
        amount, source = rule.price, 'agent_override'
    restriction = '商品已下架' if not product.active else '代理等级已停用，请联系管理员' if not level.active else '该商品未向你授权采购' if rule and not rule.allowed else ''
    return Quote(amount, not bool(restriction), source, restriction)

def assert_confirmed(quote, expected_amount):
    if not quote.can_purchase:
        raise HTTPException(403, quote.restriction)
    if quote.effective_price != expected_amount:
        raise HTTPException(409, '商品价格已变化，请刷新后按新价格重新确认购买', headers={'X-Error-Code': 'PRICE_CHANGED'})
