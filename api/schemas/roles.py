"""Pydantic schemas for Roles."""
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
