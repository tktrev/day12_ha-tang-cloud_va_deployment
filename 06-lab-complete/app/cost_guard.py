"""
Cost Guard — Redis-backed daily/monthly budget per user.
"""
import time
from datetime import datetime
from fastapi import HTTPException

from app.config import settings


_redis_client = None
_use_redis = False


def init_redis(redis_client):
    """Called from main.py after Redis connection is established."""
    global _redis_client, _use_redis
    _redis_client = redis_client
    _use_redis = True


def check_budget(user_id: str) -> None:
    """Check if user has budget remaining. Raises 402 if exceeded."""
    if _use_redis:
        month_key = datetime.now().strftime("%Y-%m")
        key = f"budget:{user_id}:{month_key}"
        current = float(_redis_client.get(key) or 0)

        if current >= settings.daily_budget_usd:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "Daily budget exceeded",
                    "used_usd": round(current, 4),
                    "budget_usd": settings.daily_budget_usd,
                    "resets_at": "midnight UTC",
                },
            )
    else:
        if not hasattr(check_budget, "_records"):
            check_budget._records = {}
        today = time.strftime("%Y-%m-%d")
        record = check_budget._records.get(user_id, {"day": today, "cost": 0.0})
        if record["day"] != today:
            record = {"day": today, "cost": 0.0}
        if record["cost"] >= settings.daily_budget_usd:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "Daily budget exceeded",
                    "used_usd": round(record["cost"], 4),
                    "budget_usd": settings.daily_budget_usd,
                },
            )
        check_budget._records[user_id] = record


def record_usage(user_id: str, input_tokens: int, output_tokens: int) -> dict:
    """Record usage and return usage record."""
    input_cost = (input_tokens / 1000) * (settings.price_per_1k_input_tokens / 1000)
    output_cost = (output_tokens / 1000) * (settings.price_per_1k_output_tokens / 1000)
    total_cost = input_cost + output_cost

    if _use_redis:
        month_key = datetime.now().strftime("%Y-%m")
        key = f"budget:{user_id}:{month_key}"
        _redis_client.incrbyfloat(key, total_cost)
        _redis_client.expire(key, 32 * 24 * 3600)
        current = float(_redis_client.get(key) or 0)
        return {
            "user_id": user_id,
            "date": month_key,
            "cost_usd": round(current, 6),
            "budget_usd": settings.daily_budget_usd,
            "remaining_usd": round(settings.daily_budget_usd - current, 6),
        }
    else:
        if not hasattr(record_usage, "_records"):
            record_usage._records = {}
        today = time.strftime("%Y-%m-%d")
        record = record_usage._records.get(user_id, {"day": today, "cost": 0.0})
        if record["day"] != today:
            record = {"day": today, "cost": 0.0}
        record["cost"] += total_cost
        record_usage._records[user_id] = record
        return {
            "user_id": user_id,
            "date": record["day"],
            "cost_usd": round(record["cost"], 6),
            "budget_usd": settings.daily_budget_usd,
            "remaining_usd": round(settings.daily_budget_usd - record["cost"], 6),
        }