"""FastAPI dependencies for authentication and role-based access control (RBAC)."""
from __future__ import annotations

from typing import Callable
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from api.auth.security import decode_access_token
from api.database.models import User
from api.database.session import get_db

security_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(security_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Validate Bearer token and return the authenticated User."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub") or payload.get("user_id")
    email = payload.get("email")
    if not user_id and not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is missing subject.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = None
    if user_id:
        try:
            user = db.query(User).filter(User.id == int(user_id)).first()
        except (ValueError, TypeError):
            pass

    if not user and email:
        user = db.query(User).filter(User.email == email).first()

    if not user and user_id:
        user = db.query(User).filter(User.username == str(user_id)).first()

    if not user:
        # Fallback: if email matches demo accounts, map to seeded users
        if email == "hod@evalisense.edu" or user_id == "admin":
            user = db.query(User).filter(User.username == "admin").first()
        elif email == "teacher@evalisense.edu" or user_id in ("teacher1", "teacher"):
            user = db.query(User).filter(User.username == "teacher1").first()
        elif email == "scanner@evalisense.edu" or user_id in ("scanner1", "scanner"):
            user = db.query(User).filter(User.username == "scanner1").first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    return user


async def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(security_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """Return authenticated User if token is present and valid, otherwise None."""
    if not credentials:
        return None
    payload = decode_access_token(credentials.credentials)
    if not payload:
        return None
    user_id = payload.get("sub") or payload.get("user_id")
    email = payload.get("email")
    user = None
    if user_id:
        try:
            user = db.query(User).filter(User.id == int(user_id)).first()
        except (ValueError, TypeError):
            pass
    if not user and email:
        user = db.query(User).filter(User.email == email).first()
    if not user and user_id:
        user = db.query(User).filter(User.username == str(user_id)).first()
    if not user or not user.is_active:
        return None
    return user


def require_roles(allowed_roles: list[str]) -> Callable:
    """Reusable RBAC dependency requiring user to have one of the allowed roles."""
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_role = current_user.role.name if current_user.role else ""
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Requires one of roles: {', '.join(allowed_roles)}.",
            )
        return current_user
    return role_checker


# Role-specific dependency shortcuts
require_hod = require_roles(["HOD"])
require_teacher = require_roles(["TEACHER", "HOD"])
require_scanner = require_roles(["SCANNER", "HOD"])
