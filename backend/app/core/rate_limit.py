import ipaddress
import threading
import time
from collections import defaultdict, deque
from fastapi import HTTPException, Request
from redis import Redis, RedisError
from app.core.config import get_settings

# In production the shared Redis counter fails closed. Never trust forwarded IP headers.
_buckets = defaultdict(deque)
_expiry = {}
_lock = threading.Lock()
_redis = None
SCRIPT = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n"

def limit(request: Request, scope: str, maximum: int = 20, window: int = 60, *, per_client: bool = True):
    global _redis
    settings = get_settings()
    ip = request.client.host if request.client else 'unknown'
    if settings.trust_proxy and request.headers.get('x-real-ip'):
        try:
            ip = str(ipaddress.ip_address(request.headers['x-real-ip']))
        except ValueError:
            raise HTTPException(400, 'Invalid proxy address')
    key = f'limit:{scope}:{ip if per_client else "shared"}'
    if settings.redis_url:
        try:
            if _redis is None:
                _redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
            count = _redis.eval(SCRIPT, 1, key, window)
        except RedisError:
            raise HTTPException(503, '限流服务暂不可用')
        if count > maximum:
            raise HTTPException(429, '请求过于频繁，请稍后重试', headers={'Retry-After': str(window)})
    else:
        with _lock:
            current = time.monotonic()
            # Expire inactive keys as well, to bound development-only memory use.
            for old in list(_buckets):
                if not _buckets[old] or _expiry.get(old, 0) <= current:
                    del _buckets[old]
                    _expiry.pop(old, None)
            bucket = _buckets[key]
            while bucket and bucket[0] < current - window:
                bucket.popleft()
            if len(bucket) >= maximum:
                raise HTTPException(429, '请求过于频繁，请稍后重试', headers={'Retry-After': str(window)})
            bucket.append(current)
            _expiry[key] = current + window
