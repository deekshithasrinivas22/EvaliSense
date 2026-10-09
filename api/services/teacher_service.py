"""Teacher workflow and workload-balancing service for EvaliSense.

Implements:
- Workload-balanced assignment of risky/high-risk answers to eligible subject teachers
- Teacher review verification and final mark recording
- Status updating for answers and parent answer scripts
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from api.database.models import (
    AnswerAnswer,
    AnswerScript,
    Exam,
    FinalMark,
    TeacherAssignment,
    TeacherSubject,
    User,
)
from api.services.notification_service import create_notification
from utils.logging import get_logger

logger = get_logger(__name__)


def get_eligible_teachers_for_exam(db: Session, exam: Exam) -> list[User]:
    """Retrieve all active teachers assigned to the exam's subject."""
    query = (
        db.query(User)
        .join(TeacherSubject, TeacherSubject.teacher_id == User.id)
        .filter(
            TeacherSubject.subject_id == exam.subject_id,
            TeacherSubject.is_active.is_(True),
            User.is_active.is_(True),
        )
    )

    # If section is set on the exam and teachers have section-specific mapping, filter if present
    teachers = query.all()
    # Unique teachers
    unique_teachers = {t.id: t for t in teachers}
    return list(unique_teachers.values())


def get_teacher_workloads(db: Session, teacher_ids: list[int]) -> dict[int, int]:
    """Count pending assignments (ASSIGNED or IN_REVIEW) for each teacher."""
    workloads: dict[int, int] = {tid: 0 for tid in teacher_ids}
    if not teacher_ids:
        return workloads

    assignments = (
        db.query(TeacherAssignment)
        .filter(
            TeacherAssignment.teacher_id.in_(teacher_ids),
            TeacherAssignment.assignment_status.in_(["ASSIGNED", "IN_REVIEW"]),
        )
        .all()
    )
    for a in assignments:
        workloads[a.teacher_id] = workloads.get(a.teacher_id, 0) + 1

    return workloads


def auto_assign_risky_answers(db: Session, exam_id: int | None = None) -> int:
    """Assign unassigned HIGH_RISK answers to eligible subject teachers using min-workload balancing."""
    # Find answers that need assignment
    query = (
        db.query(AnswerAnswer)
        .join(AnswerScript, AnswerScript.id == AnswerAnswer.script_id)
        .filter(AnswerAnswer.status == "HIGH_RISK")
    )
    if exam_id:
        query = query.filter(AnswerScript.exam_id == exam_id)

    risky_answers = query.all()
    assigned_count = 0

    for answer in risky_answers:
        # Check if already assigned
        active_assignment = (
            db.query(TeacherAssignment)
            .filter(
                TeacherAssignment.answer_id == answer.id,
                TeacherAssignment.assignment_status.in_(["ASSIGNED", "IN_REVIEW"]),
            )
            .first()
        )
        if active_assignment:
            continue

        exam = answer.script.exam if answer.script else None
        if not exam:
            continue

        eligible_teachers = get_eligible_teachers_for_exam(db, exam)
        if not eligible_teachers:
            logger.warning(
                "No eligible teachers found for exam '%s' (subject_id=%s) to assign answer #%d",
                exam.name,
                exam.subject_id,
                answer.id,
            )
            continue

        workloads = get_teacher_workloads(db, [t.id for t in eligible_teachers])

        # Pick teacher with minimum workload
        best_teacher = min(eligible_teachers, key=lambda t: (workloads.get(t.id, 0), t.id))

        assignment = TeacherAssignment(
            answer_id=answer.id,
            teacher_id=best_teacher.id,
            assignment_status="ASSIGNED",
            assigned_at=datetime.utcnow(),
        )
        db.add(assignment)
        answer.status = "TEACHER_REVIEW"
        db.flush()

        assigned_count += 1

        # Notify teacher
        create_notification(
            db=db,
            user_id=best_teacher.id,
            type="ASSIGNMENT_NEW",
            title="New Risky Answer Assigned",
            message=f"You have been assigned to review high-risk answer #{answer.id} for {exam.name}.",
            reference_type="teacher_assignment",
            reference_id=assignment.id,
        )

    db.commit()
    return assigned_count


def submit_teacher_review(
    db: Session,
    assignment_id: int,
    teacher: User,
    final_mark: float,
    teacher_notes: str | None = None,
    decision: str = "MODIFIED",
) -> FinalMark:
    """Submit teacher's review and finalize the mark for an assigned answer."""
    assignment = (
        db.query(TeacherAssignment)
        .filter(TeacherAssignment.id == assignment_id)
        .first()
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="Teacher assignment not found.")

    # Authorization: Ensure teacher owns this assignment, unless user is HOD
    user_role = teacher.role.name if teacher.role else ""
    if assignment.teacher_id != teacher.id and user_role != "HOD":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You can only review assignments assigned to you.",
        )

    answer = db.query(AnswerAnswer).filter(AnswerAnswer.id == assignment.answer_id).first()
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found.")

    # Max mark check
    max_mark = answer.question.max_marks if answer.question else 100.0
    if final_mark < 0 or final_mark > max_mark:
        raise HTTPException(
            status_code=400,
            detail=f"Final mark must be between 0 and {max_mark}.",
        )

    # Save or update final mark
    final_mark_rec = db.query(FinalMark).filter(FinalMark.answer_id == answer.id).first()
    if not final_mark_rec:
        final_mark_rec = FinalMark(
            answer_id=answer.id,
            teacher_id=teacher.id,
            final_mark=round(final_mark, 2),
            teacher_notes=teacher_notes,
            decision=decision,
            reviewed_at=datetime.utcnow(),
        )
        db.add(final_mark_rec)
    else:
        final_mark_rec.teacher_id = teacher.id
        final_mark_rec.final_mark = round(final_mark, 2)
        final_mark_rec.teacher_notes = teacher_notes
        final_mark_rec.decision = decision
        final_mark_rec.reviewed_at = datetime.utcnow()

    assignment.assignment_status = "COMPLETED"
    assignment.reviewed_at = datetime.utcnow()
    answer.status = "FINALIZED"
    db.flush()

    # Check parent script: if all answers finalized or low_risk, mark script COMPLETED
    script = answer.script
    if script:
        all_done = True
        for a in script.answers:
            if a.status in ["PROCESSING", "HIGH_RISK", "TEACHER_REVIEW"]:
                all_done = False
                break
        if all_done:
            script.status = "COMPLETED"

    db.commit()
    db.refresh(final_mark_rec)

    logger.info(
        "Teacher %s reviewed assignment #%d: final mark %.2f (decision: %s)",
        teacher.username,
        assignment_id,
        final_mark,
        decision,
    )
    return final_mark_rec
