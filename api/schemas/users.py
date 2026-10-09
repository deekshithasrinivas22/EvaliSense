"""Pydantic schemas for Roles and Users."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RoleCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    description: str | None = None


class RoleUpdate(BaseModel):
    description: str | None = None
    is_active: bool | None = None


class RoleResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_system_role: bool
    is_active: bool
    created_at: str | None = None


class UserCreate(BaseModel):
    role_id: int
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., min_length=3, max_length=120)
    employee_id: str | None = None
    phone: str | None = None


class UserUpdate(BaseModel):
    role_id: int | None = None
    full_name: str | None = None
    email: str | None = None
    employee_id: str | None = None
    phone: str | None = None
    is_active: bool | None = None
    password: str | None = None


class UserResponse(BaseModel):
    id: int
    role_id: int
    role_name: str | None = None
    employee_id: str | None = None
    username: str
    full_name: str
    email: str
    phone: str | None = None
    is_active: bool
    created_at: str | None = None
