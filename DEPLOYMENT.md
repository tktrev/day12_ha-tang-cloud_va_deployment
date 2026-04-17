# Deployment Information

## Public URL
https://day12ha-tang-cloudvadeployment-production-8a77.up.railway.app

## Platform
Railway

## Test Commands

### Health Check
```bash
curl https://day12ha-tang-cloudvadeployment-production-8a77.up.railway.app/health
# Expected: {"status": "ok"}
```

### API Test (with authentication)
```bash
curl -X POST https://day12ha-tang-cloudvadeployment-production-8a77.up.railway.app/ask \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
```

### Get JWT Token
```bash
curl -X POST https://day12ha-tang-cloudvadeployment-production-8a77.up.railway.app/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "student", "password": "demo123"}'
```

## Environment Variables Set
- PORT (set by Railway)
- REDIS_URL (set by Railway)
- AGENT_API_KEY (set by Railway, generated value)
- JWT_SECRET (set by Railway, generated value)
- ENVIRONMENT=production
- DAILY_BUDGET_USD=5.0
- RATE_LIMIT_PER_MINUTE=20

## Screenshots
- Deployment dashboard: [screenshots/dashboard.png](screenshots/dashboard.png)
- Service running: [screenshots/service_running.png](screenshots/service_running.png)
- Test results: [screenshots/test.png](screenshots/test.png)

## Service Status
- Health: ✅ OK (tested 2026-04-17)
- Authentication: ✅ Required (401 without token)
- Rate Limiting: ✅ 20 req/min
- Budget Guard: ✅ $5/day