"""
Supervisor authentication: bcrypt password hashes + stateless JWT bearer
tokens (same approach as Avalio's dashboard auth).
"""

import logging
import time
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import config

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
JWT_SECRET = config.JWT_SECRET
if not JWT_SECRET:
    logger.warning("⚠️ JWT_SECRET is not set — using an insecure dev fallback. Set it before deploying.")
    JWT_SECRET = "sitepay-dev-secret-do-not-use-in-production"

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_token(subject: str, role: str = "supervisor") -> str:
    now = int(time.time())
    payload = {"sub": subject, "role": role, "iat": now, "exp": now + config.JWT_EXPIRE_MINUTES * 60}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired — please sign in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session token")


def require_supervisor(credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> str:
    """Returns the signed-in supervisor_id."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Please sign in")
    payload = decode_token(credentials.credentials)
    if payload.get("role") != "supervisor":
        raise HTTPException(status_code=403, detail="Not authorised for this action")
    return payload["sub"]
