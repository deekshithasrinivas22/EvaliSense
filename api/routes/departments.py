"""Departments management routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_hod
from api.database.models import Department, User
from api.database.session import get_db
from api.schemas.academic import DepartmentCreate, DepartmentResponse, DepartmentUpdate

router = APIRouter(prefix="/api/departments", tags=["Departments"])


@router.get("", response_model=list[DepartmentResponse])
def list_departments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all departments."""
    depts = db.query(Department).all()
    return [DepartmentResponse(**d.to_dict()) for d in depts]


@router.post("", response_model=DepartmentResponse)
def create_department(
    req: DepartmentCreate,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Create a new department (HOD only)."""
    code = req.code.strip().upper()
    if db.query(Department).filter(Department.code == code).first():
        raise HTTPException(status_code=400, detail=f"Department code '{code}' already exists.")

    dept = Department(name=req.name.strip(), code=code, is_active=True)
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return DepartmentResponse(**dept.to_dict())


@router.put("/{dept_id}", response_model=DepartmentResponse)
def update_department(
    dept_id: int,
    req: DepartmentUpdate,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Update department (HOD only)."""
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found.")

    if req.name is not None:
        dept.name = req.name.strip()
    if req.code is not None:
        code = req.code.strip().upper()
        existing = db.query(Department).filter(Department.code == code, Department.id != dept_id).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Department code '{code}' is already used.")
        dept.code = code
    if req.is_active is not None:
        dept.is_active = req.is_active

    db.commit()
    db.refresh(dept)
    return DepartmentResponse(**dept.to_dict())


@router.delete("/{dept_id}")
def delete_department(
    dept_id: int,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Deactivate or remove department (HOD only)."""
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found.")

    dept.is_active = False
    db.commit()
    return {"message": f"Department '{dept.code}' deactivated."}
