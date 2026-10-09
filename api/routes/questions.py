"""Exam questions and rubrics management routes."""
from __future__ import annotations

import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_teacher_or_hod
from api.database.models import Exam, ExamQuestion, User
from api.database.session import get_db
from api.schemas.academic import ExamQuestionCreate, ExamQuestionResponse, ExamQuestionUpdate
from api.services.answer_key_service import check_exam_authorization

router = APIRouter(tags=["Questions & Rubrics"])


@router.get("/api/exams/{exam_id}/questions", response_model=list[ExamQuestionResponse])
def list_exam_questions(
    exam_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List questions and rubrics for an exam."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    questions = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.exam_id == exam_id)
        .order_by(ExamQuestion.question_number)
        .all()
    )
    return [ExamQuestionResponse(**q.to_dict()) for q in questions]


@router.post("/api/exams/{exam_id}/questions", response_model=ExamQuestionResponse)
def create_exam_question(
    exam_id: int,
    req: ExamQuestionCreate,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Add a question and rubric to an exam (Assigned Teacher or HOD)."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    check_exam_authorization(db, current_user, exam)

    existing_q = (
        db.query(ExamQuestion)
        .filter(
            ExamQuestion.exam_id == exam_id,
            ExamQuestion.question_number == req.question_number,
        )
        .first()
    )
    if existing_q:
        raise HTTPException(status_code=400, detail=f"Question #{req.question_number} already exists for this exam.")

    # Validate rubric JSON if provided
    if req.rubric_json:
        try:
            from evaluation import Rubric
            r_data = json.loads(req.rubric_json)
            rubric = Rubric.from_dict(r_data)
            warnings = rubric.validate()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid rubric JSON: {exc}")

    question = ExamQuestion(
        exam_id=exam_id,
        question_number=req.question_number,
        question_text=req.question_text.strip(),
        max_marks=req.max_marks,
        reference_answer=req.reference_answer.strip() if req.reference_answer else None,
        rubric_json=req.rubric_json,
        created_at=datetime.utcnow(),
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return ExamQuestionResponse(**question.to_dict())


@router.put("/api/questions/{question_id}", response_model=ExamQuestionResponse)
def update_question(
    question_id: int,
    req: ExamQuestionUpdate,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Update question text, marks, answer key, or rubric (Assigned Teacher or HOD)."""
    question = db.query(ExamQuestion).filter(ExamQuestion.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found.")

    check_exam_authorization(db, current_user, question.exam)

    if req.question_number is not None:
        question.question_number = req.question_number
    if req.question_text is not None:
        question.question_text = req.question_text.strip()
    if req.max_marks is not None:
        question.max_marks = req.max_marks
    if req.reference_answer is not None:
        question.reference_answer = req.reference_answer.strip()
    if req.rubric_json is not None:
        try:
            json.loads(req.rubric_json)
            question.rubric_json = req.rubric_json
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid rubric JSON: {exc}")

    question.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(question)
    return ExamQuestionResponse(**question.to_dict())


@router.delete("/api/questions/{question_id}")
def delete_question(
    question_id: int,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Delete question (Assigned Teacher or HOD)."""
    question = db.query(ExamQuestion).filter(ExamQuestion.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found.")

    check_exam_authorization(db, current_user, question.exam)

    db.delete(question)
    db.commit()
    return {"message": f"Question #{question.question_number} deleted."}
