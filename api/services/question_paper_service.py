"""Official Question Paper document and version lifecycle management service for EvaliSense.

Handles:
- Uploading and registering question paper versions (PDF, PNG, JPG, JPEG, TXT)
- File storage in storage/question_papers/{academic_year}/{exam_id}/
- Version incrementing, replacement, archiving, restoring, and safe deletion
- Safeguards to prevent deleting documents associated with evaluated student answer scripts
- Access authorization and audit notifications
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from api.database.models import AnswerScript, Exam, QuestionPaperFile, TeacherSubject, User
from api.services.notification_service import create_notification
from config import config
from utils.logging import get_logger

logger = get_logger(__name__)


def check_exam_authorization(db: Session, user: User, exam: Exam) -> None:
    """Verify that user has teacher access or HOD privileges for this exam's subject."""
    role_name = user.role.name if hasattr(user.role, "name") else str(user.role)
    if role_name in ["HOD", "ADMIN"]:
        return

    if role_name == "TEACHER":
        is_assigned = (
            db.query(TeacherSubject)
            .filter(
                TeacherSubject.teacher_id == user.id,
                TeacherSubject.subject_id == exam.subject_id,
            )
            .first()
            is not None
        )
        if not is_assigned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: You are not assigned to subject '{exam.subject.name if exam.subject else exam.subject_id}'.",
            )
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only subject teachers and HOD can manage question papers.",
    )


def save_and_register_question_paper(
    db: Session,
    exam: Exam,
    file: UploadFile,
    content: bytes,
    user: User,
    meta: dict[str, Any],
    question_count: int = 0,
) -> QuestionPaperFile:
    """Save an uploaded question paper file to persistent storage and register its version."""
    check_exam_authorization(db, user, exam)

    year_str = re.sub(r"[^\w\-]", "_", exam.academic_year or "default")
    qp_dir = config.storage_dir / "question_papers" / year_str / f"exam_{exam.id}"
    qp_dir.mkdir(parents=True, exist_ok=True)

    # Determine next version
    latest = (
        db.query(QuestionPaperFile)
        .filter(QuestionPaperFile.exam_id == exam.id)
        .order_by(QuestionPaperFile.version.desc())
        .first()
    )
    next_version = (latest.version + 1) if latest else 1

    ext = meta.get("extension", Path(file.filename or "qp.pdf").suffix.lower() or ".pdf")
    safe_name = re.sub(r"[^\w\-.]", "_", Path(file.filename or "question_paper").stem)
    stored_path = qp_dir / f"qp_v{next_version}_{safe_name}{ext}"

    with open(stored_path, "wb") as f:
        f.write(content)

    # Render page 1 preview for PDF
    if ext == ".pdf":
        try:
            import pymupdf
            from api.services.pdf_service import calculate_render_scale
            doc = pymupdf.open(stream=content, filetype="pdf")
            if doc.page_count > 0:
                p0 = doc[0]
                scale, _, _, _ = calculate_render_scale(p0.rect, target_dpi=150)
                pix = p0.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                pix.save(str(qp_dir / f"preview_v{next_version}_page1.png"))
                pix.save(str(qp_dir / "preview_page1.png"))
                pix = None
            doc.close()
        except Exception as exc:
            logger.warning("Could not render page 1 preview for QP v%d: %s", next_version, exc)

    # Deactivate existing active question papers
    existing_actives = (
        db.query(QuestionPaperFile)
        .filter(QuestionPaperFile.exam_id == exam.id, QuestionPaperFile.is_active == True)
        .all()
    )
    for qp in existing_actives:
        qp.is_active = False

    qp_record = QuestionPaperFile(
        exam_id=exam.id,
        uploaded_by=user.id,
        original_filename=file.filename or "question_paper",
        file_path=str(stored_path),
        file_size=len(content),
        page_count=meta.get("page_count", 1),
        version=next_version,
        is_active=True,
        status="ACTIVE",
        question_count=question_count,
        uploaded_at=datetime.utcnow(),
    )
    db.add(qp_record)
    db.commit()
    db.refresh(qp_record)

    create_notification(
        db=db,
        user_id=user.id,
        type="QUESTION_PAPER_UPLOADED",
        title=f"Question Paper Uploaded (v{next_version})",
        message=f"Question paper v{next_version} for examination '{exam.name}' was successfully uploaded and registered.",
        reference_type="exam",
        reference_id=exam.id,
    )

    return qp_record


def get_exam_question_papers_info(db: Session, exam_id: int) -> dict[str, Any]:
    """Retrieve active question paper and version history for an examination."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    records = (
        db.query(QuestionPaperFile)
        .filter(QuestionPaperFile.exam_id == exam_id, QuestionPaperFile.status != "DELETED")
        .order_by(QuestionPaperFile.version.desc())
        .all()
    )

    active_rec = next((r.to_dict() for r in records if r.is_active and r.status == "ACTIVE"), None)
    return {
        "exam_id": exam.id,
        "exam_name": exam.name,
        "subject_name": exam.subject.name if exam.subject else None,
        "subject_code": exam.subject.code if exam.subject else None,
        "has_active_question_paper": active_rec is not None,
        "active_question_paper": active_rec,
        "versions": [r.to_dict() for r in records],
        "question_papers": [r.to_dict() for r in records],
        "total_versions": len(records),
        "count": len(records),
    }


def activate_question_paper_version(
    db: Session,
    exam_id: int,
    qp_id: int,
    user: User,
) -> QuestionPaperFile:
    """Switch the active question paper version for an examination."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    check_exam_authorization(db, user, exam)

    target_qp = (
        db.query(QuestionPaperFile)
        .filter(QuestionPaperFile.id == qp_id, QuestionPaperFile.exam_id == exam_id)
        .first()
    )
    if not target_qp or target_qp.status == "DELETED":
        raise HTTPException(status_code=404, detail="Question paper version not found.")

    all_qps = db.query(QuestionPaperFile).filter(QuestionPaperFile.exam_id == exam_id).all()
    for qp in all_qps:
        qp.is_active = (qp.id == target_qp.id)

    target_qp.status = "ACTIVE"
    db.commit()
    db.refresh(target_qp)

    create_notification(
        db=db,
        user_id=user.id,
        type="QUESTION_PAPER_VERSION_CHANGED",
        title=f"Active Question Paper Updated (v{target_qp.version})",
        message=f"Question paper v{target_qp.version} is now active for examination '{exam.name}'.",
        reference_type="exam",
        reference_id=exam.id,
    )

    return target_qp


def archive_question_paper_version(
    db: Session,
    exam_id: int,
    qp_id: int,
    user: User,
) -> QuestionPaperFile:
    """Archive a question paper version without deleting files or evaluation links."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    check_exam_authorization(db, user, exam)

    target_qp = (
        db.query(QuestionPaperFile)
        .filter(QuestionPaperFile.id == qp_id, QuestionPaperFile.exam_id == exam_id)
        .first()
    )
    if not target_qp or target_qp.status == "DELETED":
        raise HTTPException(status_code=404, detail="Question paper version not found.")

    target_qp.status = "ARCHIVED"
    was_active = target_qp.is_active
    target_qp.is_active = False

    # If it was active, pick the newest remaining active or unarchived version if any
    if was_active:
        remaining = (
            db.query(QuestionPaperFile)
            .filter(
                QuestionPaperFile.exam_id == exam_id,
                QuestionPaperFile.id != target_qp.id,
                QuestionPaperFile.status == "ACTIVE",
            )
            .order_by(QuestionPaperFile.version.desc())
            .first()
        )
        if remaining:
            remaining.is_active = True

    db.commit()
    db.refresh(target_qp)

    create_notification(
        db=db,
        user_id=user.id,
        type="QUESTION_PAPER_ARCHIVED",
        title=f"Question Paper Archived (v{target_qp.version})",
        message=f"Question paper v{target_qp.version} has been archived for exam '{exam.name}'.",
        reference_type="exam",
        reference_id=exam.id,
    )

    return target_qp


def restore_question_paper_version(
    db: Session,
    exam_id: int,
    qp_id: int,
    user: User,
) -> QuestionPaperFile:
    """Restore an archived question paper version and set it active."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    check_exam_authorization(db, user, exam)

    target_qp = (
        db.query(QuestionPaperFile)
        .filter(QuestionPaperFile.id == qp_id, QuestionPaperFile.exam_id == exam_id)
        .first()
    )
    if not target_qp or target_qp.status == "DELETED":
        raise HTTPException(status_code=404, detail="Question paper version not found.")

    all_qps = db.query(QuestionPaperFile).filter(QuestionPaperFile.exam_id == exam_id).all()
    for qp in all_qps:
        qp.is_active = (qp.id == target_qp.id)

    target_qp.status = "ACTIVE"
    db.commit()
    db.refresh(target_qp)

    create_notification(
        db=db,
        user_id=user.id,
        type="QUESTION_PAPER_RESTORED",
        title=f"Question Paper Restored (v{target_qp.version})",
        message=f"Question paper v{target_qp.version} has been restored and activated for exam '{exam.name}'.",
        reference_type="exam",
        reference_id=exam.id,
    )

    return target_qp


def delete_question_paper_version(
    db: Session,
    exam_id: int,
    qp_id: int,
    user: User,
) -> dict[str, Any]:
    """Safely delete or soft-delete a question paper version with evaluation safety check."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    check_exam_authorization(db, user, exam)

    target_qp = (
        db.query(QuestionPaperFile)
        .filter(QuestionPaperFile.id == qp_id, QuestionPaperFile.exam_id == exam_id)
        .first()
    )
    if not target_qp or target_qp.status == "DELETED":
        raise HTTPException(status_code=404, detail="Question paper version not found.")

    # Safeguard: check if exam has evaluated student answer scripts
    has_evals = (
        db.query(AnswerScript)
        .filter(
            AnswerScript.exam_id == exam_id,
            AnswerScript.status.in_(["EVALUATED", "COMPLETED", "TEACHER_REVIEW", "FINALIZED"]),
        )
        .count()
        > 0
    )
    if has_evals:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cannot delete question paper: this examination has evaluated student answer scripts. "
                "Question papers must be retained for academic integrity and auditability. "
                "You may archive this version instead."
            ),
        )

    # Perform soft-deletion
    was_active = target_qp.is_active
    target_qp.status = "DELETED"
    target_qp.is_active = False

    if was_active:
        remaining = (
            db.query(QuestionPaperFile)
            .filter(
                QuestionPaperFile.exam_id == exam_id,
                QuestionPaperFile.id != target_qp.id,
                QuestionPaperFile.status == "ACTIVE",
            )
            .order_by(QuestionPaperFile.version.desc())
            .first()
        )
        if remaining:
            remaining.is_active = True

    db.commit()

    return {
        "status": "success",
        "message": f"Question paper v{target_qp.version} successfully removed.",
        "deleted_id": target_qp.id,
    }
