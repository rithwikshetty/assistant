from fastapi import HTTPException, status
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import secrets
import hashlib
from ..config.settings import settings


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def verify_token(token: str) -> dict:
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def create_refresh_token() -> Tuple[str, str, datetime]:
    """
    Create a new refresh token.

    Returns:
        Tuple of (raw_token, token_hash, expires_at)
        - raw_token: Send to client (store securely)
        - token_hash: Store in database
        - expires_at: Expiration timestamp
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    return raw_token, token_hash, expires_at


def hash_refresh_token(raw_token: str) -> str:
    """Hash a raw refresh token for database lookup."""
    return hashlib.sha256(raw_token.encode()).hexdigest()