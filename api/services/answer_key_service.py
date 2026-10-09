"""Official answer key and marking scheme service for EvaliSense.

Handles:
- Uploading and versioning official answer keys for examinations
- File storage in storage/answer_keys/{academic_year}/{exam_id}/
- Version incrementing and active version toggling
- Structured questions extraction and synchronization with exam_questions
- Strict teacher-subject assignment verification
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from api.database.models import AnswerKeyFile, Exam, ExamQuestion, TeacherSubject, User
from api.services.notification_service import create_notification
from config import config
from utils.logging import get_logger

logger = get_logger(__name__)

ALLOWED_ANSWER_KEY_EXTENSIONS = {".txt", ".json", ".pdf", ".png", ".jpg", ".jpeg", ".docx"}
MAX_ANSWER_KEY_SIZE = 25 * 1024 * 1024  # 25 MB


def is_teacher_assigned_to_exam_subject(db: Session, teacher_id: int, exam: Exam) -> bool:
    """Verify whether a teacher is assigned to the exam's subject."""
    mapping = (
        db.query(TeacherSubject)
        .filter(
            TeacherSubject.teacher_id == teacher_id,
            TeacherSubject.subject_id == exam.subject_id,
            TeacherSubject.is_active.is_(True),
        )
        .first()
    )
    return mapping is not None


def check_exam_authorization(db: Session, user: User, exam: Exam) -> None:
    """Ensure user is authorized to manage answer keys or rubrics for the exam."""
    user_role = user.role.name if user.role else ""
    if user_role == "HOD":
        return
    if user_role == "TEACHER":
        if not is_teacher_assigned_to_exam_subject(db, user.id, exam):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: You are not assigned to subject '{exam.subject.name if exam.subject else exam.subject_id}' for this examination.",
            )
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only subject teachers and HOD can manage answer keys.",
    )


def save_and_register_answer_key(
    db: Session,
    exam: Exam,
    user: User,
    file: UploadFile | None = None,
    questions_json: str | None = None,
) -> AnswerKeyFile:
    """Save answer key file, track version, set active, and update structured questions."""
    check_exam_authorization(db, user, exam)

    # Calculate next version
    existing_keys = (
        db.query(AnswerKeyFile)
        .filter(AnswerKeyFile.exam_id == exam.id)
        .order_by(AnswerKeyFile.version.desc())
        .all()
    )
    next_version = (existing_keys[0].version + 1) if existing_keys else 1

    # Deactivate older versions
    for k in existing_keys:
        k.is_active = False

    # Build safe storage path: storage/answer_keys/{academic_year}/{exam_id}/
    year_str = re.sub(r"[^\w\-]", "_", exam.academic_year or "default")
    key_dir = config.storage_dir / "answer_keys" / year_str / f"exam_{exam.id}"
    key_dir.mkdir(parents=True, exist_ok=True)

    filename = "structured_key.json"
    file_path = str(key_dir / f"key_v{next_version}_{filename}")

    if file and file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext and ext not in ALLOWED_ANSWER_KEY_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported answer key format '{ext}'. Allowed: {', '.join(ALLOWED_ANSWER_KEY_EXTENSIONS)}",
            )
        content = file.file.read()
        file.file.seek(0)
        if len(content) > MAX_ANSWER_KEY_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File exceeds maximum size of 25MB (got {len(content)/(1024*1024):.1f}MB)",
            )

        safe_name = re.sub(r"[^\w\-.]", "_", Path(file.filename).stem)
        stored_file_path = key_dir / f"key_v{next_version}_{safe_name}{ext}"
        with open(stored_file_path, "wb") as f:
            f.write(content)
        file_path = str(stored_file_path)
        filename = file.filename

        # If file is a JSON file and no questions_json was provided, attempt to parse structured questions
        if ext == ".json" and not questions_json:
            try:
                questions_json = content.decode("utf-8")
            except Exception:
                pass

    key_record = AnswerKeyFile(
        exam_id=exam.id,
        uploaded_by=user.id,
        original_filename=filename,
        file_path=file_path,
        version=next_version,
        is_active=True,
        uploaded_at=datetime.utcnow(),
    )
    db.add(key_record)
    db.flush()

    # Parse questions if provided
    if questions_json:
        try:
            data = json.loads(questions_json)
            questions_list = data if isinstance(data, list) else data.get("questions", [])
            for q_data in questions_list:
                q_num = q_data.get("question_number") or q_data.get("number")
                if not q_num:
                    continue
                q_rec = (
                    db.query(ExamQuestion)
                    .filter(ExamQuestion.exam_id == exam.id, ExamQuestion.question_number == q_num)
                    .first()
                )
                q_text = q_data.get("question_text") or q_data.get("text") or f"Question {q_num}"
                max_m = float(q_data.get("max_marks", 10.0))
                ref_ans = q_data.get("reference_answer", "")
                rubric_val = q_data.get("rubric_json")
                if isinstance(rubric_val, dict):
                    rubric_val = json.dumps(rubric_val)
                elif not rubric_val and "criteria" in q_data:
                    rubric_val = json.dumps({
                        "question": q_text,
                        "max_marks": max_m,
                        "reference_answer": ref_ans,
                        "criteria": q_data.get("criteria", []),
                    })

                if not q_rec:
                    q_rec = ExamQuestion(
                        exam_id=exam.id,
                        question_number=q_num,
                        question_text=q_text,
                        max_marks=max_m,
                        reference_answer=ref_ans,
                        rubric_json=rubric_val,
                        created_at=datetime.utcnow(),
                    )
                    db.add(q_rec)
                else:
                    q_rec.question_text = q_text
                    q_rec.max_marks = max_m
                    q_rec.reference_answer = ref_ans
                    if rubric_val:
                        q_rec.rubric_json = rubric_val
                    q_rec.updated_at = datetime.utcnow()
        except Exception as e:
            logger.warning("Could not auto-parse structured questions from answer key: %s", e)

    db.commit()
    db.refresh(key_record)

    # Notify teacher and HOD
    create_notification(
        db=db,
        user_id=user.id,
        type="ANSWER_KEY_UPLOADED",
        title=f"Answer Key Uploaded (v{next_version})",
        message=f"Official answer key v{next_version} for exam '{exam.name}' was successfully uploaded.",
        reference_type="exam",
        reference_id=exam.id,
    )

    return key_record


def get_exam_answer_key_info(db: Session, exam_id: int) -> dict[str, Any]:
    """Retrieve active answer key and version history for an examination."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    keys = (
        db.query(AnswerKeyFile)
        .filter(AnswerKeyFile.exam_id == exam_id)
        .order_by(AnswerKeyFile.version.desc())
        .all()
    )

    active_key = next((k.to_dict() for k in keys if k.is_active), None)
    return {
        "exam_id": exam.id,
        "exam_name": exam.name,
        "subject_name": exam.subject.name if exam.subject else None,
        "subject_code": exam.subject.code if exam.subject else None,
        "has_active_key": active_key is not None,
        "active_key": active_key,
        "active_answer_key": active_key,
        "versions": [k.to_dict() for k in keys],
        "questions_count": len(exam.questions),
        "questions": [q.to_dict() for q in exam.questions],
    }


def activate_answer_key_version(
    db: Session,
    exam_id: int,
    key_id: int,
    user: User,
) -> AnswerKeyFile:
    """Switch the active answer key version for an examination."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    check_exam_authorization(db, user, exam)

    target_key = db.query(AnswerKeyFile).filter(AnswerKeyFile.id == key_id, AnswerKeyFile.exam_id == exam_id).first()
    if not target_key:
        raise HTTPException(status_code=404, detail="Answer key file version not found.")

    all_keys = db.query(AnswerKeyFile).filter(AnswerKeyFile.exam_id == exam_id).all()
    for k in all_keys:
        k.is_active = (k.id == target_key.id)

    db.commit()
    db.refresh(target_key)

    create_notification(
        db=db,
        user_id=user.id,
        type="ANSWER_KEY_VERSION_CHANGED",
        title=f"Active Answer Key Updated (v{target_key.version})",
        message=f"Version v{target_key.version} is now active for examination '{exam.name}'.",
        reference_type="exam",
        reference_id=exam.id,
    )

    return target_key
