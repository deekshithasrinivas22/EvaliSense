"""Student result calculation and aggregation service for EvaliSense.

Authoritatively resolves marks from `final_marks`, separating them from `ai_evaluations`.
Calculates per-question marks, subject totals, exam totals, percentages, and grade statistics.
"""
from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from api.database.models import (
    AIEvaluation,
    AnswerAnswer,
    AnswerScript,
    Exam,
    ExamQuestion,
    FinalMark,
    Student,
    Subject,
)


def get_student_exam_result(db: Session, student_id: int, exam_id: int) -> dict[str, Any] | None:
    """Calculate detailed examination results for a specific student."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return None

    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        return None

    scripts = (
        db.query(AnswerScript)
        .filter(
            AnswerScript.student_id == student_id,
            AnswerScript.exam_id == exam_id,
        )
        .all()
    )

    questions_results = []
    total_obtained = 0.0
    total_max = exam.total_marks or 0.0

    for q in exam.questions:
        q_ans = None
        for script in scripts:
            for ans in script.answers:
                if ans.question_id == q.id:
                    q_ans = ans
                    break
            if q_ans:
                break

        ai_mark = None
        risk_label = None
        final_mark = None
        status_str = "NOT_ATTEMPTED"
        decision = None

        if q_ans:
            status_str = q_ans.status
            if q_ans.ai_evaluation:
                ai_mark = q_ans.ai_evaluation.ai_mark
                risk_label = q_ans.ai_evaluation.risk_label
            if q_ans.final_mark:
                final_mark = q_ans.final_mark.final_mark
                decision = q_ans.final_mark.decision
                total_obtained += final_mark
            elif ai_mark is not None:
                # If finalized, use final mark; otherwise indicate pending
                pass

        questions_results.append({
            "question_number": q.question_number,
            "question_text": q.question_text,
            "max_marks": q.max_marks,
            "ai_mark": ai_mark,
            "final_mark": final_mark,
            "status": status_str,
            "risk_label": risk_label,
            "decision": decision,
        })

    pct = round((total_obtained / total_max * 100), 2) if total_max > 0 else 0.0

    return {
        "student_id": student.id,
        "student_name": student.name,
        "student_usn": student.usn,
        "exam_id": exam.id,
        "exam_name": exam.name,
        "subject_name": exam.subject.name if exam.subject else None,
        "subject_code": exam.subject.code if exam.subject else None,
        "total_obtained": round(total_obtained, 2),
        "total_max": total_max,
        "percentage": pct,
        "questions": questions_results,
    }


def get_exam_summary_results(db: Session, exam_id: int) -> dict[str, Any] | None:
    """Calculate summary and class-wide performance for an examination."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        return None

    # Get all scripts submitted for this exam
    scripts = db.query(AnswerScript).filter(AnswerScript.exam_id == exam_id).all()
    students_dict: dict[int, dict[str, Any]] = {}

    for script in scripts:
        if not script.student_id:
            continue
        student_id = script.student_id
        if student_id not in students_dict:
            res = get_student_exam_result(db, student_id, exam_id)
            if res:
                students_dict[student_id] = res

    student_results = list(students_dict.values())
    scores = [r["total_obtained"] for r in student_results]

    avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    highest_score = max(scores) if scores else 0.0
    lowest_score = min(scores) if scores else 0.0
    pass_count = sum(1 for s in scores if (s / (exam.total_marks or 1.0)) >= 0.4)
    pass_pct = round(pass_count / len(scores) * 100, 2) if scores else 0.0

    return {
        "exam_id": exam.id,
        "exam_name": exam.name,
        "subject_code": exam.subject.code if exam.subject else "",
        "subject_name": exam.subject.name if exam.subject else "",
        "total_marks": exam.total_marks,
        "total_students_evaluated": len(student_results),
        "class_average": avg_score,
        "highest_score": highest_score,
        "lowest_score": lowest_score,
        "pass_percentage": pass_pct,
        "students": sorted(student_results, key=lambda x: x["total_obtained"], reverse=True),
    }


def get_student_all_results(db: Session, student_id: int) -> dict[str, Any] | None:
    """Retrieve all exam results across subjects for a given student."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return None

    # Find exams the student took
    scripts = db.query(AnswerScript).filter(AnswerScript.student_id == student_id).all()
    exam_ids = {s.exam_id for s in scripts if s.exam_id}

    results = []
    for eid in exam_ids:
        r = get_student_exam_result(db, student_id, eid)
        if r:
            results.append(r)

    return {
        "student_id": student.id,
        "student_name": student.name,
        "student_usn": student.usn,
        "section": student.section.name if student.section else None,
        "exam_results": results,
    }
