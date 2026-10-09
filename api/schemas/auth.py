"""Pydantic schemas for authentication and user accounts."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    username: str = Field(..., description="Username or email")
    password: str = Field(..., description="Plaintext password")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    full_name: str
    role: str
    role_id: int


class UserProfileResponse(BaseModel):
    id: int
    role_id: int
    role_name: str
    employee_id: str | None = None
    username: str
    full_name: str
    email: str
    phone: str | None = None
    is_active: bool
    created_at: str | None = None


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str
