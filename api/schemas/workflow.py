"""Pydantic schemas for scanning, evaluation, teacher review, and notifications."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


# ─── Script & Upload ───
class AnswerScriptResponse(BaseModel):
    id: int
    exam_id: int
    exam_name: str | None = None
    student_id: int | None = None
    student_name: str | None = None
    student_usn: str | None = None
    uploaded_by: int
    uploader_name: str | None = None
    original_filename: str
    original_path: str
    status: str
    scan_quality: str
    student_identifier_confidence: float
    uploaded_at: str | None = None
    processed_at: str | None = None
    issues_count: int = 0
    answers_count: int = 0


# ─── Answer & Evaluation ───
class AnswerResponse(BaseModel):
    id: int
    script_id: int
    question_id: int
    question_number: int | None = None
    image_path: str | None = None
    extracted_text: str | None = None
    ocr_confidence: float | None = None
    status: str
    created_at: str | None = None
    ai_evaluation: dict[str, Any] | None = None
    final_mark: dict[str, Any] | None = None


class TeacherReviewSubmit(BaseModel):
    final_mark: float = Field(..., ge=0)
    teacher_notes: str | None = None
    decision: str = Field(default="MODIFIED", description="APPROVED, MODIFIED, or OVERRIDDEN")


class ScanIssueResponse(BaseModel):
    id: int
    script_id: int
    script_filename: str | None = None
    reported_by: int | None = None
    reporter_name: str | None = None
    issue_type: str
    description: str
    severity: str
    status: str
    created_at: str | None = None
    resolved_at: str | None = None


class NotificationResponse(BaseModel):
    id: int
    user_id: int
    type: str
    title: str
    message: str
    reference_type: str | None = None
    reference_id: int | None = None
    is_read: bool
    created_at: str | None = None
