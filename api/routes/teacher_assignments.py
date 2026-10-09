"""Teacher subject assignments management routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_hod
from api.database.models import Section, Subject, TeacherSubject, User
from api.database.session import get_db
from api.schemas.academic import TeacherSubjectCreate, TeacherSubjectResponse

router = APIRouter(prefix="/api/teacher-subjects", tags=["Teacher Subjects"])


@router.get("", response_model=list[TeacherSubjectResponse])
def list_teacher_subjects(
    teacher_id: int | None = Query(None, description="Filter by teacher ID"),
    subject_id: int | None = Query(None, description="Filter by subject ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List teacher-subject mappings."""
    query = db.query(TeacherSubject).filter(TeacherSubject.is_active.is_(True))
    if teacher_id is not None:
        query = query.filter(TeacherSubject.teacher_id == teacher_id)
    if subject_id is not None:
        query = query.filter(TeacherSubject.subject_id == subject_id)
    mappings = query.all()
    return [TeacherSubjectResponse(**m.to_dict()) for m in mappings]


@router.post("", response_model=TeacherSubjectResponse)
def assign_teacher_subject(
    req: TeacherSubjectCreate,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Map a teacher to a subject and section (HOD only)."""
    teacher = db.query(User).filter(User.id == req.teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=400, detail="Teacher not found.")

    subject = db.query(Subject).filter(Subject.id == req.subject_id).first()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject not found.")

    if req.section_id:
        section = db.query(Section).filter(Section.id == req.section_id).first()
        if not section:
            raise HTTPException(status_code=400, detail="Section not found.")

    existing = db.query(TeacherSubject).filter(
        TeacherSubject.teacher_id == req.teacher_id,
        TeacherSubject.subject_id == req.subject_id,
        TeacherSubject.section_id == req.section_id,
        TeacherSubject.academic_year == req.academic_year,
        TeacherSubject.is_active.is_(True),
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Mapping already exists.")

    mapping = TeacherSubject(
        teacher_id=req.teacher_id,
        subject_id=req.subject_id,
        section_id=req.section_id,
        academic_year=req.academic_year,
        is_active=True,
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return TeacherSubjectResponse(**mapping.to_dict())


@router.delete("/{mapping_id}")
def delete_teacher_subject(
    mapping_id: int,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Remove a teacher-subject mapping (HOD only)."""
    mapping = db.query(TeacherSubject).filter(TeacherSubject.id == mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found.")

    mapping.is_active = False
    db.commit()
    return {"message": "Teacher-subject mapping removed."}
