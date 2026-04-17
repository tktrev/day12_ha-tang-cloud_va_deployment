"""
Authentication — JWT + API Key.
"""
import jwt
from datetime import datetime, timezone
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings


security = HTTPBearer(auto_error=False)

# Demo users for JWT auth
DEMO_USERS = {
    "student": {"password": "demo123", "role": "user"},
    "teacher": {"password": "teach456", "role": "admin"},
}


def create_token(username: str, role: str) -> str:
    """Create JWT token with expiry."""
    payload = {
        "sub": username,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc).timestamp() + settings.jwt_expire_minutes * 60,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    """Dependency: verify JWT token from Authorization header."""
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Include: Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return {"username": payload["sub"], "role": payload["role"]}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired. Please login again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=403, detail="Invalid token.")


def authenticate_user(username: str, password: str) -> dict:
    """Authenticate user against demo users."""
    user = DEMO_USERS.get(username)
    if not user or user["password"] != password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"username": username, "role": user["role"]}