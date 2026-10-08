"""Evaluation and risky answer management routes."""
from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_hod
from api.database.models import (
    AIEvaluation,
    AnswerAnswer,
    ExamQuestion,
    FinalMark,
    TeacherAssignment,
    User,
)
from api.database.session import get_db
from api.services.teacher_service import auto_assign_risky_answers

router = APIRouter(prefix="/api/evaluations", tags=["Evaluations"])


@router.get("/risky")
def list_risky_evaluations(
    exam_id: int | None = Query(None, description="Filter by exam ID"),
    unassigned_only: bool = Query(False, description="Filter unassigned only"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List evaluations classified as HIGH risk (HOD or Teacher)."""
    query = (
        db.query(AnswerAnswer)
        .join(AIEvaluation, AIEvaluation.answer_id == AnswerAnswer.id)
        .filter(AIEvaluation.risk_label == "HIGH")
    )

    if exam_id is not None:
        query = query.filter(AnswerAnswer.script.has(exam_id=exam_id))

    if unassigned_only:
        query = query.filter(~AnswerAnswer.teacher_assignment.has())

    answers = query.all()
    results = []
    for a in answers:
        eval_dict = a.ai_evaluation.to_dict() if a.ai_evaluation else {}
        assignment_dict = a.teacher_assignment.to_dict() if a.teacher_assignment else None
        results.append({
            "answer_id": a.id,
            "script_id": a.script_id,
            "question_id": a.question_id,
            "question_number": a.question.question_number if a.question else None,
            "question_text": a.question.question_text if a.question else None,
            "max_marks": a.question.max_marks if a.question else 0.0,
            "extracted_text": a.extracted_text,
            "ocr_confidence": a.ocr_confidence,
            "status": a.status,
            "ai_evaluation": eval_dict,
            "assignment": assignment_dict,
        })
    return results


@router.get("/{answer_id}")
def get_evaluation_detail(
    answer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get full evaluation detail for an individual answer."""
    answer = db.query(AnswerAnswer).filter(AnswerAnswer.id == answer_id).first()
    if not answer:
        raise HTTPException(status_code=404, detail="Answer record not found.")

    q = answer.question
    rubric = json.loads(q.rubric_json) if q and q.rubric_json else {}

    return {
        "answer_id": answer.id,
        "script_id": answer.script_id,
        "image_path": f"/api/scripts/{answer.script_id}/image",
        "question_number": q.question_number if q else None,
        "question_text": q.question_text if q else None,
        "reference_answer": q.reference_answer if q else None,
        "max_marks": q.max_marks if q else 0.0,
        "rubric": rubric,
        "extracted_text": answer.extracted_text,
        "ocr_confidence": answer.ocr_confidence,
        "status": answer.status,
        "ai_evaluation": answer.ai_evaluation.to_dict() if answer.ai_evaluation else None,
        "teacher_assignment": answer.teacher_assignment.to_dict() if answer.teacher_assignment else None,
        "final_mark": answer.final_mark.to_dict() if answer.final_mark else None,
    }


@router.post("/auto-assign")
def trigger_auto_assignment(
    exam_id: int | None = Query(None, description="Optional exam ID filter"),
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Trigger workload-balanced assignment of pending risky answers (HOD only)."""
    assigned_count = auto_assign_risky_answers(db, exam_id=exam_id)
    return {"message": f"Successfully assigned {assigned_count} risky answers across teachers."}
