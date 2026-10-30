"""Authentication and security utilities for EvaliSense.

Implements:
- Argon2 password hashing and verification
- JWT token creation and validation
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

from config import config

_hasher = PasswordHasher()
_firebase_keys = jwt.PyJWKClient(
    'https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com',
    cache_keys=True, timeout=5,
)


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using Argon2."""
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against an Argon2 hash."""
    try:
        return _hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError):
        return False


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=config.jwt_expire_minutes)

    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    encoded_jwt = jwt.encode(to_encode, config.jwt_secret, algorithm=config.jwt_algorithm)
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT access token (supports local JWT and Firebase Auth tokens)."""
    # 1. Try local application secret
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=[config.jwt_algorithm])
        return payload
    except Exception:
        pass

    # 2. Firebase identity is trusted only after signature, audience, issuer and
    # expiry verification. An unverified payload must never authorize a user.
    try:
        if jwt.get_unverified_header(token).get('alg') != 'RS256':
            return None
        key = _firebase_keys.get_signing_key_from_jwt(token).key
        verified = jwt.decode(token, key, algorithms=['RS256'], audience='evalisense',
                              issuer='https://securetoken.google.com/evalisense',
                              options={'require': ['exp', 'iat', 'sub']})
        if not verified.get('email_verified'):
            return None
        return {**verified, 'is_firebase': True}
    except Exception:
        return None
