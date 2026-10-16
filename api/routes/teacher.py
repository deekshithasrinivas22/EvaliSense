"""Teacher-specific review routes."""
from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_teacher
from api.database.models import AnswerAnswer, TeacherAssignment, TeacherSubject, User
from api.database.session import get_db
from api.schemas.workflow import TeacherReviewSubmit
from api.services.teacher_service import submit_teacher_review

router = APIRouter(prefix="/api/teacher", tags=["Teacher Review"])


@router.get("/subjects")
def get_my_subjects(
    current_user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Retrieve subjects assigned to the logged-in teacher."""
    mappings = (
        db.query(TeacherSubject)
        .filter(TeacherSubject.teacher_id == current_user.id, TeacherSubject.is_active.is_(True))
        .all()
    )
    return [m.to_dict() for m in mappings]


@router.get("/assignments")
def list_teacher_assignments(
    status_filter: str | None = Query(None, alias="status", description="Filter by ASSIGNED, IN_REVIEW, COMPLETED"),
    current_user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Retrieve risky answer assignments assigned strictly to the current teacher."""
    user_role = current_user.role.name if current_user.role else ""
    query = db.query(TeacherAssignment)

    # Teachers strictly view only their own assigned reviews
    if user_role != "HOD":
        query = query.filter(TeacherAssignment.teacher_id == current_user.id)

    if status_filter:
        query = query.filter(TeacherAssignment.assignment_status == status_filter)

    assignments = query.order_by(TeacherAssignment.assigned_at.desc()).all()

    results = []
    for a in assignments:
        ans = a.answer
        q = ans.question if ans else None
        results.append({
            "assignment_id": a.id,
            "answer_id": a.answer_id,
            "assignment_status": a.assignment_status,
            "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
            "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
            "question_number": q.question_number if q else None,
            "max_marks": q.max_marks if q else 0.0,
            "ai_mark": ans.ai_evaluation.ai_mark if ans and ans.ai_evaluation else None,
            "risk_label": ans.ai_evaluation.risk_label if ans and ans.ai_evaluation else None,
            "risk_probability": ans.ai_evaluation.risk_probability if ans and ans.ai_evaluation else None,
            "final_mark": ans.final_mark.final_mark if ans and ans.final_mark else None,
        })
    return results


@router.get("/assignments/{assignment_id}")
def get_teacher_assignment_detail(
    assignment_id: int,
    current_user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Retrieve complete review view for an assigned answer with strict authorization."""
    assignment = db.query(TeacherAssignment).filter(TeacherAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found.")

    user_role = current_user.role.name if current_user.role else ""
    # Authorization: teachers can ONLY view their own assignments
    if user_role != "HOD" and assignment.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: This evaluation is not assigned to you.",
        )

    ans = assignment.answer
    if not ans:
        raise HTTPException(status_code=404, detail="Associated answer record not found.")

    q = ans.question
    rubric_obj = json.loads(q.rubric_json) if q and q.rubric_json else {}
    ai_eval = ans.ai_evaluation

    risk_factors_list = []
    if ai_eval and ai_eval.risk_factors:
        try:
            risk_factors_list = json.loads(ai_eval.risk_factors)
        except Exception:
            risk_factors_list = [ai_eval.risk_factors]

    return {
        "assignment_id": assignment.id,
        "assignment_status": assignment.assignment_status,
        "answer_id": ans.id,
        "script_id": ans.script_id,
        "image_url": f"/api/scripts/{ans.script_id}/image",
        "question": {
            "number": q.question_number if q else None,
            "text": q.question_text if q else None,
            "max_marks": q.max_marks if q else 0.0,
            "reference_answer": q.reference_answer if q else "",
            "rubric": rubric_obj,
        },
        "extracted_text": ans.extracted_text,
        "ocr_confidence": ans.ocr_confidence,
        "ai_evaluation": {
            "ai_mark": ai_eval.ai_mark if ai_eval else None,
            "max_marks": ai_eval.max_marks if ai_eval else (q.max_marks if q else 0.0),
            "semantic_similarity": ai_eval.semantic_similarity if ai_eval else None,
            "rubric_coverage": ai_eval.rubric_coverage if ai_eval else None,
            "evaluation_confidence": ai_eval.evaluation_confidence if ai_eval else None,
            "risk_label": ai_eval.risk_label if ai_eval else "UNKNOWN",
            "risk_probability": ai_eval.risk_probability if ai_eval else 0.0,
            "risk_factors": risk_factors_list,
        } if ai_eval else None,
        "final_mark": ans.final_mark.to_dict() if ans.final_mark else None,
    }


@router.post("/assignments/{assignment_id}/review")
def review_assignment(
    assignment_id: int,
    req: TeacherReviewSubmit,
    current_user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Submit final mark and teacher notes for an assigned answer."""
    final_mark_rec = submit_teacher_review(
        db=db,
        assignment_id=assignment_id,
        teacher=current_user,
        final_mark=req.final_mark,
        teacher_notes=req.teacher_notes,
        decision=req.decision,
    )
    return {
        "status": "success",
        "message": "Evaluation finalized successfully.",
        "final_mark": final_mark_rec.to_dict(),
    }
