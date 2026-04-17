"""
Rate Limiting — Redis-backed sliding window, per user.
"""
import time
from collections import defaultdict, deque
from fastapi import HTTPException

from app.config import settings


_redis_client = None
_use_redis = False


def init_redis(redis_client):
    """Called from main.py after Redis connection is established."""
    global _redis_client, _use_redis
    _redis_client = redis_client
    _use_redis = True


def check_rate_limit(user_id: str) -> dict:
    """
    Sliding window rate limiting per user.
    Uses Redis sorted set for accurate window tracking.
    Returns dict with limit/remaining info.
    """
    now = time.time()
    window_seconds = 60
    key = f"ratelimit:{user_id}"

    if _use_redis:
        pipe = _redis_client.pipeline()
        pipe.zremrangebyscore(key, 0, now - window_seconds)
        pipe.zcard(key)
        pipe.zadd(key, {str(now): now})
        pipe.expire(key, window_seconds + 1)
        results = pipe.execute()
        current_count = results[1]

        limit = settings.rate_limit_per_minute
        remaining = max(0, limit - current_count - 1)

        if current_count >= limit:
            oldest = _redis_client.zrange(key, 0, 0, withscores=True)
            retry_after = int(oldest[0][1] + window_seconds - now) + 1 if oldest else 60
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {limit} req/min",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(now) + window_seconds),
                },
            )
        return {"limit": limit, "remaining": remaining, "reset_at": int(now) + window_seconds}

    # Fallback in-memory rate limiter
    if not hasattr(check_rate_limit, "_windows"):
        check_rate_limit._windows = defaultdict(deque)
    window = check_rate_limit._windows[user_id]
    while window and window[0] < now - window_seconds:
        window.popleft()
    limit = settings.rate_limit_per_minute
    if len(window) >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit} req/min",
            headers={"Retry-After": "60"},
        )
    window.append(now)
    return {"limit": limit, "remaining": limit - len(window) - 1, "reset_at": int(now) + window_seconds}