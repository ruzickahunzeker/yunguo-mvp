from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from app.core.config import get_settings
from app.core.db import engine
from app.api import auth, public, member, admin, agents_admin, reports, audit_logs, operations

settings = get_settings()
app = FastAPI(title='云果 · 数字服务管理平台', version='0.1.0', description='金额单位均为分。修改交易接口需 Idempotency-Key。仅模拟/人工履约。')
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=['GET','POST','PUT','PATCH','DELETE'], allow_headers=['Authorization','Content-Type','Idempotency-Key'], expose_headers=['X-Error-Code'])
for router in (auth.router, public.router, member.router, admin.router, agents_admin.router, reports.router, audit_logs.router, operations.router):
    app.include_router(router, prefix='/api')

@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # Do not reflect raw passwords, tokens or codes in validation error payloads.
    return JSONResponse(status_code=422, content={'detail': [{'loc': list(e['loc']), 'msg': e['msg'], 'type': e['type']} for e in exc.errors()]})

@app.exception_handler(IntegrityError)
async def conflict(request: Request, exc: IntegrityError):
    return JSONResponse(status_code=409, content={'detail': '数据冲突，请使用相同幂等键重试或刷新记录'})

@app.exception_handler(OperationalError)
async def unavailable(request: Request, exc: OperationalError):
    return JSONResponse(status_code=503, content={'detail': '数据库暂不可用，请稍后重试'})

@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'same-origin'
    return response

@app.get('/api/health', tags=['健康检查'])
def health():
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
    return {'status': 'ok', 'mode': settings.fulfillment_mode, 'demo': settings.demo_recharge_enabled}
