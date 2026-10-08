"""Roles management routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_hod
from api.database.models import Role, User
from api.database.session import get_db
from api.schemas.roles import RoleCreate, RoleResponse, RoleUpdate

router = APIRouter(prefix="/api/roles", tags=["Roles"])


@router.get("", response_model=list[RoleResponse])
def list_roles(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all system and custom roles."""
    roles = db.query(Role).all()
    return [RoleResponse(**r.to_dict()) for r in roles]


@router.post("", response_model=RoleResponse)
def create_role(
    req: RoleCreate,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Create a new custom role (HOD only)."""
    existing = db.query(Role).filter(Role.name == req.name.strip().upper()).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Role '{req.name}' already exists.")

    role = Role(
        name=req.name.strip().upper(),
        description=req.description,
        is_system_role=False,
        is_active=True,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return RoleResponse(**role.to_dict())


@router.put("/{role_id}", response_model=RoleResponse)
def update_role(
    role_id: int,
    req: RoleUpdate,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Update role details (HOD only)."""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found.")

    if req.description is not None:
        role.description = req.description
    if req.is_active is not None:
        if role.is_system_role and not req.is_active:
            raise HTTPException(status_code=400, detail="System-critical roles cannot be deactivated.")
        role.is_active = req.is_active

    db.commit()
    db.refresh(role)
    return RoleResponse(**role.to_dict())


@router.delete("/{role_id}")
def delete_role(
    role_id: int,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Delete a custom role if no users reference it (HOD only)."""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found.")

    if role.is_system_role:
        raise HTTPException(status_code=400, detail="System-critical roles cannot be deleted.")

    user_count = db.query(User).filter(User.role_id == role.id).count()
    if user_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete role: {user_count} users are currently assigned to this role.",
        )

    db.delete(role)
    db.commit()
    return {"message": f"Role '{role.name}' deleted successfully."}
