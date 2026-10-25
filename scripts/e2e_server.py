"""Disposable E2E fixture, never a deployment entrypoint.
Binds only loopback, uses a TemporaryDirectory database, SMTP sink and mailbox.
Contains fixed test-only passwords; no production data/configuration is loaded.
"""
import json
import os
from pathlib import Path
import re
import secrets
import socketserver
import sys
import tempfile
import threading
import time
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
TEMP = tempfile.TemporaryDirectory(prefix='yunguo-e2e-')
os.environ.update(APP_ENV='test', DATABASE_URL=f'sqlite:///{TEMP.name}/browser.db',
    JWT_SECRET=secrets.token_hex(32), CODE_PEPPER=secrets.token_hex(32), REDIS_URL='',
    TRUST_PROXY='false', DEMO_RECHARGE_ENABLED='true', FULFILLMENT_MODE='mock',
    PASSWORD_RESET_ENABLED='true', EMAIL_VERIFICATION_ENABLED='true', REQUIRE_VERIFIED_EMAIL_FOR_PURCHASE='false', SMTP_HOST='127.0.0.1', SMTP_PORT='8801',
    SMTP_SECURITY='none', SMTP_USERNAME='', SMTP_PASSWORD='', SMTP_FROM='test@example.com',
    PUBLIC_BASE_URL='http://127.0.0.1:8803')
from app.core.db import Base, engine, SessionLocal
from app.core.security import hash_password
from app.cli import seed_basics
from app.models import User, Wallet, Product, ProductPrice, Agent
from app.tasks.worker import run_once as fulfill_once
from app.tasks.mail_worker import run_once as mail_once
from app.services.monitoring import run_once as monitor_once, heartbeat
from app.core import rate_limit
from app.core.config import get_settings
from app.main import app
import uvicorn

Base.metadata.create_all(engine)
with SessionLocal() as db:
    seed_basics(db)
    for email, role in [('browser-admin@example.com','admin'),('browser-agent@example.com','agent')]:
        user=User(email=email,name='测试管理员' if role=='admin' else '测试代理',role=role,password_hash=hash_password('Browser-fixture-password-2026'))
        db.add(user);db.flush();db.add(Wallet(user_id=user.id))
        if role=='agent':db.add(Agent(user_id=user.id))
    product=Product(name='浏览器验收套餐',description='本地端到端测试，无真实权益开通。',original_price=1500,price=1000,stock=1000)
    db.add(product);db.flush();db.add(ProductPrice(product_id=product.id,role='agent',price=800));db.commit()

messages=[]
message_lock=threading.Lock()
class SMTPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        def reply(value):
            self.wfile.write((value+'\r\n').encode());self.wfile.flush()
        reply('220 localhost test SMTP')
        while True:
            line=self.rfile.readline(65537)
            if not line:return
            command=line.decode(errors='replace').strip().upper()
            if command.startswith(('EHLO','HELO')):reply('250-localhost\r\n250 SIZE 65536')
            elif command.startswith(('MAIL FROM:','RCPT TO:','RSET','NOOP')):reply('250 OK')
            elif command=='DATA':
                reply('354 End with dot')
                data=[]
                while True:
                    part=self.rfile.readline(65537)
                    if not part:return
                    if part in (b'.\r\n',b'.\n'):break
                    data.append(part[1:] if part.startswith(b'..') else part)
                email=BytesParser(policy=policy.default).parsebytes(b''.join(data))
                token=re.search(r'/(reset-password|verify-email)#token=([a-f0-9]{64})',email.get_content())
                with message_lock:
                    messages.append({'email':str(email['To']),'token':token.group(2) if token else '', 'purpose':'email_verification' if token and token.group(1)=='verify-email' else 'password_reset'})
                reply('250 accepted')
            elif command=='QUIT':reply('221 Bye');return
            else:reply('502 unsupported')
class SMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True
class Mailbox(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        parsed=urlsplit(self.path)
        if parsed.path=='/monitor-tick':
            heartbeat('fulfillment');heartbeat('mail');monitor_once()
            value={'status':'ok'}
        elif parsed.path=='/fulfillment-policy':
            get_settings().fulfillment_mode='manual' if parse_qs(parsed.query).get('manual',['false'])[0]=='true' else 'mock'
            value={'status':'ok'}
        elif parsed.path=='/purchase-policy':
            get_settings().require_verified_email_for_purchase=parse_qs(parsed.query).get('required',['false'])[0]=='true'
            value={'status':'ok'}
        elif parsed.path=='/reset-limits':
            get_settings().require_verified_email_for_purchase=False
            get_settings().fulfillment_mode='mock'
            with rate_limit._lock:
                rate_limit._buckets.clear();rate_limit._expiry.clear()
            value={'status':'ok'}
        elif parsed.path=='/messages':
            email=parse_qs(parsed.query).get('email',[''])[0]
            with message_lock:value=[m for m in messages if m['email']==email]
        elif parsed.path=='/health':value={'status':'ok'}
        else:self.send_error(404);return
        content=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(content)

stop=threading.Event()
def worker():
    last_beat=0
    while not stop.is_set():
        fulfill_once();mail_once()
        if time.monotonic()-last_beat>=1:
            heartbeat('fulfillment');heartbeat('mail');monitor_once();last_beat=time.monotonic()
        stop.wait(.15)

smtp=SMTPServer(('127.0.0.1',8801),SMTPHandler)
mailbox=ThreadingHTTPServer(('127.0.0.1',8802),Mailbox)
for fn in (smtp.serve_forever,mailbox.serve_forever,worker):threading.Thread(target=fn,daemon=True).start()
try:
    uvicorn.run(app,host='127.0.0.1',port=8800,access_log=False,log_level='warning')
finally:
    stop.set();smtp.shutdown();smtp.server_close();mailbox.shutdown();mailbox.server_close();engine.dispose();TEMP.cleanup()
