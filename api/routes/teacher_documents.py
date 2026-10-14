"""Teacher document management routes: question papers and answer keys.

Allows teachers assigned to a subject/exam to:
- Upload question papers (PDF, JPG, JPEG, PNG)
- Upload official answer keys with versioning
- View upload history and previews
- Manage answer key versions

Scanner and Teacher script upload restrictions are enforced:
- Scanners cannot upload answer keys
- Teachers cannot upload student answer scripts
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_teacher
from api.database.models import (
    AnswerKey,
    Exam,
    ExamQuestion,
    QuestionPaper,
    TeacherSubject,
    User,
)
from api.database.session import get_db
from api.services.audit_service import create_audit_log
from api.services.file_service import (
    ALLOWED_DOCUMENT_TYPES,
    compute_checksum,
    save_uploaded_file,
    validate_upload_file,
    count_pdf_pages,
)
from config import config
from utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/teacher/documents", tags=["Teacher Documents"])


def _verify_teacher_exam_access(db: Session, teacher: User, exam_id: int) -> Exam:
    """Verify that the teacher is assigned to the exam's subject."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    user_role = teacher.role.name if teacher.role else ""
    if user_role == "HOD":
        return exam  # HOD can view but not upload scripts

    # Check teacher-subject mapping
    mapping = (
        db.query(TeacherSubject)
        .filter(
            TeacherSubject.teacher_id == teacher.id,
            TeacherSubject.subject_id == exam.subject_id,
            TeacherSubject.is_active.is_(True),
        )
        .first()
    )
    if not mapping:
        raise HTTPException(
            status_code=403,
            detail="You are not assigned to this exam's subject.",
        )
    return exam


# ──────────────────── Question Paper Endpoints ────────────────────


@router.post("/question-papers")
def upload_question_paper(
    exam_id: int = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Upload a question paper for an assigned exam (Teacher or HOD)."""
    exam = _verify_teacher_exam_access(db, current_user, exam_id)

    content = file.file.read()
    file.file.seek(0)

    is_valid, msg, meta = validate_upload_file(file, content)
    if not is_valid:
        raise HTTPException(status_code=400, detail=msg)

    # Determine page count for PDFs
    page_count = 1
    if meta.get("mime_type") == "application/pdf":
        page_count = count_pdf_pages(content)

    # Get next version number
    latest = (
        db.query(QuestionPaper)
        .filter(QuestionPaper.exam_id == exam_id)
        .order_by(QuestionPaper.version.desc())
        .first()
    )
    next_version = (latest.version + 1) if latest else 1

    # Deactivate previous versions
    if latest:
        db.query(QuestionPaper).filter(
            QuestionPaper.exam_id == exam_id,
            QuestionPaper.is_active.is_(True),
        ).update({"is_active": False})

    # Save file
    storage_path, safe_name = save_uploaded_file(
        content=content,
        category="question_papers",
        exam_id=exam_id,
        original_filename=file.filename or "question_paper.pdf",
    )

    qp = QuestionPaper(
        exam_id=exam_id,
        uploaded_by=current_user.id,
        original_filename=file.filename or "unknown",
        storage_path=str(storage_path),
        mime_type=meta["mime_type"],
        file_size=meta["file_size"],
        checksum=meta["checksum"],
        version=next_version,
        is_active=True,
        page_count=page_count,
        uploaded_at=datetime.utcnow(),
    )
    db.add(qp)
    db.commit()
    db.refresh(qp)

    create_audit_log(
        db=db,
        user_id=current_user.id,
        action="UPLOAD_QUESTION_PAPER",
        entity_type="question_paper",
        entity_id=qp.id,
        details={"exam_id": exam_id, "version": next_version, "filename": file.filename},
    )

    return {"status": "success", "question_paper": qp.to_dict()}


@router.get("/question-papers")
def list_question_papers(
    exam_id: int | None = Query(None, description="Filter by exam ID"),
    current_user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """List question papers for assigned exams."""
    query = db.query(QuestionPaper)
    if exam_id is not None:
        query = query.filter(QuestionPaper.exam_id == exam_id)
    papers = query.order_by(QuestionPaper.uploaded_at.desc()).all()
    return [p.to_dict() for p in papers]


@router.get("/question-papers/{paper_id}/preview")
def preview_question_paper(
    paper_id: int,
    current_user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Serve the question paper file for preview."""
    paper = db.query(QuestionPaper).filter(QuestionPaper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Question paper not found.")

    file_path = Path(paper.storage_path).resolve()
    storage_root = config.storage_dir.resolve()
    project_root = config.project_root.resolve()

    if not (str(file_path).startswith(str(storage_root)) or str(file_path).startswith(str(project_root))):
        raise HTTPException(status_code=403, detail="Access denied.")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on server.")

    return FileResponse(str(file_path), media_type=paper.mime_type)


# ──────────────────── Answer Key Endpoints ────────────────────


@router.post("/answer-keys")
def upload_answer_key(
    exam_id: int = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Upload an official answer key for an assigned exam (Teacher or HOD).

    Scanners are explicitly blocked from uploading or modifying answer keys.
    """
    user_role = current_user.role.name if current_user.role else ""
    if user_role == "SCANNER":
        raise HTTPException(
            status_code=403,
            detail="Scanners cannot upload or modify official answer keys.",
        )

    exam = _verify_teacher_exam_access(db, current_user, exam_id)

    content = file.file.read()
    file.file.seek(0)

    is_valid, msg, meta = validate_upload_file(file, content)
    if not is_valid:
        raise HTTPException(status_code=400, detail=msg)

    page_count = 1
    if meta.get("mime_type") == "application/pdf":
        page_count = count_pdf_pages(content)

    # Get next version number
    latest = (
        db.query(AnswerKey)
        .filter(AnswerKey.exam_id == exam_id)
        .order_by(AnswerKey.version.desc())
        .first()
    )
    next_version = (latest.version + 1) if latest else 1

    # Mark previous active versions as SUPERSEDED
    if latest:
        db.query(AnswerKey).filter(
            AnswerKey.exam_id == exam_id,
            AnswerKey.is_active.is_(True),
        ).update({"is_active": False, "status": "SUPERSEDED"})

    storage_path, safe_name = save_uploaded_file(
        content=content,
        category="answer_keys",
        exam_id=exam_id,
        original_filename=file.filename or "answer_key.pdf",
    )

    ak = AnswerKey(
        exam_id=exam_id,
        uploaded_by=current_user.id,
        original_filename=file.filename or "unknown",
        storage_path=str(storage_path),
        mime_type=meta["mime_type"],
        file_size=meta["file_size"],
        checksum=meta["checksum"],
        version=next_version,
        is_active=True,
        is_approved=False,
        page_count=page_count,
        status="UPLOADED",
        uploaded_at=datetime.utcnow(),
    )
    db.add(ak)
    db.commit()
    db.refresh(ak)

    create_audit_log(
        db=db,
        user_id=current_user.id,
        action="UPLOAD_ANSWER_KEY",
        entity_type="answer_key",
        entity_id=ak.id,
        details={"exam_id": exam_id, "version": next_version, "filename": file.filename},
    )

    return {"status": "success", "answer_key": ak.to_dict()}


@router.get("/answer-keys")
def list_answer_keys(
    exam_id: int | None = Query(None, description="Filter by exam ID"),
    active_only: bool = Query(False, description="Only show active versions"),
    current_user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """List answer keys for assigned exams with version history."""
    query = db.query(AnswerKey)
    if exam_id is not None:
        query = query.filter(AnswerKey.exam_id == exam_id)
    if active_only:
        query = query.filter(AnswerKey.is_active.is_(True))
    keys = query.order_by(AnswerKey.uploaded_at.desc()).all()
    return [k.to_dict() for k in keys]


@router.get("/answer-keys/{key_id}/preview")
def preview_answer_key(
    key_id: int,
    current_user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Serve the answer key file for preview."""
    key = db.query(AnswerKey).filter(AnswerKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="Answer key not found.")

    file_path = Path(key.storage_path).resolve()
    storage_root = config.storage_dir.resolve()
    project_root = config.project_root.resolve()

    if not (str(file_path).startswith(str(storage_root)) or str(file_path).startswith(str(project_root))):
        raise HTTPException(status_code=403, detail="Access denied.")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on server.")

    return FileResponse(str(file_path), media_type=key.mime_type)


@router.post("/answer-keys/{key_id}/approve")
def approve_answer_key(
    key_id: int,
    current_user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Approve an answer key for use in evaluation (Teacher or HOD)."""
    user_role = current_user.role.name if current_user.role else ""
    if user_role == "SCANNER":
        raise HTTPException(status_code=403, detail="Scanners cannot approve answer keys.")

    key = db.query(AnswerKey).filter(AnswerKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="Answer key not found.")

    # Deactivate other approved keys for same exam
    db.query(AnswerKey).filter(
        AnswerKey.exam_id == key.exam_id,
        AnswerKey.id != key.id,
        AnswerKey.is_approved.is_(True),
    ).update({"is_approved": False, "status": "SUPERSEDED", "is_active": False})

    key.is_approved = True
    key.is_active = True
    key.status = "APPROVED"
    key.approved_at = datetime.utcnow()
    db.commit()
    db.refresh(key)

    create_audit_log(
        db=db,
        user_id=current_user.id,
        action="APPROVE_ANSWER_KEY",
        entity_type="answer_key",
        entity_id=key.id,
        details={"exam_id": key.exam_id, "version": key.version},
    )

    return {"status": "success", "message": "Answer key approved.", "answer_key": key.to_dict()}
