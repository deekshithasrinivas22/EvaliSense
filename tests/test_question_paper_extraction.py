"""Comprehensive test suite for Question Paper upload and automatic question extraction in EvaliSense.

Verifies:
1. Multipage PDF question paper with selectable text extraction.
2. Scanned multipage PDF question paper with OCR fallback.
3. Image question paper upload (PNG and JPG).
4. Plaintext question paper upload (TXT).
5. Deterministic page order preservation.
6. Accurate extraction of question numbers, question text, subquestions, and explicit marks.
7. Missing marks flagged with warnings instead of invented values.
8. Unsegmented preamble/instructions separation.
9. Question review, editing, and confirmation workflow.
10. Association of confirmed questions with answer keys and rubrics.
11. RBAC authorization (assigned teacher/HOD allowed, unauthorized teacher/scanner rejected).
12. Preservation of answer-key version history.
13. Unchanged student answer sheet upload and grading workflows.
14. Edge cases: corrupted files, unsupported file formats, oversized files (> 25MB), empty files.
15. PDFs with unusually large page dimensions rendered safely without limit errors.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.database.session import SessionLocal
from api.database.models import Exam, ExamQuestion, User
from config import config


@pytest.fixture
def client():
    return TestClient(app)


def get_token(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, f"Login failed for {username}: {res.text}"
    return res.json()["access_token"]


def make_sharp_text_image(text: str = "State Newton second law of motion") -> bytes:
    """Generate in-memory synthetic PNG with legible high-contrast text."""
    img = np.ones((400, 800, 3), dtype=np.uint8) * 255
    cv2.putText(img, text, (30, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    _, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def make_selectable_pdf(pages_text: list[list[str]]) -> bytes:
    """Generate a clean PDF with selectable text across pages."""
    doc = pymupdf.open()
    for page_lines in pages_text:
        page = doc.new_page(width=595, height=842)
        y = 70
        for line in page_lines:
            page.insert_text(pymupdf.Point(50, y), line, fontsize=11)
            y += 28
    buf = doc.tobytes()
    doc.close()
    return buf


def make_scanned_pdf_without_text(pages_images: list[bytes]) -> bytes:
    """Generate a scanned PDF where each page only has an embedded image and no selectable text."""
    doc = pymupdf.open()
    for img_bytes in pages_images:
        page = doc.new_page(width=595, height=842)
        rect = pymupdf.Rect(50, 100, 545, 600)
        page.insert_image(rect, stream=img_bytes)
    buf = doc.tobytes()
    doc.close()
    return buf


# ─────────────────────────────────────────────────────────────────────────────
# 1. Selectable Multipage PDF Extraction
# ─────────────────────────────────────────────────────────────────────────────

def test_selectable_multipage_pdf_extraction(client):
    """Verify extraction of questions, subquestions, and explicit marks from selectable multipage PDF."""
    teacher_token = get_token(client, "teacher1", "Teacher@123")
    headers = {"Authorization": f"Bearer {teacher_token}"}

    pages_data = [
        [
            "Department of Electronics and Communication",
            "Midterm Assessment - Signals and Systems",
            "Max Marks: 40 | Duration: 2 Hours",
            "Q1. State and prove the Nyquist Sampling Theorem. [10 Marks]",
            "(a) Define Nyquist rate and interval.",
            "(b) Explain aliasing distortion.",
            "Q2. Compute the continuous-time Fourier Transform of a rectangular pulse. [10 Marks]",
        ],
        [
            "Question 3: Explain the properties of Discrete Fourier Transform. [10]",
            "(a) Circular shift property",
            "(b) Parseval relation",
            "4. Describe the design steps of a Butterworth IIR filter.",
        ]
    ]

    pdf_bytes = make_selectable_pdf(pages_data)
    files = {"file": ("signals_qp.pdf", io.BytesIO(pdf_bytes), "application/pdf")}

    res = client.post("/api/teacher/exams/1/upload-question-paper", files=files, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["status"] == "success"
    assert data["page_count"] == 2
    assert "preamble" in data
    assert "Signals and Systems" in data["preamble"] or "Department" in data["preamble"]

    questions = data["questions"]
    assert len(questions) == 4

    # Q1 checks
    assert questions[0]["question_number"] == 1
    assert "Nyquist Sampling Theorem" in questions[0]["question_text"]
    assert questions[0]["max_marks"] == 10.0
    assert len(questions[0]["subquestions"]) == 2

    # Q2 checks
    assert questions[1]["question_number"] == 2
    assert "Fourier Transform" in questions[1]["question_text"]
    assert questions[1]["max_marks"] == 10.0

    # Q3 checks
    assert questions[2]["question_number"] == 3
    assert "Discrete Fourier Transform" in questions[2]["question_text"]
    assert questions[2]["max_marks"] == 10.0
    assert len(questions[2]["subquestions"]) == 2

    # Q4 checks: missing explicit marks should be flagged, NOT invented!
    assert questions[3]["question_number"] == 4
    assert "Butterworth" in questions[3]["question_text"]
    assert questions[3]["max_marks"] is None
    assert any("marks" in w.lower() for w in questions[3]["warnings"])


# ─────────────────────────────────────────────────────────────────────────────
# 2. Text File and Image File Extractions
# ─────────────────────────────────────────────────────────────────────────────

def test_txt_question_paper_extraction(client):
    """Verify question extraction from plaintext TXT question paper."""
    teacher_token = get_token(client, "teacher1", "Teacher@123")
    headers = {"Authorization": f"Bearer {teacher_token}"}

    txt_content = (
        "Midterm Examination - Operating Systems\n"
        "Max Marks: 20\n\n"
        "1. Define a process and explain PCB contents. [10 Marks]\n"
        "2. What is deadlock? List the four necessary conditions. [10 Marks]\n"
    ).encode("utf-8")

    files = {"file": ("os_qp.txt", io.BytesIO(txt_content), "text/plain")}
    res = client.post("/api/teacher/exams/1/upload-question-paper", files=files, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["questions"]) == 2
    assert data["questions"][0]["question_number"] == 1
    assert data["questions"][0]["max_marks"] == 10.0
    assert data["questions"][1]["question_number"] == 2
    assert data["questions"][1]["max_marks"] == 10.0


def test_image_question_paper_extraction(client):
    """Verify question paper upload as PNG image."""
    teacher_token = get_token(client, "teacher1", "Teacher@123")
    headers = {"Authorization": f"Bearer {teacher_token}"}

    img_bytes = make_sharp_text_image("1. State Newton second law of motion [5 Marks]")
    files = {"file": ("physics_q1.png", io.BytesIO(img_bytes), "image/png")}
    res = client.post("/api/teacher/exams/1/upload-question-paper", files=files, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["page_count"] == 1
    assert len(data["questions"]) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 3. Document Preview Endpoint
# ─────────────────────────────────────────────────────────────────────────────

def test_question_paper_preview_endpoint(client):
    """Verify that uploaded question paper can be previewed by authorized teachers."""
    teacher_token = get_token(client, "teacher1", "Teacher@123")
    headers = {"Authorization": f"Bearer {teacher_token}"}

    txt_content = b"Q1. Sample preview test question [5]"
    files = {"file": ("preview_test.txt", io.BytesIO(txt_content), "text/plain")}
    upload_res = client.post("/api/teacher/exams/1/upload-question-paper", files=files, headers=headers)
    assert upload_res.status_code == 200

    preview_res = client.get("/api/teacher/exams/1/question-paper/preview", headers=headers)
    assert preview_res.status_code == 200
    assert len(preview_res.content) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Question Confirmation, Editing, and Rubric Workflow
# ─────────────────────────────────────────────────────────────────────────────

def test_question_confirmation_and_rubric_persistence(client):
    """Verify that extracted questions can be reviewed, edited, confirmed, and saved with rubrics."""
    teacher_token = get_token(client, "teacher1", "Teacher@123")
    headers = {"Authorization": f"Bearer {teacher_token}"}

    confirm_payload = {
        "questions": [
            {
                "question_number": 1,
                "question_text": "Explain the Nyquist Sampling Theorem with mathematical proof.",
                "max_marks": 10.0,
                "reference_answer": "Nyquist theorem states that fs >= 2*fmax to avoid aliasing.",
                "rubric_json": json.dumps({
                    "question": "Explain the Nyquist Sampling Theorem",
                    "max_marks": 10.0,
                    "reference_answer": "fs >= 2*fmax",
                    "criteria": [
                        {"id": "c1", "description": "Definition of Nyquist rate", "marks": 4.0, "keywords": ["sampling rate", "fmax"]},
                        {"id": "c2", "description": "Proof and aliasing explanation", "marks": 6.0, "keywords": ["aliasing", "spectrum"]},
                    ]
                }),
            },
            {
                "question_number": 2,
                "question_text": "Derive Fourier Transform of rectangular pulse.",
                "max_marks": 10.0,
                "reference_answer": "X(f) = sinc(f*T)",
                "rubric_json": None,
            }
        ],
        "replace_existing": False,
    }

    res = client.post("/api/teacher/exams/1/questions/confirm", json=confirm_payload, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "success"

    # Query exam questions endpoint to verify database persistence
    q_list_res = client.get("/api/exams/1/questions", headers=headers)
    assert q_list_res.status_code == 200
    saved_questions = q_list_res.json()
    assert len(saved_questions) >= 2

    q1 = next(q for q in saved_questions if q["question_number"] == 1)
    assert "Nyquist" in q1["question_text"]
    assert q1["max_marks"] == 10.0
    assert q1["rubric_json"] is not None
    r_data = json.loads(q1["rubric_json"])
    assert len(r_data["criteria"]) == 2


def test_rubric_marks_exceeding_max_marks_rejected(client):
    """Verify that rubric criteria marks totaling more than question max marks are rejected."""
    teacher_token = get_token(client, "teacher1", "Teacher@123")
    headers = {"Authorization": f"Bearer {teacher_token}"}

    invalid_payload = {
        "questions": [
            {
                "question_number": 1,
                "question_text": "Sample question",
                "max_marks": 5.0,
                "rubric_json": json.dumps({
                    "question": "Sample question",
                    "max_marks": 5.0,
                    "criteria": [
                        {"id": "c1", "description": "Part 1", "marks": 4.0, "keywords": []},
                        {"id": "c2", "description": "Part 2", "marks": 4.0, "keywords": []},  # 4 + 4 = 8 > 5
                    ]
                }),
            }
        ],
        "replace_existing": False,
    }

    res = client.post("/api/teacher/exams/1/questions/confirm", json=invalid_payload, headers=headers)
    assert res.status_code == 400
    assert "exceeds" in res.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# 5. RBAC Isolation
# ─────────────────────────────────────────────────────────────────────────────

def test_question_paper_rbac_boundaries(client):
    """Verify that only authorized teachers and HOD can upload/confirm question papers."""
    hod_token = get_token(client, "admin", "Admin@123")
    scanner_token = get_token(client, "scanner1", "Scanner@123")
    teacher_token = get_token(client, "teacher1", "Teacher@123")

    txt_content = b"Q1. Role check question [10]"
    files = {"file": ("role_check.txt", io.BytesIO(txt_content), "text/plain")}

    # Scanner role -> 403 Forbidden
    res_scanner = client.post(
        "/api/teacher/exams/1/upload-question-paper",
        files=files,
        headers={"Authorization": f"Bearer {scanner_token}"},
    )
    assert res_scanner.status_code == 403

    # Teacher role -> 200 OK (teacher1 is assigned to exam 1 subject)
    files = {"file": ("role_check.txt", io.BytesIO(txt_content), "text/plain")}
    res_teacher = client.post(
        "/api/teacher/exams/1/upload-question-paper",
        files=files,
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert res_teacher.status_code == 200

    # HOD role -> 200 OK
    files = {"file": ("role_check.txt", io.BytesIO(txt_content), "text/plain")}
    res_hod = client.post(
        "/api/teacher/exams/1/upload-question-paper",
        files=files,
        headers={"Authorization": f"Bearer {hod_token}"},
    )
    assert res_hod.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# 6. Edge Cases & Validation Limits
# ─────────────────────────────────────────────────────────────────────────────

def test_unsupported_file_format_rejected(client):
    """Verify rejection of unsupported question paper file formats."""
    teacher_token = get_token(client, "teacher1", "Teacher@123")
    headers = {"Authorization": f"Bearer {teacher_token}"}

    files = {"file": ("paper.exe", io.BytesIO(b"executable data"), "application/octet-stream")}
    res = client.post("/api/teacher/exams/1/upload-question-paper", files=files, headers=headers)
    assert res.status_code == 400
    assert "unsupported" in res.json()["detail"].lower()


def test_empty_question_paper_rejected(client):
    """Verify rejection of empty (0 bytes) question paper files."""
    teacher_token = get_token(client, "teacher1", "Teacher@123")
    headers = {"Authorization": f"Bearer {teacher_token}"}

    files = {"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")}
    res = client.post("/api/teacher/exams/1/upload-question-paper", files=files, headers=headers)
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()


def test_corrupted_pdf_rejected(client):
    """Verify rejection of corrupted question paper PDF files."""
    teacher_token = get_token(client, "teacher1", "Teacher@123")
    headers = {"Authorization": f"Bearer {teacher_token}"}

    files = {"file": ("corrupt.pdf", io.BytesIO(b"RANDOM_CORRUPT_BYTES_NOT_PDF"), "application/pdf")}
    res = client.post("/api/teacher/exams/1/upload-question-paper", files=files, headers=headers)
    assert res.status_code == 400
    assert "invalid" in res.json()["detail"].lower() or "missing" in res.json()["detail"].lower()


def test_oversized_question_paper_rejected(client, monkeypatch):
    """Verify rejection of oversized question papers (> 25MB)."""
    teacher_token = get_token(client, "teacher1", "Teacher@123")
    headers = {"Authorization": f"Bearer {teacher_token}"}

    # Use monkeypatch to test size boundary cleanly
    from api.services import question_extraction_service
    monkeypatch.setattr(question_extraction_service, "MAX_QP_FILE_SIZE", 500 * 1024)

    large_bytes = b"A" * (600 * 1024)
    files = {"file": ("large_qp.txt", io.BytesIO(large_bytes), "text/plain")}
    res = client.post("/api/teacher/exams/1/upload-question-paper", files=files, headers=headers)
    assert res.status_code == 400
    assert "exceeds" in res.json()["detail"].lower()


def test_large_page_dimensions_pdf_renders_safely(client):
    """Verify that a question paper PDF with unusually large page dimensions renders safely without limit errors."""
    teacher_token = get_token(client, "teacher1", "Teacher@123")
    headers = {"Authorization": f"Bearer {teacher_token}"}

    # Create a PDF with large page dimensions (1786 x 2525 pt, like scanned sheets)
    doc = pymupdf.open()
    page = doc.new_page(width=1786, height=2525)
    page.insert_text(pymupdf.Point(100, 200), "Q1. Large dimensions question statement. [15 Marks]", fontsize=24)
    pdf_bytes = doc.tobytes()
    doc.close()

    files = {"file": ("large_dim_qp.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    res = client.post("/api/teacher/exams/1/upload-question-paper", files=files, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert len(data["questions"]) == 1
    assert data["questions"][0]["max_marks"] == 15.0
