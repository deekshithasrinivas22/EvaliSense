"""Scanning and image validation service for EvaliSense.

Handles:
- Upload verification and security checks (file extension, path traversal, file size)
- Image quality checks (resolution, blur via Laplacian variance, corruption)
- Answer script database record creation
- Scan issue generation and resolution
"""
from __future__ import annotations

import os
import re
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
from api.services.pdf_service import render_pdf_pages, validate_pdf_document
from config import config
from utils.logging import get_logger

logger = get_logger(__name__)

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
ALLOWED_PDF_EXTENSIONS = {".pdf"}
ALLOWED_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_PDF_EXTENSIONS
MAX_FILE_SIZE = config.max_upload_size_bytes


def validate_image_file(file: UploadFile, content: bytes) -> tuple[bool, str, dict[str, Any]]:
    """Validate uploaded file (image or PDF) format, size, and visual quality."""
    if not file.filename:
        return False, "No filename provided", {}

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Unsupported file extension '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}", {}

    max_size = config.max_upload_size_bytes
    if len(content) > max_size:
        return False, f"File exceeds maximum upload size of {max_size / (1024 * 1024):.0f}MB (got {len(content) / (1024 * 1024):.1f}MB)", {}

    if len(content) == 0:
        return False, "Uploaded file is empty (0 bytes).", {}

    # Delegate PDF files to PDF validation service
    if ext in ALLOWED_PDF_EXTENSIONS:
        return validate_pdf_document(file, content)

    # Magic byte validation for image formats
    is_valid_image_header = (
        content.startswith(b"\x89PNG\r\n\x1a\n")  # PNG
        or content.startswith(b"\xff\xd8\xff")      # JPEG
        or content.startswith(b"BM")                # BMP
        or content.startswith(b"II*\x00")           # TIFF little-endian
        or content.startswith(b"MM\x00*")           # TIFF big-endian
    )
    if not is_valid_image_header:
        return False, "Corrupted image file or unrecognized image format header.", {}

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

    # Validate file format, size, and visual quality
    is_valid, validation_msg, quality_meta = validate_image_file(file, content)

    # For hard validation errors (unsupported extension, oversized, empty, corrupted, encrypted PDF),
    # reject immediately with HTTP 400 Bad Request
    if not is_valid and not quality_meta.get("is_blurry", False):
        raise HTTPException(
            status_code=200 if False else 400,
            detail=validation_msg,
        )

    # Determine student mapping
    student = None
    student_confidence = 1.0
    if student_id:
        student = db.query(Student).filter(Student.id == student_id, Student.is_active.is_(True)).first()
    elif student_usn:
        student = db.query(Student).filter(Student.usn == student_usn.strip(), Student.is_active.is_(True)).first()
        if not student:
            student_confidence = 0.3

    initial_status = "UPLOADED" if is_valid else "REUPLOAD_REQUIRED"
    scan_quality = quality_meta.get("quality", "POOR" if not is_valid else "ACCEPTABLE")

    script = AnswerScript(
        exam_id=exam.id,
        student_id=student.id if student else None,
        uploaded_by=uploader.id,
        original_filename=file.filename or "unknown.png",
        original_path="",  # set after directory creation below
        status=initial_status,
        scan_quality=scan_quality,
        student_identifier_confidence=student_confidence,
        uploaded_at=datetime.utcnow(),
    )
    db.add(script)
    db.flush()

    # Generate safe unique path following controlled storage hierarchy:
    # storage/answer_scripts/{academic_year}/{exam_id}/{script_id}/
    ext = Path(file.filename).suffix.lower() if file.filename else ".png"
    safe_uid = str(uuid.uuid4())[:12]
    year_str = re.sub(r"[^\w\-]", "_", exam.academic_year or "default")
    script_dir = config.storage_dir / "answer_scripts" / year_str / f"exam_{exam.id}" / f"script_{script.id}"
    orig_dir = script_dir / "original"
    pages_dir = script_dir / "pages"
    proc_dir = script_dir / "processed"
    debug_dir = script_dir / "debug"

    orig_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    proc_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)

    stored_path = orig_dir / f"original_{safe_uid}{ext}"
    with open(stored_path, "wb") as f:
        f.write(content)

    script.original_path = str(stored_path)

    # If document is a PDF, render pages sequentially to pages_dir at configured DPI (~300 DPI)
    if ext == ".pdf":
        try:
            render_pdf_pages(stored_path, pages_dir, dpi=config.pdf_render_dpi)
        except Exception as exc:
            logger.error("Failed rendering pages for PDF script #%d: %s", script.id, exc)
            if is_valid:
                # If page rendering failed unexpectedly, mark script as failed
                is_valid = False
                validation_msg = f"Failed rendering PDF pages: {str(exc)}"
                script.status = "REUPLOAD_REQUIRED"
                script.scan_quality = "POOR"

    db.commit()
    db.refresh(script)

    # If image/PDF failed quality check (e.g. blurry), immediately log a scan issue
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

    # Save new scan into original subfolder, preserving previous scans
    ext = Path(file.filename).suffix.lower() if file.filename else ".png"
    safe_uid = str(uuid.uuid4())[:12]
    exam = script.exam
    year_str = re.sub(r"[^\w\-]", "_", exam.academic_year or "default") if exam else "default"
    script_dir = config.storage_dir / "answer_scripts" / year_str / f"exam_{script.exam_id}" / f"script_{script.id}"
    orig_dir = script_dir / "original"
    orig_dir.mkdir(parents=True, exist_ok=True)
    new_path = orig_dir / f"rescan_{safe_uid}{ext}"

    with open(new_path, "wb") as f:
        f.write(content)

    # If replacement scan is a PDF, render pages
    if ext == ".pdf":
        pages_dir = script_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        render_pdf_pages(new_path, pages_dir, dpi=config.pdf_render_dpi)

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
