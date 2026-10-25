from datetime import date
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func
from app.api.deps import DB, Admin
from app.models import User, Agent, AgentLevel, AgentLevelPrice, AgentProductRule, Product, AgentRelation
from app.api.reports import filters as report_filters
from app.schemas.requests import AgentLevelInput, AgentAssignment, AgentParentAssignment, AgentLevelPriceInput, AgentProductRuleInput
from app.services.commerce import audit
from app.services.agent_team import assign_parent, team_report
from app.services.pricing import quote_for
from app.repositories.queries import row, required

router = APIRouter(prefix='/admin', tags=['代理配置'])

def locked_agent(db, user_id):
    user = db.scalar(select(User).where(User.id == user_id).with_for_update(key_share=True).execution_options(populate_existing=True))
    if not user or user.role != 'agent':
        raise HTTPException(404, '代理不存在')
    agent = db.scalar(select(Agent).where(Agent.user_id == user_id).with_for_update(key_share=True).execution_options(populate_existing=True))
    if not agent:
        raise HTTPException(409, '代理资料未初始化')
    return user, agent

@router.get('/agent-levels')
def levels(actor: Admin, db: DB):
    return [row(level) for level in db.scalars(select(AgentLevel).order_by(AgentLevel.sort, AgentLevel.id).limit(1000))]

@router.post('/agent-levels', status_code=201)
def create_level(payload: AgentLevelInput, actor: Admin, db: DB):
    if db.scalar(select(func.count()).select_from(AgentLevel)) >= 1000:
        raise HTTPException(409, '代理等级最多1000个')
    level = AgentLevel(**payload.model_dump())
    db.add(level); db.flush()
    audit(db, actor, 'agent-levels.create', level.id, f'name={level.name};active={level.active}')
    db.commit()
    return row(level)

@router.put('/agent-levels/{level_id}')
def update_level(level_id: int, payload: AgentLevelInput, actor: Admin, db: DB):
    level = db.scalar(select(AgentLevel).where(AgentLevel.id == level_id).with_for_update(key_share=True))
    if not level:
        raise HTTPException(404, '等级不存在')
    for key, value in payload.model_dump().items():
        setattr(level, key, value)
    audit(db, actor, 'agent-levels.update', level.id, f'name={level.name};active={level.active}')
    db.commit()
    return row(level)

@router.get('/agents')
def agents(actor: Admin, db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), q: str = Query('', max_length=100), level_id: int | None = None):
    query = select(User, Agent, AgentLevel, AgentRelation.parent_id).join(Agent, Agent.user_id == User.id).join(AgentLevel, AgentLevel.id == Agent.level_id).outerjoin(AgentRelation, AgentRelation.child_id == User.id).where(User.role == 'agent')
    if q:
        query = query.where(User.email.icontains(q, autoescape=True))
    if level_id:
        query = query.where(Agent.level_id == level_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    result = db.execute(query.order_by(User.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return {'items': [{**row(user, ('password_hash','token_version')), 'level_id': agent.level_id, 'level_name': level.name, 'level_active': level.active, 'parent_id': parent_id} for user,agent,level,parent_id in result], 'total': total, 'page': page, 'page_size': page_size}

@router.put('/agents/{user_id}/level')
def assign_level(user_id: int, payload: AgentAssignment, actor: Admin, db: DB):
    user, agent = locked_agent(db, user_id)
    level = db.scalar(select(AgentLevel).where(AgentLevel.id == payload.level_id).with_for_update(read=True))
    if not level or not level.active:
        raise HTTPException(409, '目标等级不存在或已停用')
    before = agent.level_id
    agent.level_id = level.id
    audit(db, actor, 'agents.assign-level', user.id, f'from={before};to={level.id}')
    db.commit()
    return {'user_id': user.id, 'level_id': level.id, 'level_name': level.name}

@router.get('/agent-levels/{level_id}/prices')
def level_prices(level_id: int, actor: Admin, db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), q: str = Query('', max_length=100)):
    required(db, AgentLevel, level_id)
    query = select(Product, AgentLevelPrice.price).outerjoin(AgentLevelPrice, (AgentLevelPrice.product_id == Product.id) & (AgentLevelPrice.level_id == level_id))
    if q:
        query = query.where(Product.name.icontains(q, autoescape=True))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    data = db.execute(query.order_by(Product.sort, Product.id).offset((page-1)*page_size).limit(page_size)).all()
    return {'items': [{**row(product), 'level_price': price} for product, price in data], 'total': total, 'page': page, 'page_size': page_size}

@router.put('/agent-levels/{level_id}/prices/{product_id}')
def set_level_price(level_id: int, product_id: int, payload: AgentLevelPriceInput, actor: Admin, db: DB):
    level = db.scalar(select(AgentLevel).where(AgentLevel.id == level_id).with_for_update(key_share=True))
    if not level:
        raise HTTPException(404, '等级不存在')
    required(db, Product, product_id)
    price = db.scalar(select(AgentLevelPrice).where(AgentLevelPrice.level_id == level_id, AgentLevelPrice.product_id == product_id))
    before = price.price if price else None
    if price:
        price.price = payload.price
    else:
        db.add(AgentLevelPrice(level_id=level_id, product_id=product_id, price=payload.price))
    audit(db, actor, 'agent-levels.price', f'{level_id}:{product_id}', f'from={before};to={payload.price}')
    db.commit()
    return {'level_id': level_id, 'product_id': product_id, 'price': payload.price}

@router.delete('/agent-levels/{level_id}/prices/{product_id}')
def reset_level_price(level_id: int, product_id: int, actor: Admin, db: DB):
    level = db.scalar(select(AgentLevel).where(AgentLevel.id == level_id).with_for_update(key_share=True))
    if not level:
        raise HTTPException(404, '等级不存在')
    value = db.scalar(select(AgentLevelPrice).where(AgentLevelPrice.level_id == level_id, AgentLevelPrice.product_id == product_id))
    if value:
        db.delete(value)
    audit(db, actor, 'agent-levels.price-reset', f'{level_id}:{product_id}')
    db.commit()
    return {'message': '已恢复默认代理价'}

@router.get('/agents/{user_id}/products')
def agent_products(user_id: int, actor: Admin, db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), q: str = Query('', max_length=100)):
    user = required(db, User, user_id)
    if user.role != 'agent' or not db.get(Agent, user_id):
        raise HTTPException(404, '代理不存在')
    query = select(Product, AgentProductRule).outerjoin(AgentProductRule, (AgentProductRule.product_id == Product.id) & (AgentProductRule.agent_id == user_id))
    if q:
        query = query.where(Product.name.icontains(q, autoescape=True))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    data = db.execute(query.order_by(Product.sort, Product.id).offset((page-1)*page_size).limit(page_size)).all()
    return {'items': [{**row(product), **quote_for(db, product, user).as_dict(), 'override_price': rule.price if rule else None, 'allowed': rule.allowed if rule else True} for product, rule in data], 'total': total, 'page': page, 'page_size': page_size}

@router.put('/agents/{user_id}/products/{product_id}')
def set_agent_rule(user_id: int, product_id: int, payload: AgentProductRuleInput, actor: Admin, db: DB):
    user, agent = locked_agent(db, user_id)
    required(db, Product, product_id)
    rule = db.scalar(select(AgentProductRule).where(AgentProductRule.agent_id == user_id, AgentProductRule.product_id == product_id))
    before = f'price={rule.price};allowed={rule.allowed}' if rule else 'inherited'
    if rule:
        rule.price, rule.allowed = payload.price, payload.allowed
    else:
        db.add(AgentProductRule(agent_id=user_id, product_id=product_id, **payload.model_dump()))
    audit(db, actor, 'agents.product-rule', f'{user.id}:{product_id}', f'from={before};price={payload.price};allowed={payload.allowed}')
    db.commit()
    return payload

@router.get('/agents/{user_id}/team')
def team(user_id: int, actor: Admin, db: DB, start: date | None = None, end: date | None = None, page: int = Query(1, ge=1),
         page_size: int = Query(20, ge=1, le=100), q: str = Query('', max_length=80)):
    parent = required(db, User, user_id)
    if parent.role != 'agent' or not db.get(Agent, user_id):
        raise HTTPException(404, '代理不存在')
    query = report_filters(start, end, None, None)
    return team_report(db, user_id, query['start'], query['end'], page, page_size, q)

@router.put('/agents/{user_id}/parent')
def parent(user_id: int, payload: AgentParentAssignment, actor: Admin, db: DB):
    result = assign_parent(db, actor, user_id, payload)
    db.commit()
    return result

@router.delete('/agents/{user_id}/products/{product_id}')
def reset_agent_rule(user_id: int, product_id: int, actor: Admin, db: DB):
    user, agent = locked_agent(db, user_id)
    value = db.scalar(select(AgentProductRule).where(AgentProductRule.agent_id == user_id, AgentProductRule.product_id == product_id))
    if value:
        db.delete(value)
    audit(db, actor, 'agents.product-rule-reset', f'{user.id}:{product_id}')
    db.commit()
    return {'message': '已恢复等级定价与默认商品权限'}
