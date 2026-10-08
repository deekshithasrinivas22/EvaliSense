"""Student, exam, and subject results routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user
from api.database.models import Exam, Student, Subject, User
from api.database.session import get_db
from api.services.result_service import (
    get_exam_summary_results,
    get_student_all_results,
    get_student_exam_result,
)

router = APIRouter(tags=["Results"])


@router.get("/api/students/{student_id}/results")
def get_student_results(
    student_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all examination results for a specific student."""
    res = get_student_all_results(db, student_id)
    if not res:
        raise HTTPException(status_code=404, detail="Student or results not found.")
    return res


@router.get("/api/exams/{exam_id}/results")
def get_exam_results(
    exam_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get complete results, class statistics, and student marks for an exam."""
    res = get_exam_summary_results(db, exam_id)
    if not res:
        raise HTTPException(status_code=404, detail="Exam results not found.")
    return res


@router.get("/api/exams/{exam_id}/students/{student_id}/results")
def get_student_single_exam_result(
    exam_id: int,
    student_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get marks breakdown for a student in a specific exam."""
    res = get_student_exam_result(db, student_id, exam_id)
    if not res:
        raise HTTPException(status_code=404, detail="Result breakdown not found.")
    return res
