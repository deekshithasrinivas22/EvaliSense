"""Subjects management routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_hod
from api.database.models import Department, Subject, User
from api.database.session import get_db
from api.schemas.academic import SubjectCreate, SubjectResponse, SubjectUpdate

router = APIRouter(prefix="/api/subjects", tags=["Subjects"])


@router.get("", response_model=list[SubjectResponse])
def list_subjects(
    department_id: int | None = Query(None, description="Filter by department ID"),
    semester: int | None = Query(None, description="Filter by semester"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all subjects."""
    query = db.query(Subject)
    if department_id is not None:
        query = query.filter(Subject.department_id == department_id)
    if semester is not None:
        query = query.filter(Subject.semester == semester)
    subjects = query.order_by(Subject.code).all()
    return [SubjectResponse(**s.to_dict()) for s in subjects]


@router.post("", response_model=SubjectResponse)
def create_subject(
    req: SubjectCreate,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Create a new subject (HOD only)."""
    code = req.code.strip().upper()
    if db.query(Subject).filter(Subject.code == code).first():
        raise HTTPException(status_code=400, detail=f"Subject code '{code}' already exists.")

    dept = db.query(Department).filter(Department.id == req.department_id).first()
    if not dept:
        raise HTTPException(status_code=400, detail="Invalid department ID.")

    subject = Subject(
        code=code,
        name=req.name.strip(),
        semester=req.semester,
        department_id=dept.id,
        max_marks=req.max_marks,
        is_active=True,
    )
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return SubjectResponse(**subject.to_dict())


@router.get("/{subject_id}", response_model=SubjectResponse)
def get_subject(
    subject_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get subject by ID."""
    sub = db.query(Subject).filter(Subject.id == subject_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subject not found.")
    return SubjectResponse(**sub.to_dict())


@router.put("/{subject_id}", response_model=SubjectResponse)
def update_subject(
    subject_id: int,
    req: SubjectUpdate,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Update subject details (HOD only)."""
    sub = db.query(Subject).filter(Subject.id == subject_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subject not found.")

    if req.name is not None:
        sub.name = req.name.strip()
    if req.semester is not None:
        sub.semester = req.semester
    if req.department_id is not None:
        dept = db.query(Department).filter(Department.id == req.department_id).first()
        if not dept:
            raise HTTPException(status_code=400, detail="Invalid department specified.")
        sub.department_id = req.department_id
    if req.max_marks is not None:
        sub.max_marks = req.max_marks
    if req.is_active is not None:
        sub.is_active = req.is_active

    db.commit()
    db.refresh(sub)
    return SubjectResponse(**sub.to_dict())


@router.delete("/{subject_id}")
def delete_subject(
    subject_id: int,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Deactivate subject (HOD only)."""
    sub = db.query(Subject).filter(Subject.id == subject_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subject not found.")

    sub.is_active = False
    db.commit()
    return {"message": f"Subject '{sub.code}' deactivated."}
