from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.inspection import inspect

def required(db, model, identity):
    value = db.get(model, identity)
    if not value:
        raise HTTPException(404, '记录不存在')
    return value

def row(value, exclude=()):
    data = {c.key: getattr(value, c.key) for c in inspect(value).mapper.column_attrs if c.key not in exclude}
    return {key: val.replace(tzinfo=timezone.utc) if isinstance(val, datetime) and val.tzinfo is None else val for key, val in data.items()}

def paginate(db, statement, page=1, page_size=20, exclude=()):
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    items = db.scalars(statement.offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [row(item, exclude) for item in items], 'total': total, 'page': page, 'page_size': page_size}
