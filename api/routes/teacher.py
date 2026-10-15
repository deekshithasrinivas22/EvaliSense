"""Teacher-specific review, subject, and answer key management routes."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_teacher, require_teacher_or_hod
from api.database.models import (
    AnswerAnswer,
    AnswerKeyFile,
    Exam,
    ExamQuestion,
    QuestionPaperFile,
    TeacherAssignment,
    TeacherSubject,
    User,
)
from api.database.session import get_db
from api.schemas.academic import ConfirmQuestionsRequest, ExamQuestionResponse
from api.schemas.workflow import TeacherReviewSubmit
from api.services.answer_key_service import (
    activate_answer_key_version,
    archive_answer_key_version,
    check_exam_authorization,
    delete_answer_key_version,
    get_exam_answer_key_info,
    restore_answer_key_version,
    save_and_register_answer_key,
)
from api.services.question_extraction_service import (
    apply_bulk_marks_to_questions,
    extract_text_from_document,
    parse_questions_from_text,
    validate_question_paper_file,
)
from api.services.question_paper_service import (
    activate_question_paper_version,
    archive_question_paper_version,
    delete_question_paper_version,
    get_exam_question_papers_info,
    restore_question_paper_version,
    save_and_register_question_paper,
)
from api.services.teacher_service import submit_teacher_review
from config import config

router = APIRouter(prefix="/api/teacher", tags=["Teacher Operations"])


@router.get("/subjects")
def get_my_subjects(
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Retrieve subjects assigned to the logged-in teacher (or all for HOD)."""
    user_role = current_user.role.name if current_user.role else ""
    if user_role == "HOD":
        mappings = db.query(TeacherSubject).filter(TeacherSubject.is_active.is_(True)).all()
    else:
        mappings = (
            db.query(TeacherSubject)
            .filter(TeacherSubject.teacher_id == current_user.id, TeacherSubject.is_active.is_(True))
            .all()
        )
    return [m.to_dict() for m in mappings]


@router.get("/exams")
def get_my_exams(
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Retrieve exams for subjects assigned to the teacher (or all for HOD)."""
    user_role = current_user.role.name if current_user.role else ""
    if user_role == "HOD":
        exams = db.query(Exam).order_by(Exam.created_at.desc()).all()
    else:
        assigned_subject_ids = [
            m.subject_id
            for m in db.query(TeacherSubject)
            .filter(TeacherSubject.teacher_id == current_user.id, TeacherSubject.is_active.is_(True))
            .all()
        ]
        exams = (
            db.query(Exam)
            .filter(Exam.subject_id.in_(assigned_subject_ids))
            .order_by(Exam.created_at.desc())
            .all()
        )
    return [e.to_dict() for e in exams]


# ─── Answer Key & Marking Scheme Workflow ───

@router.get("/exams/{exam_id}/answer-key")
def get_answer_key(
    exam_id: int,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Retrieve active answer key, version history, and questions for an exam."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    check_exam_authorization(db, current_user, exam)
    return get_exam_answer_key_info(db, exam_id)


@router.post("/exams/{exam_id}/answer-key")
def upload_answer_key(
    exam_id: int,
    file: UploadFile | None = File(None),
    questions_json: str | None = Form(None),
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Upload or replace official answer key and configure marking scheme for an exam."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    check_exam_authorization(db, current_user, exam)

    key_record = save_and_register_answer_key(
        db=db,
        exam=exam,
        user=current_user,
        file=file,
        questions_json=questions_json,
    )
    return {
        "status": "success",
        "message": f"Answer key version v{key_record.version} uploaded successfully.",
        "version": key_record.version,
        "answer_key": key_record.to_dict(),
    }


@router.put("/exams/{exam_id}/answer-key/{key_id}")
@router.post("/exams/{exam_id}/answer-keys/{key_id}/activate")
def update_active_answer_key_version(
    exam_id: int,
    key_id: int,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Set a specific answer key version as active."""
    key_record = activate_answer_key_version(db, exam_id, key_id, user=current_user)
    return {
        "status": "success",
        "message": f"Version v{key_record.version} marked as active.",
        "answer_key": key_record.to_dict(),
    }


@router.post("/exams/{exam_id}/answer-keys/{key_id}/archive")
def archive_answer_key(
    exam_id: int,
    key_id: int,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Archive an answer key version without deleting historical evaluation records."""
    key_record = archive_answer_key_version(db, exam_id, key_id, user=current_user)
    return {
        "status": "success",
        "message": f"Answer key v{key_record.version} archived successfully.",
        "answer_key": key_record.to_dict(),
    }


@router.post("/exams/{exam_id}/answer-keys/{key_id}/restore")
def restore_answer_key(
    exam_id: int,
    key_id: int,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Restore an archived answer key version and set it active."""
    key_record = restore_answer_key_version(db, exam_id, key_id, user=current_user)
    return {
        "status": "success",
        "message": f"Answer key v{key_record.version} restored and activated.",
        "answer_key": key_record.to_dict(),
    }


@router.delete("/exams/{exam_id}/answer-keys/{key_id}")
def delete_answer_key(
    exam_id: int,
    key_id: int,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Delete an answer key version (safeguarded against deleting if evaluations exist)."""
    return delete_answer_key_version(db, exam_id, key_id, user=current_user)


# ─── Question Paper Document & Version Management ───

@router.get("/exams/{exam_id}/question-papers")
def list_exam_question_papers(
    exam_id: int,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Retrieve all question paper versions and active status for an examination."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")
    check_exam_authorization(db, current_user, exam)
    return get_exam_question_papers_info(db, exam_id)


@router.post("/exams/{exam_id}/upload-question-paper")
def upload_and_extract_question_paper(
    exam_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Upload a question paper (PDF, PNG, JPG, JPEG, TXT), extract text, segment questions, and register version."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    check_exam_authorization(db, current_user, exam)

    content = file.file.read()
    file.file.seek(0)

    is_valid, val_msg, meta = validate_question_paper_file(file, content)
    if not is_valid:
        raise HTTPException(status_code=400, detail=val_msg)

    ext = meta.get("extension", ".pdf")

    # Extract text and parse questions
    try:
        raw_text, page_records, extraction_warnings = extract_text_from_document(file, content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to extract text from question paper: {str(exc)}")

    questions, preamble, parse_warnings = parse_questions_from_text(raw_text)
    all_warnings = extraction_warnings + parse_warnings

    # Persist and register Question Paper version in database & storage
    qp_record = save_and_register_question_paper(
        db=db,
        exam=exam,
        file=file,
        content=content,
        user=current_user,
        meta=meta,
        question_count=len(questions),
    )

    return {
        "status": "success",
        "exam_id": exam.id,
        "exam_name": exam.name,
        "question_paper": qp_record.to_dict(),
        "filename": qp_record.original_filename,
        "version": qp_record.version,
        "file_type": ext,
        "file_size": len(content),
        "page_count": meta.get("page_count", len(page_records)),
        "preamble": preamble,
        "raw_text": raw_text,
        "questions": questions,
        "warnings": all_warnings,
        "preview_url": f"/api/teacher/exams/{exam_id}/question-paper/preview",
    }


@router.post("/exams/{exam_id}/question-papers/{qp_id}/activate")
def activate_question_paper(
    exam_id: int,
    qp_id: int,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Set a specific question paper version as active."""
    qp_rec = activate_question_paper_version(db, exam_id, qp_id, user=current_user)
    return {
        "status": "success",
        "message": f"Question paper v{qp_rec.version} marked as active.",
        "question_paper": qp_rec.to_dict(),
    }


@router.post("/exams/{exam_id}/question-papers/{qp_id}/archive")
def archive_question_paper(
    exam_id: int,
    qp_id: int,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Archive a question paper version without deleting data."""
    qp_rec = archive_question_paper_version(db, exam_id, qp_id, user=current_user)
    return {
        "status": "success",
        "message": f"Question paper v{qp_rec.version} archived successfully.",
        "question_paper": qp_rec.to_dict(),
    }


@router.post("/exams/{exam_id}/question-papers/{qp_id}/restore")
def restore_question_paper(
    exam_id: int,
    qp_id: int,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Restore an archived question paper version and set it active."""
    qp_rec = restore_question_paper_version(db, exam_id, qp_id, user=current_user)
    return {
        "status": "success",
        "message": f"Question paper v{qp_rec.version} restored and activated.",
        "question_paper": qp_rec.to_dict(),
    }


@router.delete("/exams/{exam_id}/question-papers/{qp_id}")
def delete_question_paper(
    exam_id: int,
    qp_id: int,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Delete a question paper version (safeguarded against deleting if evaluations exist)."""
    return delete_question_paper_version(db, exam_id, qp_id, user=current_user)


@router.get("/question-papers/{qp_id}/file")
def download_question_paper_file(
    qp_id: int,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Securely download / view uploaded question paper file."""
    qp_rec = db.query(QuestionPaperFile).filter(QuestionPaperFile.id == qp_id).first()
    if not qp_rec or qp_rec.status == "DELETED":
        raise HTTPException(status_code=404, detail="Question paper record not found.")

    check_exam_authorization(db, current_user, qp_rec.exam)

    file_path = Path(qp_rec.file_path).resolve()
    storage_root = config.storage_dir.resolve()
    if not str(file_path).startswith(str(storage_root)):
        raise HTTPException(status_code=403, detail="Access denied.")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Question paper file not found on server.")

    return FileResponse(str(file_path), filename=qp_rec.original_filename)


@router.get("/exams/{exam_id}/question-paper/preview")
def get_question_paper_preview(
    exam_id: int,
    page: int | None = Query(None, description="Page number for multipage PDF preview"),
    raw: bool = Query(False, description="Serve raw original file if True"),
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Retrieve uploaded question paper file or rendered page preview."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    check_exam_authorization(db, current_user, exam)

    year_str = re.sub(r"[^\w\-]", "_", exam.academic_year or "default")
    qp_dir = config.storage_dir / "question_papers" / year_str / f"exam_{exam.id}"
    if not qp_dir.exists():
        raise HTTPException(status_code=404, detail="No question paper found for this examination.")

    files = sorted(qp_dir.glob("qp_*.*"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        raise HTTPException(status_code=404, detail="No question paper file available.")

    latest_file = files[0]

    # If raw file requested or if it's an image/txt
    if raw or latest_file.suffix.lower() in [".png", ".jpg", ".jpeg", ".txt"]:
        media_type = (
            "text/plain"
            if latest_file.suffix.lower() == ".txt"
            else ("image/png" if latest_file.suffix.lower() == ".png" else "application/pdf")
        )
        return FileResponse(str(latest_file), media_type=media_type)

    # For PDFs, check if rendered page exists or generate on-the-fly
    if latest_file.suffix.lower() == ".pdf":
        page_num = page or 1
        rendered_page = qp_dir / f"page_{page_num:03d}.png"
        if not rendered_page.exists():
            try:
                import pymupdf
                from api.services.pdf_service import calculate_render_scale
                doc = pymupdf.open(str(latest_file))
                if 1 <= page_num <= doc.page_count:
                    p = doc[page_num - 1]
                    scale, _, _, _ = calculate_render_scale(p.rect, target_dpi=150)
                    pix = p.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                    pix.save(str(rendered_page))
                    pix = None
                doc.close()
            except Exception:
                pass

        if rendered_page.exists():
            return FileResponse(str(rendered_page), media_type="image/png")

    return FileResponse(str(latest_file))


@router.post("/exams/{exam_id}/questions/confirm")
def confirm_exam_questions(
    exam_id: int,
    req: ConfirmQuestionsRequest,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Save or update teacher-confirmed questions and rubrics for an exam."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    check_exam_authorization(db, current_user, exam)

    if not req.questions:
        raise HTTPException(status_code=400, detail="Cannot save empty question set.")

    # Validate distinct numbers and required fields
    seen_numbers = set()
    for q_in in req.questions:
        if q_in.question_number in seen_numbers:
            raise HTTPException(status_code=400, detail=f"Duplicate question #{q_in.question_number} in submission.")
        seen_numbers.add(q_in.question_number)

        if not q_in.question_text.strip():
            raise HTTPException(status_code=400, detail=f"Question #{q_in.question_number} text cannot be empty.")
        if q_in.max_marks <= 0:
            raise HTTPException(status_code=400, detail=f"Question #{q_in.question_number} max marks must be > 0.")

        # Validate rubric if provided
        if q_in.rubric_json:
            try:
                r_data = json.loads(q_in.rubric_json)
                from evaluation import Rubric
                rubric = Rubric.from_dict(r_data)
                rubric.validate()
                total_crit = sum(c.marks for c in rubric.criteria)
                if total_crit > q_in.max_marks:
                    raise ValueError(f"Criteria marks total ({total_crit}) exceeds question max marks ({q_in.max_marks})")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Invalid rubric for Question #{q_in.question_number}: {str(exc)}")

    # Update or insert questions
    confirmed_records = []
    incoming_nums = {q.question_number for q in req.questions}

    for q_in in req.questions:
        q_rec = (
            db.query(ExamQuestion)
            .filter(ExamQuestion.exam_id == exam_id, ExamQuestion.question_number == q_in.question_number)
            .first()
        )
        if not q_rec:
            q_rec = ExamQuestion(
                exam_id=exam_id,
                question_number=q_in.question_number,
                question_text=q_in.question_text.strip(),
                max_marks=q_in.max_marks,
                reference_answer=q_in.reference_answer.strip() if q_in.reference_answer else None,
                rubric_json=q_in.rubric_json,
                created_at=datetime.utcnow(),
            )
            db.add(q_rec)
        else:
            q_rec.question_text = q_in.question_text.strip()
            q_rec.max_marks = q_in.max_marks
            if q_in.reference_answer is not None:
                q_rec.reference_answer = q_in.reference_answer.strip()
            if q_in.rubric_json is not None:
                q_rec.rubric_json = q_in.rubric_json
            q_rec.updated_at = datetime.utcnow()

        confirmed_records.append(q_rec)

    # Clean up stale questions that have no student answers
    if req.replace_existing:
        stale_qs = (
            db.query(ExamQuestion)
            .filter(ExamQuestion.exam_id == exam_id, ~ExamQuestion.question_number.in_(incoming_nums))
            .all()
        )
        for sq in stale_qs:
            if not sq.answers:
                db.delete(sq)

    db.flush()

    # Recalculate exam total marks
    all_current_qs = db.query(ExamQuestion).filter(ExamQuestion.exam_id == exam_id).all()
    exam.total_marks = sum(q.max_marks for q in all_current_qs)

    active_qp = (
        db.query(QuestionPaperFile)
        .filter(QuestionPaperFile.exam_id == exam_id, QuestionPaperFile.is_active == True)
        .first()
    )
    if active_qp:
        active_qp.question_count = len(all_current_qs)

    db.commit()

    return {
        "status": "success",
        "message": f"Successfully saved {len(confirmed_records)} questions for '{exam.name}'.",
        "questions": [q.to_dict() for q in sorted(all_current_qs, key=lambda x: x.question_number)],
        "total_marks": exam.total_marks,
    }


# ─── Teacher Review & Workload Management ───

@router.get("/assignments")
def list_teacher_assignments(
    status_filter: str | None = Query(None, alias="status", description="Filter by ASSIGNED, IN_REVIEW, COMPLETED"),
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Retrieve risky answer assignments assigned strictly to the current teacher (or all for HOD overview)."""
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
    current_user: User = Depends(require_teacher_or_hod),
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

    # Student metadata
    student = ans.script.student if ans.script else None

    return {
        "assignment_id": assignment.id,
        "assignment_status": assignment.assignment_status,
        "answer_id": ans.id,
        "script_id": ans.script_id,
        "student": {
            "id": student.id if student else None,
            "name": student.name if student else "Unknown",
            "usn": student.usn if student else "Unidentified",
        } if student else None,
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
    """Submit final mark and teacher notes for an assigned answer (Teacher only)."""
    assignment = db.query(TeacherAssignment).filter(TeacherAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found.")

    # Strict check: teacher can only submit for their own assigned evaluation
    if assignment.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You cannot review an assignment that belongs to another teacher.",
        )

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


@router.get("/answer-keys/{key_id}/file")
def download_answer_key_file(
    key_id: int,
    current_user: User = Depends(require_teacher_or_hod),
    db: Session = Depends(get_db),
):
    """Securely download / view official answer key file."""
    key_rec = db.query(AnswerKeyFile).filter(AnswerKeyFile.id == key_id).first()
    if not key_rec:
        raise HTTPException(status_code=404, detail="Answer key file record not found.")

    check_exam_authorization(db, current_user, key_rec.exam)

    file_path = Path(key_rec.file_path).resolve()
    storage_root = config.storage_dir.resolve()
    if not str(file_path).startswith(str(storage_root)):
        raise HTTPException(status_code=403, detail="Access denied.")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on server.")

    return FileResponse(str(file_path), filename=key_rec.original_filename)
