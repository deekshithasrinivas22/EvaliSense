"""Authentication API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user
from api.auth.security import create_access_token, verify_password
from api.database.models import User
from api.database.session import get_db
from api.schemas.auth import LoginRequest, TokenResponse, UserProfileResponse

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user with username or email and return JWT access token."""
    user = (
        db.query(User)
        .filter((User.username == req.username) | (User.email == req.username))
        .first()
    )

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Contact the administrator.",
        )

    token = create_access_token({
        "sub": str(user.id),
        "user_id": user.id,
        "username": user.username,
        "role": user.role.name if user.role else "USER",
        "role_id": user.role_id,
    })

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role.name if user.role else "USER",
        role_id=user.role_id,
    )


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)):
    """Log out current user."""
    return {"message": "Logged out successfully."}


@router.get("/me", response_model=UserProfileResponse)
def me(current_user: User = Depends(get_current_user)):
    """Return profile of authenticated user."""
    return UserProfileResponse(
        id=current_user.id,
        role_id=current_user.role_id,
        role_name=current_user.role.name if current_user.role else "USER",
        employee_id=current_user.employee_id,
        username=current_user.username,
        full_name=current_user.full_name,
        email=current_user.email,
        phone=current_user.phone,
        is_active=current_user.is_active,
        created_at=current_user.created_at.isoformat() if current_user.created_at else None,
    )
