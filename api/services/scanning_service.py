"""Scanning and image validation service for EvaliSense.

Handles:
- Upload verification and security checks (file extension, path traversal, file size)
- Image quality checks (resolution, blur via Laplacian variance, corruption)
- Answer script database record creation
- Scan issue generation and resolution
"""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from api.database.models import AnswerScript, Exam, ScanIssue, Student, User
from api.services.notification_service import create_notification
from config import config
from utils.logging import get_logger

logger = get_logger(__name__)

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB


def validate_image_file(file: UploadFile, content: bytes) -> tuple[bool, str, dict[str, Any]]:
    """Validate uploaded image format, size, and visual quality."""
    if not file.filename:
        return False, "No filename provided", {}

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Unsupported file extension '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}", {}

    if len(content) > MAX_FILE_SIZE:
        return False, f"File exceeds maximum size of 25MB (got {len(content) / (1024*1024):.1f}MB)", {}

    # Read image with OpenCV
    nparr = np.frombuffer(content, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        return False, "Corrupted image file or unreadable image format.", {}

    h, w = image.shape[:2]
    if h < 100 or w < 100:
        return False, f"Image resolution too low ({w}x{h} px). Minimum required is 100x100 px.", {}

    # Blur detection via Laplacian variance
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()

    is_blurry = blur_score < 15.0
    quality = "POOR" if is_blurry else ("EXCELLENT" if blur_score > 150 else "ACCEPTABLE")

    metadata = {
        "width": w,
        "height": h,
        "blur_score": float(round(blur_score, 2)),
        "quality": quality,
        "is_blurry": is_blurry,
    }

    if is_blurry:
        return False, f"Image is excessively blurry (blur score: {blur_score:.1f}). Please provide a sharper scan.", metadata

    return True, "Image validation passed", metadata


def save_and_register_script(
    db: Session,
    exam: Exam,
    uploader: User,
    file: UploadFile,
    student_usn: str | None = None,
    student_id: int | None = None,
) -> AnswerScript:
    """Save the uploaded script to disk and register in the database."""
    content = file.file.read()
    file.file.seek(0)

    # Validate image quality
    is_valid, validation_msg, quality_meta = validate_image_file(file, content)

    # Determine student mapping
    student = None
    student_confidence = 1.0
    if student_id:
        student = db.query(Student).filter(Student.id == student_id, Student.is_active.is_(True)).first()
    elif student_usn:
        student = db.query(Student).filter(Student.usn == student_usn.strip(), Student.is_active.is_(True)).first()
        if not student:
            student_confidence = 0.3

    # Generate safe unique path
    ext = Path(file.filename).suffix.lower() if file.filename else ".png"
    safe_uid = str(uuid.uuid4())[:12]
    exam_storage = config.storage_dir / f"exam_{exam.id}"
    exam_storage.mkdir(parents=True, exist_ok=True)
    stored_path = exam_storage / f"script_{safe_uid}{ext}"

    with open(stored_path, "wb") as f:
        f.write(content)

    initial_status = "UPLOADED" if is_valid else "REUPLOAD_REQUIRED"
    scan_quality = quality_meta.get("quality", "POOR" if not is_valid else "ACCEPTABLE")

    script = AnswerScript(
        exam_id=exam.id,
        student_id=student.id if student else None,
        uploaded_by=uploader.id,
        original_filename=file.filename or "unknown.png",
        original_path=str(stored_path),
        status=initial_status,
        scan_quality=scan_quality,
        student_identifier_confidence=student_confidence,
        uploaded_at=datetime.utcnow(),
    )
    db.add(script)
    db.commit()
    db.refresh(script)

    # If image failed quality check, immediately log a scan issue
    if not is_valid:
        issue_type = "POOR_IMAGE" if quality_meta.get("is_blurry") else "CORRUPTED_FILE"
        issue = ScanIssue(
            script_id=script.id,
            reported_by=uploader.id,
            issue_type=issue_type,
            description=f"Automated quality rejection: {validation_msg}",
            severity="HIGH",
            status="OPEN",
        )
        db.add(issue)
        db.commit()

        # Notify scanner
        create_notification(
            db=db,
            user_id=uploader.id,
            type="RESCAN_REQUIRED",
            title=f"Scan Issue on Script #{script.id}",
            message=f"Script '{script.original_filename}' requires re-upload: {validation_msg}",
            reference_type="answer_script",
            reference_id=script.id,
        )

    # If student identification failed, log issue
    elif student_usn and not student:
        issue = ScanIssue(
            script_id=script.id,
            reported_by=uploader.id,
            issue_type="STUDENT_ID_NOT_RECOGNIZED",
            description=f"Provided student USN '{student_usn}' does not match any registered student.",
            severity="MEDIUM",
            status="OPEN",
        )
        db.add(issue)
        db.commit()

    return script


def resolve_scan_issue(
    db: Session,
    issue_id: int,
    user: User,
    resolution_note: str | None = None,
) -> ScanIssue:
    """Mark a scan issue as resolved."""
    issue = db.query(ScanIssue).filter(ScanIssue.id == issue_id).first()
    if not issue:
        raise HTTPException(status_code=404, detail="Scan issue not found.")

    issue.status = "RESOLVED"
    issue.resolved_at = datetime.utcnow()
    if resolution_note:
        issue.description = f"{issue.description} | Resolved note: {resolution_note}"

    # If all issues for the script are resolved, update script status
    open_issues = db.query(ScanIssue).filter(
        ScanIssue.script_id == issue.script_id,
        ScanIssue.status == "OPEN",
    ).count()

    if open_issues == 0 and issue.script:
        if issue.script.status == "REUPLOAD_REQUIRED":
            issue.script.status = "UPLOADED"

    db.commit()
    db.refresh(issue)
    return issue


def rescan_script(
    db: Session,
    script_id: int,
    file: UploadFile,
    user: User,
) -> AnswerScript:
    """Replace an existing script with a new scan and resolve open issues."""
    script = db.query(AnswerScript).filter(AnswerScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Answer script not found.")

    content = file.file.read()
    file.file.seek(0)

    is_valid, validation_msg, quality_meta = validate_image_file(file, content)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"New scan validation failed: {validation_msg}")

    # Overwrite the stored file or save with new name
    ext = Path(file.filename).suffix.lower() if file.filename else ".png"
    safe_uid = str(uuid.uuid4())[:12]
    exam_storage = config.storage_dir / f"exam_{script.exam_id}"
    exam_storage.mkdir(parents=True, exist_ok=True)
    new_path = exam_storage / f"script_{safe_uid}{ext}"

    with open(new_path, "wb") as f:
        f.write(content)

    script.original_filename = file.filename or script.original_filename
    script.original_path = str(new_path)
    script.status = "UPLOADED"
    script.scan_quality = quality_meta.get("quality", "ACCEPTABLE")
    script.uploaded_at = datetime.utcnow()

    # Resolve open scan issues
    open_issues = db.query(ScanIssue).filter(
        ScanIssue.script_id == script.id,
        ScanIssue.status == "OPEN",
    ).all()
    for issue in open_issues:
        issue.status = "RESOLVED"
        issue.resolved_at = datetime.utcnow()
        issue.description = f"{issue.description} (Resolved via rescan)"

    db.commit()
    db.refresh(script)

    create_notification(
        db=db,
        user_id=user.id,
        type="SCAN_RESOLVED",
        title=f"Script #{script.id} Rescanned",
        message=f"Script #{script.id} was successfully rescanned and is ready for evaluation.",
        reference_type="answer_script",
        reference_id=script.id,
    )

    return script
