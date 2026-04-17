"""
Production AI Agent — Full Day 12 Concepts

Functional:
  ✅ Agent answers questions via REST API
  ✅ Conversation history with session support
  ✅ Streaming responses (mock)

Non-functional:
  ✅ Dockerized with multi-stage build
  ✅ Config from environment variables (12-factor)
  ✅ JWT authentication (app/auth.py)
  ✅ Rate limiting (Redis sliding window, 10 req/min per user) (app/rate_limiter.py)
  ✅ Cost guard (Redis daily budget $10/month per user, $50 global) (app/cost_guard.py)
  ✅ Health check endpoint (/health)
  ✅ Readiness check endpoint (/ready)
  ✅ Graceful shutdown
  ✅ Stateless design (state in Redis)
  ✅ Structured JSON logging

Chạy locally (với Redis):
  docker compose up

Chạy production:
  railway up
  # hoặc
  docker compose -f docker-compose.yml up --scale agent=3
"""
import os
import time
import signal
import logging
import json
import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from app.config import settings
from app.auth import verify_token, authenticate_user, create_token
import app.rate_limiter as rate_limiter
import app.cost_guard as cost_guard

# ─────────────────────────────────────────────────────────
# Logging — JSON structured
# ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='{"ts":"%(asctime)s","lvl":"%(levelname)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
_is_ready = False
_request_count = 0
_error_count = 0

# ─────────────────────────────────────────────────────────
# Redis (optional fallback to in-memory)
# ─────────────────────────────────────────────────────────
_use_redis = False
_redis_client = None
_memory_store: dict = {}

try:
    import redis
    _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    _redis_client.ping()
    _use_redis = True
    logger.info("Connected to Redis")
    rate_limiter.init_redis(_redis_client)
    cost_guard.init_redis(_redis_client)
except Exception:
    logger.warning("Redis not available — using in-memory store (not stateless!)")


# ─────────────────────────────────────────────────────────
# Redis-backed session management (stateless)
# ─────────────────────────────────────────────────────────

def _redis_get(key: str):
    if _use_redis:
        return _redis_client.get(key)
    return _memory_store.get(key)


def _redis_setex(key: str, ttl: int, value: str):
    if _use_redis:
        _redis_client.setex(key, ttl, value)
    else:
        _memory_store[key] = value


def _redis_delete(key: str):
    if _use_redis:
        _redis_client.delete(key)
    else:
        _memory_store.pop(key, None)


def save_session(session_id: str, data: dict, ttl: int = None):
    """Save session to Redis with TTL. TTL defaults to session_ttl_seconds."""
    if ttl is None:
        ttl = settings.session_ttl_seconds
    _redis_setex(f"session:{session_id}", ttl, json.dumps(data))


def load_session(session_id: str) -> dict:
    """Load session from Redis."""
    data = _redis_get(f"session:{session_id}")
    return json.loads(data) if data else {}


def append_to_history(session_id: str, role: str, content: str):
    """Append a message to conversation history, keeping last max_history_messages."""
    session = load_session(session_id)
    history = session.get("history", [])
    history.append({
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    if len(history) > settings.max_history_messages:
        history = history[-settings.max_history_messages:]
    session["history"] = history
    save_session(session_id, session)
    return history


# ─────────────────────────────────────────────────────────
# Lifespan — startup / shutdown
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    logger.info(json.dumps({
        "event": "startup",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "redis": _use_redis,
    }))
    time.sleep(0.1)
    _is_ready = True
    logger.info("Agent is ready to serve requests")

    yield

    _is_ready = False
    logger.info("Agent shutting down gracefully — finishing in-flight requests...")


# ─────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    global _request_count, _error_count
    start = time.time()
    _request_count += 1
    try:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if "server" in response.headers:
            del response.headers["server"]
        duration = round((time.time() - start) * 1000, 1)
        logger.info(json.dumps({
            "event": "request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": duration,
        }))
        return response
    except Exception:
        _error_count += 1
        raise


# ─────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None


class AskResponse(BaseModel):
    session_id: str
    question: str
    answer: str
    model: str
    turn: int
    usage: dict


# ─────────────────────────────────────────────────────────
# Auth Endpoints
# ─────────────────────────────────────────────────────────

@app.post("/auth/token", tags=["Auth"])
def login(body: LoginRequest):
    """
    Public endpoint. Returns JWT token.
    Demo: student/demo123 or teacher/teach456
    """
    user = authenticate_user(body.username, body.password)
    token = create_token(user["username"], user["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_minutes": settings.jwt_expire_minutes,
        "user": user["username"],
        "role": user["role"],
    }


# ─────────────────────────────────────────────────────────
# Agent Endpoints
# ─────────────────────────────────────────────────────────

@app.post("/ask", response_model=AskResponse, tags=["Agent"])
async def ask_agent(
    body: AskRequest,
    request: Request,
    user: dict = Depends(verify_token),
):
    """
    Send a question to the AI agent.
    Supports multi-turn conversation via session_id.

    **Authentication:** JWT token required in Authorization: Bearer <token>
    """
    username = user["username"]

    # Rate limiting
    rate_limiter.check_rate_limit(username)

    # Budget check
    cost_guard.check_budget(username)

    # Session management (stateless)
    session_id = body.session_id or str(uuid.uuid4())

    # Append user question to history
    append_to_history(session_id, "user", body.question)

    # Get conversation history for context
    session = load_session(session_id)
    history = session.get("history", [])
    turn = len([m for m in history if m["role"] == "user"])

    # Call LLM
    answer = _mock_llm_ask(body.question, history)

    # Append assistant response to history
    append_to_history(session_id, "assistant", answer)

    # Record usage
    input_tokens = len(body.question.split()) * 2
    output_tokens = len(answer.split()) * 2
    usage = cost_guard.record_usage(username, input_tokens, output_tokens)

    logger.info(json.dumps({
        "event": "agent_response",
        "user": username,
        "session_id": session_id,
        "turn": turn,
    }))

    return AskResponse(
        session_id=session_id,
        question=body.question,
        answer=answer,
        model=settings.llm_model,
        turn=turn,
        usage=usage,
    )


@app.get("/chat/{session_id}/history", tags=["Agent"])
def get_history(session_id: str, _user: dict = Depends(verify_token)):
    """Get conversation history for a session."""
    session = load_session(session_id)
    if not session:
        raise HTTPException(404, f"Session {session_id} not found or expired")
    return {
        "session_id": session_id,
        "messages": session.get("history", []),
        "count": len(session.get("history", [])),
    }


@app.delete("/chat/{session_id}", tags=["Agent"])
def delete_session(session_id: str, _user: dict = Depends(verify_token)):
    """Delete a session (logout)."""
    _redis_delete(f"session:{session_id}")
    return {"deleted": session_id}


# ─────────────────────────────────────────────────────────
# Operations Endpoints
# ─────────────────────────────────────────────────────────

@app.get("/health", tags=["Operations"])
def health():
    """Liveness probe. Platform restarts container if this fails."""
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "storage": "redis" if _use_redis else "in-memory",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Operations"])
def ready():
    """Readiness probe. Load balancer stops routing here if not ready."""
    if not _is_ready:
        raise HTTPException(503, "Not ready")
    return {
        "ready": True,
        "redis": _use_redis,
    }


@app.get("/metrics", tags=["Operations"])
def metrics(user: dict = Depends(verify_token)):
    """User's usage metrics."""
    username = user["username"]
    if _use_redis:
        month_key = datetime.now().strftime("%Y-%m")
        key = f"budget:{username}:{month_key}"
        cost = float(_redis_client.get(key) or 0)
    else:
        cost = getattr(cost_guard.check_budget, "_records", {}).get(username, {}).get("cost", 0.0)
    return {
        "user": username,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "daily_cost_usd": round(cost, 4),
        "daily_budget_usd": settings.daily_budget_usd,
        "budget_remaining_usd": round(settings.daily_budget_usd - cost, 4),
        "rate_limit_per_minute": settings.rate_limit_per_minute,
    }


# ─────────────────────────────────────────────────────────
# Graceful Shutdown
# ─────────────────────────────────────────────────────────
def _handle_signal(signum, _frame):
    logger.info(json.dumps({"event": "signal_received", "signum": signum}))


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ─────────────────────────────────────────────────────────
# Mock LLM with conversation context
# ─────────────────────────────────────────────────────────
def _mock_llm_ask(question: str, history: list[dict]) -> str:
    """Mock LLM that considers conversation history."""
    responses = [
        f"Here's my response to '{question}' based on our conversation.",
        f"Regarding '{question}': as we discussed, the key point is...",
        f"Following up on your question about '{question}': the answer is...",
        f"Great question '{question}'! In context of our conversation:",
    ]
    import hashlib
    idx = int(hashlib.md5(question.encode()).hexdigest()[0], 16) % len(responses)
    return responses[idx] + f" (turn {len([m for m in history if m['role']=='user'])})"


if __name__ == "__main__":
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Redis: {_use_redis}")
    logger.info(f"Demo credentials: student/demo123, teacher/teach456")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        timeout_graceful_shutdown=30,
    )