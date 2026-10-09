"""System analytics and HOD dashboard overview metrics."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.dependencies import require_hod
from api.database.models import (
    AIEvaluation,
    AnswerScript,
    Exam,
    Role,
    ScanIssue,
    Student,
    Subject,
    TeacherAssignment,
    User,
)
from api.database.session import get_db

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


@router.get("/overview")
def get_hod_overview_metrics(
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Retrieve comprehensive system metrics for the HOD dashboard."""
    # Count roles
    teacher_role = db.query(Role).filter(Role.name == "TEACHER").first()
    scanner_role = db.query(Role).filter(Role.name == "SCANNER").first()

    total_teachers = (
        db.query(User).filter(User.role_id == teacher_role.id).count() if teacher_role else 0
    )
    total_scanners = (
        db.query(User).filter(User.role_id == scanner_role.id).count() if scanner_role else 0
    )
    total_students = db.query(Student).count()
    active_subjects = db.query(Subject).filter(Subject.is_active.is_(True)).count()
    active_exams = db.query(Exam).count()

    scripts_uploaded = db.query(AnswerScript).count()
    scripts_processed = (
        db.query(AnswerScript)
        .filter(AnswerScript.status.in_(["OCR_COMPLETED", "AI_EVALUATED", "RISK_REVIEW", "COMPLETED"]))
        .count()
    )
    scripts_rescan_required = (
        db.query(AnswerScript).filter(AnswerScript.status == "REUPLOAD_REQUIRED").count()
    )

    high_risk_answers = (
        db.query(AIEvaluation).filter(AIEvaluation.risk_label == "HIGH").count()
    )
    pending_teacher_reviews = (
        db.query(TeacherAssignment)
        .filter(TeacherAssignment.assignment_status.in_(["ASSIGNED", "IN_REVIEW"]))
        .count()
    )
    completed_reviews = (
        db.query(TeacherAssignment)
        .filter(TeacherAssignment.assignment_status == "COMPLETED")
        .count()
    )

    # Teacher workloads list
    teacher_users = (
        db.query(User).filter(User.role_id == teacher_role.id).all() if teacher_role else []
    )
    teacher_workloads = []
    for t in teacher_users:
        pending = (
            db.query(TeacherAssignment)
            .filter(
                TeacherAssignment.teacher_id == t.id,
                TeacherAssignment.assignment_status.in_(["ASSIGNED", "IN_REVIEW"]),
            )
            .count()
        )
        completed = (
            db.query(TeacherAssignment)
            .filter(
                TeacherAssignment.teacher_id == t.id,
                TeacherAssignment.assignment_status == "COMPLETED",
            )
            .count()
        )
        teacher_workloads.append({
            "teacher_id": t.id,
            "teacher_name": t.full_name,
            "username": t.username,
            "pending_count": pending,
            "completed_count": completed,
        })

    return {
        "total_students": total_students,
        "total_teachers": total_teachers,
        "total_scanners": total_scanners,
        "active_subjects": active_subjects,
        "active_examinations": active_exams,
        "scripts_uploaded": scripts_uploaded,
        "scripts_processed": scripts_processed,
        "scripts_requiring_rescan": scripts_rescan_required,
        "high_risk_answers": high_risk_answers,
        "pending_teacher_reviews": pending_teacher_reviews,
        "completed_reviews": completed_reviews,
        "teacher_workloads": teacher_workloads,
    }
