"""Examinations management routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_hod
from api.database.models import Exam, Section, Subject, User
from api.database.session import get_db
from api.schemas.academic import ExamCreate, ExamResponse, ExamUpdate

router = APIRouter(prefix="/api/exams", tags=["Examinations"])


@router.get("", response_model=list[ExamResponse])
def list_exams(
    subject_id: int | None = Query(None, description="Filter by subject"),
    section_id: int | None = Query(None, description="Filter by section"),
    status: str | None = Query(None, description="Filter by status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all examinations."""
    query = db.query(Exam)
    if subject_id is not None:
        query = query.filter(Exam.subject_id == subject_id)
    if section_id is not None:
        query = query.filter(Exam.section_id == section_id)
    if status is not None:
        query = query.filter(Exam.status == status)
    exams = query.order_by(Exam.created_at.desc()).all()
    return [ExamResponse(**e.to_dict()) for e in exams]


@router.post("", response_model=ExamResponse)
def create_exam(
    req: ExamCreate,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Create a new examination (HOD only)."""
    subject = db.query(Subject).filter(Subject.id == req.subject_id).first()
    if not subject:
        raise HTTPException(status_code=400, detail="Invalid subject ID.")

    if req.section_id:
        section = db.query(Section).filter(Section.id == req.section_id).first()
        if not section:
            raise HTTPException(status_code=400, detail="Invalid section ID.")

    exam = Exam(
        subject_id=req.subject_id,
        section_id=req.section_id,
        name=req.name.strip(),
        exam_type=req.exam_type,
        exam_date=req.exam_date,
        academic_year=req.academic_year.strip(),
        total_marks=req.total_marks,
        status="SCHEDULED",
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return ExamResponse(**exam.to_dict())


@router.get("/{exam_id}", response_model=ExamResponse)
def get_exam(
    exam_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get exam details by ID."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")
    return ExamResponse(**exam.to_dict())


@router.put("/{exam_id}", response_model=ExamResponse)
def update_exam(
    exam_id: int,
    req: ExamUpdate,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Update exam details (HOD only)."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    if req.name is not None:
        exam.name = req.name.strip()
    if req.exam_type is not None:
        exam.exam_type = req.exam_type
    if req.exam_date is not None:
        exam.exam_date = req.exam_date
    if req.academic_year is not None:
        exam.academic_year = req.academic_year.strip()
    if req.total_marks is not None:
        exam.total_marks = req.total_marks
    if req.status is not None:
        exam.status = req.status

    db.commit()
    db.refresh(exam)
    return ExamResponse(**exam.to_dict())


@router.delete("/{exam_id}")
def delete_exam(
    exam_id: int,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Delete an exam if no scripts have been submitted (HOD only)."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    if exam.answer_scripts:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete exam: answer scripts have already been uploaded for this exam.",
        )

    db.delete(exam)
    db.commit()
    return {"message": f"Exam '{exam.name}' deleted successfully."}
