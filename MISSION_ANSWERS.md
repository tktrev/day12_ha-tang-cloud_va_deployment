# Day 12 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

1. **Hardcoded API Key** (line 17): `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` — Secret exposed in source code; if pushed to GitHub, key is compromised immediately.

2. **Hardcoded Database URL** (line 18): `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"` — Credentials exposed in code.

3. **No Config Management** (lines 20-22): `DEBUG = True`, `MAX_TOKENS = 500` are hardcoded, not reading from environment variables.

4. **Debug Logging** (lines 33-34): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` — Logs secrets to stdout.

5. **No Health Check Endpoint**: No `/health` or `/ready` endpoints. If the agent crashes, the cloud platform won't know to restart it.

6. **Fixed Port** (line 52): `port=8000` hardcoded; Railway/Render inject PORT via env var, so this won't work on cloud deployment.

7. **Debug Reload in Production** (line 53): `reload=True` in `uvicorn.run()` — dangerous in production as it can cause unexpected behavior.

8. **Localhost Binding** (line 51): `host="localhost"` — container can't accept external connections when bound to localhost only.

### Exercise 1.3: Comparison table

| Feature | Basic (develop) | Advanced (production) | Why Important? |
|---------|-----------------|----------------------|----------------|
| Config | Hardcoded (`OPENAI_API_KEY = "sk-..."`) | Environment variables (`from config import settings`) | Secrets stay outside code; safe to commit to git |
| Health check | None | `/health` and `/ready` endpoints | Platform knows when to restart; LB routes traffic only to ready instances |
| Logging | `print()` statements | Structured JSON logging (`logging.basicConfig` with JSON format) | Parsable by log aggregators (Datadog, Loki); no secrets leaked |
| Shutdown | Sudden (`uvicorn.run` with no signal handling) | Graceful (`lifespan` context manager + `signal.signal(signal.SIGTERM, handle_sigterm)`) | In-flight requests complete before shutdown; no dropped requests |
| Port binding | `port=8000` (fixed) | `port=settings.port` from `PORT` env var | Railway/Render inject PORT via env; hardcoded port fails on cloud |
| Host binding | `host="localhost"` | `host=settings.host` (0.0.0.0) | Container needs to accept external connections from outside |
| Debug mode | `DEBUG = True` always on | `settings.debug` controls reload | Debug reload in production causes instability |
| CORS | Not configured | `CORSMiddleware` with `settings.allowed_origins` | Prevents unauthorized cross-origin requests |

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

**File:** `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` — Full Python distribution, approx 1 GB.

2. **Working directory:** `/app` (set by `WORKDIR /app`).

3. **Why COPY requirements.txt first?** Docker uses layer caching. If requirements.txt hasn't changed, Docker reuses the cached layer for `pip install`. Without this, any code change would invalidate the dependency installation layer and re-run `pip install` every time.

4. **CMD vs ENTRYPOINT:**
   - `CMD`: Default arguments for the container; can be overridden at runtime.
   - `ENTRYPOINT`: Defines the main command; arguments append to it.
   - In this Dockerfile, `CMD ["python", "app.py"]` runs Python with app.py as the script.

### Exercise 2.3: Image size comparison

- **Develop (single-stage):** `python:3.11` base image (~1 GB uncompressed). Contains full Python distribution, build tools, and all installed packages in one layer.

- **Production (multi-stage):** `python:3.11-slim` base (~150 MB base), no build tools in final image. Only runtime dependencies copied from builder stage.

- **Difference:** Production multi-stage build is approximately **80-85% smaller** because:
  - `python:3.11-slim` is a stripped-down image (vs full `python:3.11`)
  - Build dependencies (gcc, libpq-dev) are only in Stage 1 (builder), not carried to Stage 2 (runtime)
  - Only installed site-packages copied, not the entire pip cache

**Key Dockerfile differences:**

| Aspect | Develop | Production |
|--------|---------|------------|
| Base image | `python:3.11` | `python:3.11-slim` |
| Build stages | Single | Multi-stage (builder + runtime) |
| Build tools | In final image | Only in builder stage |
| Non-root user | No | Yes (`RUN groupadd -r appuser && useradd -r -g appuser appuser`) |
| Health check | None | `HEALTHCHECK` defined |
| Workers | Single uvicorn | `--workers 2` |

### Exercise 2.4: Docker Compose architecture

**Services and communication:**

```
Client (curl/Postman)
        │
        ▼
┌───────────────┐
│   Nginx (LB)  │  port 80
└───────┬───────┘
        │ routes to agent:8000
        │
   ┌────┴────┬────────┐
   ▼         ▼        ▼
┌──────┐ ┌──────┐  ┌──────┐
│Agent1│ │Agent2│  │Agent3│  (replicas)
└──┬───┘ └──┬───┘  └──┬───┘
   │        │        │
   └────────┴────────┘
            │
            ▼
    ┌───────────────┐
    │  Redis (6379) │  session cache + rate limiting
    └───────────────┘

    ┌───────────────┐
    │ Qdrant (6333) │  vector database for RAG
    └───────────────┘
```

**Services:**
1. **agent** — FastAPI app (2 replicas), only accessible via nginx, not directly exposed
2. **redis** — Cache for sessions and rate limiting
3. **qdrant** — Vector database for RAG (Retrieval Augmented Generation)
4. **nginx** — Reverse proxy + load balancer, only service exposed on port 80/443

**Communication:**
- Agent → Redis: `REDIS_URL=redis://redis:6379/0`
- Agent → Qdrant: `QDRANT_URL=http://qdrant:6333`
- Nginx → Agent: proxypass to `http://agent:8000`
- External traffic → Nginx (port 80) → Agent replicas

**Health check flow:** Docker calls `HEALTHCHECK` on agent; if fail, container restarts automatically.

---

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment

- **URL:** https://day12ha-tang-cloudvadeployment-production-761e.up.railway.app
- **Screenshot:** `03-cloud-deployment/railway/app_screenshot.png`

**Steps taken:**
1. Installed Railway CLI: `npm i -g @railway/cli`
2. Logged in: `railway login`
3. Initialized project: `railway init`
4. Set environment variables:
   - `PORT=8000`
   - `AGENT_API_KEY=my-secret-key`
5. Deployed: `railway up`
6. Retrieved domain: `railway domain`

**Verification:**
```bash
curl http://day12ha-tang-cloudvadeployment-production-761e.up.railway.app/health
# Returns: {"status":"ok","uptime_seconds":...,"platform":"Railway",...}

curl -X POST http://day12ha-tang-cloudvadeployment-production-761e.up.railway.app/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Docker?"}'
# Returns: {"question":"...","answer":"...","platform":"Railway"}
```

### Exercise 3.2: Render vs Railway comparison

| Aspect | Railway | Render |
|--------|---------|--------|
| Config file | `railway.toml` | `render.yaml` |
| CLI command | `railway up` | `render deploy` |
| Environment variables | `railway variables set KEY=value` | Dashboard UI or `render.yaml` envVars |
| Health check | `healthcheckPath = "/health"` | `healthCheckPath: /health` |
| Auto-deploy | On push via CLI | On push to GitHub (connected repo) |
| Region | Auto-detected | `region: singapore` (configurable) |
| Start command | `uvicorn app:app --host 0.0.0.0 --port $PORT` | `uvicorn app:app --host 0.0.0.0 --port $PORT` |
| Redis support | External (e.g. Upstash) | Render Redis add-on available |

**Key difference:** Railway uses `railway.toml` for declarative infrastructure-as-code, while Render uses `render.yaml`. Both support health checks and automatic restarts on failure.

### Exercise 3.3: GCP Cloud Run (Optional)

**Files examined:** `03-cloud-deployment/production-cloud-run/`

- **cloudbuild.yaml**: Defines CI/CD pipeline — builds Docker image, pushes to Artifact Registry, deploys to Cloud Run.
- **service.yaml**: Cloud Run service definition with `--port` flag matching the app's expected PORT env var, and `CONTAINER_PORT` for the container listener.

**Key insight:** GCP Cloud Run uses `cloudbuild.yaml` for CI/CD (GCP's native build system) vs Railway/Render's simpler CLI-based deployment. Cloud Run also requires `--port` flag to specify the port the container listens on.

---

## Part 4: API Security

### Exercise 4.1: API Key authentication

**File:** `04-api-gateway/develop/app.py`

**How it works:**
- API key stored in environment variable: `API_KEY = os.getenv("AGENT_API_KEY", "demo-key-change-in-production")`
- Header name: `X-API-Key` (configured via `APIKeyHeader(name="X-API-Key", auto_error=False)`)
- Verification function `verify_api_key()` is a FastAPI dependency — inject with `Depends(verify_api_key)`

**If key is wrong:** Returns HTTP 403 Forbidden with `{"detail": "Invalid API key."}`

**If key is missing:** Returns HTTP 401 Unauthorized with `{"detail": "Missing API key. Include header: X-API-Key: <your-key>"}`

**To rotate key:** Change `AGENT_API_KEY` environment variable — no code changes needed. New connections use new key immediately.

**Test:**
```bash
# Without key → 401
curl -X POST -H "Content-Type: application/json" \
     -d '{"question":"hello"}' http://localhost:8000/ask
# {"detail":"Missing API key..."}

# With key → 200
curl -H "X-API-Key: demo-key-change-in-production" -X POST \
     -H "Content-Type: application/json" \
     -d '{"question":"hello"}' http://localhost:8000/ask
# {"question":"hello","answer":"..."}
```

### Exercise 4.2: JWT authentication

**File:** `04-api-gateway/production/auth.py`

**JWT Flow:**
1. User POSTs username/password to `/auth/token`
2. Server validates against `DEMO_USERS` dict: `{"student": {"password": "demo123", "role": "user"}}`
3. Server creates JWT with payload: `{"sub": username, "role": role, "iat": ..., "exp": ...}`
4. JWT signed with `HS256` algorithm and `SECRET_KEY` env var
5. Client sends token in `Authorization: Bearer <token>` header on subsequent requests
6. Server verifies signature and expiry on every protected endpoint

**Token contents:**
```json
{
  "sub": "student",      // username
  "role": "user",         // or "admin"
  "iat": 1713000000,      // issued at (Unix timestamp)
  "exp": 1713003600       // expires in 60 minutes
}
```

**Demo credentials:**
- `student / demo123` — 10 req/min, $1/day budget
- `teacher / teach456` — 100 req/min, admin role

**Test:**
```bash
# Get token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"student","password":"demo123"}' | jq -r '.access_token')

# Use token
curl -H "Authorization: Bearer $TOKEN" -X POST \
  -H "Content-Type: application/json" \
  -d '{"question":"what is docker?"}' \
  http://localhost:8000/ask
```

### Exercise 4.3: Rate limiting

**File:** `04-api-gateway/production/rate_limiter.py`

**Algorithm:** Sliding Window Counter
- Each user has a `deque` of request timestamps
- On each request, old timestamps (> window_seconds old) are removed
- If remaining count >= max_requests → 429 Too Many Requests
- Headers returned: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`

**Limits:**
- User tier: `max_requests=10, window_seconds=60` → 10 req/minute
- Admin tier: `max_requests=100, window_seconds=60` → 100 req/minute

**Bypass for admin:** The `rate_limiter_admin` instance has 10x higher limit. Admin role is checked in `app.py`:
```python
limiter = rate_limiter_admin if role == "admin" else rate_limiter_user
```

**Test:**
```bash
# Send 20 requests quickly (limit is 10/min for user)
for i in {1..20}; do
  curl -s -H "Authorization: Bearer $TOKEN" -X POST \
    -H "Content-Type: application/json" \
    -d '{"question":"Test '$i'"}' \
    http://localhost:8000/ask | jq -r '.detail // .question'
  echo ""
done
# First 10 succeed, then 429 with retry info
```

### Exercise 4.4: Cost guard implementation

**File:** `04-api-gateway/production/cost_guard.py`

**Logic:**
1. `check_budget(user_id)` — called BEFORE LLM request
   - Checks global daily budget ($10 total)
   - Checks per-user daily budget ($1/day for user, higher for admin)
   - If exceeded: raise HTTPException(402, "Daily budget exceeded")
   - Warning logged at 80% usage

2. `record_usage(user_id, input_tokens, output_tokens)` — called AFTER LLM response
   - Calculates cost: `(input_tokens/1000 * $0.00015) + (output_tokens/1000 * $0.0006)`
   - Updates user's UsageRecord
   - Updates global cost tracker

3. Cost persisted in-memory (in production, would use Redis with daily TTL)

**Key implementation:**
```python
def check_budget(user_id: str) -> None:
    record = self._get_record(user_id)

    # Global check
    if self._global_cost >= self.global_daily_budget_usd:
        raise HTTPException(503, "Service unavailable due to budget limits")

    # Per-user check
    if record.total_cost_usd >= self.daily_budget_usd:
        raise HTTPException(402, {
            "error": "Daily budget exceeded",
            "used_usd": record.total_cost_usd,
            "budget_usd": self.daily_budget_usd,
        })
```

**Pricing reference** (GPT-4o-mini rates):
- Input: $0.15 per 1M tokens ($0.00015 per 1K)
- Output: $0.60 per 1M tokens ($0.0006 per 1K)

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks implementation

**File:** `05-scaling-reliability/develop/app.py`

**Liveness probe (`/health`):**
```python
@app.get("/health")
def health():
    return {
        "status": "ok",  # or "degraded" if checks fail
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "version": "1.0.0",
        "environment": os.getenv("ENVIRONMENT", "development"),
        "checks": {"memory": {"status": "ok", "used_percent": ...}},
    }
```
Platform calls this periodically. Non-200 = restart container.

**Readiness probe (`/ready`):**
```python
@app.get("/ready")
def ready():
    if not _is_ready:
        raise HTTPException(503, "Agent not ready. Check back in a few seconds.")
    return {"ready": True, "in_flight_requests": _in_flight_requests}
```
Load balancer uses this to decide whether to route traffic to this instance.

### Exercise 5.2: Graceful shutdown implementation

**File:** `05-scaling-reliability/develop/app.py`

**Signal handling:**
```python
def handle_sigterm(signum, frame):
    logger.info(f"Received signal {signum} — uvicorn will handle graceful shutdown")

signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)
```

**Lifespan context manager for cleanup:**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    _is_ready = True
    yield
    # Shutdown
    _is_ready = False
    while _in_flight_requests > 0:  # Wait for in-flight requests
        time.sleep(1)
```

**Test:**
```bash
python app.py &
PID=$!

# Send request
curl http://localhost:8000/ask -X POST \
  -H "Content-Type: application/json" \
  -d '{"question": "Long task"}' &

# Kill with SIGTERM
kill -TERM $PID

# Observe: request completes before shutdown, log shows "Graceful shutdown initiated"
```

### Exercise 5.3: Stateless design

**File:** `05-scaling-reliability/production/app.py`

**Why in-memory state fails at scale:**
```
Instance 1: User A request 1 → stored in Instance 1's memory
Instance 2: User A request 2 → Instance 2 has NO memory of User A's session → BUG
```

**Solution: Redis-backed session storage:**
```python
def save_session(session_id: str, data: dict, ttl_seconds: int = 3600):
    serialized = json.dumps(data)
    _redis.setex(f"session:{session_id}", ttl_seconds, serialized)

def load_session(session_id: str) -> dict:
    data = _redis.get(f"session:{session_id}")
    return json.loads(data) if data else {}
```

**Architecture:**
```
Request → Any Agent Instance → Redis (session:{id}) → Response
                          ↑
                     All instances share same Redis
```

**With `--scale agent=3`:** Any of the 3 instances can handle any user's request — Redis ensures consistency.

### Exercise 5.4: Load balancing with Nginx

**Architecture:**
```
Client → Nginx (port 80) → agent:8000 (round-robin)
                          ├─→ Agent Instance 1
                          ├─→ Agent Instance 2
                          └─→ Agent Instance 3

Health check: nginx detects failed instance → route traffic to healthy ones
```

**Nginx config** (`nginx/nginx.conf`): Upstream block defines `agent:8000` with `least_conn` or `round_robin`. Nginx auto-reloads when container count changes via Docker's dynamic discovery.

**Test:**
```bash
docker compose up --scale agent=3

# Send 10 requests — observe served_by field changes
for i in {1..10}; do
  curl -s -X POST http://localhost/chat \
    -H "Content-Type: application/json" \
    -d '{"question":"Test '$i'"}' | jq '.served_by'
done
# Output: instance-a, instance-b, instance-c (round-robin across instances)
```

### Exercise 5.5: Stateless test results

**File:** `05-scaling-reliability/production/test_stateless.py`

**Test scenario:**
1. Create new session (no session_id provided → generates UUID)
2. Send 5 questions in sequence
3. Check which instances served each request
4. Verify conversation history is preserved

**Expected output:**
```
Session ID: abc-123-def

Request 1: [instance-a]
  Q: What is Docker?
  A: Docker is a platform...

Request 2: [instance-b]
  Q: Why do we need containers?
  A: Containers provide...

Request 3: [instance-c]
  ...

--- Conversation History ---
Total messages: 10  (5 user + 5 assistant)
✅ Session history preserved across all instances via Redis!
```

**Key insight:** Even though requests were distributed to different instances, the conversation history was preserved because all instances read/write to the same Redis backend.

---

## Part 6: Final Project (Reference)

For the final project, all concepts from Parts 1-5 are combined:

- **Docker**: Multi-stage build with `python:3.11-slim`, non-root user
- **Config**: All settings from environment variables (no hardcoding)
- **Auth**: JWT with `/auth/token` endpoint, role-based access
- **Rate limiting**: Sliding window per user tier
- **Cost guard**: Per-user daily budget with global cap
- **Health checks**: `/health` (liveness) + `/ready` (readiness)
- **Graceful shutdown**: SIGTERM handler + lifespan cleanup
- **Stateless**: All session state in Redis, not in-memory
- **Load balancing**: Nginx distributes to multiple agent replicas
- **Deployment**: Railway or Render with `railway.toml` or `render.yaml`

**Validation script** (`06-lab-complete/check_production_ready.py`) checks all these criteria.