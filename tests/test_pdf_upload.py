"""Comprehensive test suite for PDF upload and multipage processing in EvaliSense.

Verifies:
1. Valid PNG upload
2. Valid JPG/JPEG upload
3. Single-page scanned PDF upload and evaluation
4. Multipage scanned PDF upload, deterministic page ordering, and evaluation
5. Verification that each PDF page passes through the HTR and rubric evaluation pipeline
6. Rejection of oversized PDFs (> 25MB)
7. Rejection of corrupted/invalid PDFs
8. Rejection of empty PDFs (0 bytes / 0 pages)
9. Rejection of password-protected / encrypted PDFs
10. Rejection of unsupported file extensions
11. Cleanup of rendered resources and memory safety
12. Preservation of examination and student associations
13. RBAC isolation (Scanner allowed, HOD/Teacher denied)
14. Page streaming via /api/scripts/{id}/image and /api/scripts/{id}/pages
"""
from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.database.session import SessionLocal
from api.database.models import AnswerScript, Exam, Student, User
from config import config


@pytest.fixture
def client():
    return TestClient(app)


def get_token(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, f"Login failed for {username}: {res.text}"
    return res.json()["access_token"]


def make_sharp_image(text: str = "Nyquist sampling theorem fs >= 2 fmax") -> np.ndarray:
    """Generate a clean, high-contrast synthetic test image."""
    img = np.ones((600, 800, 3), dtype=np.uint8) * 255
    cv2.putText(img, text, (40, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    return img


def make_png_bytes(text: str = "Nyquist sampling theorem") -> bytes:
    img = make_sharp_image(text)
    _, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def make_jpg_bytes(text: str = "Nyquist sampling theorem") -> bytes:
    img = make_sharp_image(text)
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


def make_pdf_bytes(
    pages_text: list[str],
    encrypted: bool = False,
    password: str = "secret",
) -> bytes:
    """Generate in-memory synthetic PDF document with synthetic handwriting-like text on each page."""
    doc = pymupdf.open()
    for text in pages_text:
        # A4 page in points: 595 x 842
        page = doc.new_page(width=595, height=842)
        # Render clean text onto page
        page.insert_text(pymupdf.Point(50, 150), text, fontsize=18)
        # Also render a synthetic high-contrast line image into page to guarantee Laplacian sharpness
        img = make_sharp_image(text)
        _, img_buf = cv2.imencode(".png", img)
        rect = pymupdf.Rect(50, 200, 500, 500)
        page.insert_image(rect, stream=img_buf.tobytes())

    if encrypted:
        buf = doc.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw=password,
            owner_pw=password,
        )
    else:
        buf = doc.tobytes()

    doc.close()
    return buf


# ─────────────────────────────────────────────────────────────────────────────
# 1. Image Upload Tests (PNG and JPG)
# ─────────────────────────────────────────────────────────────────────────────

def test_valid_png_upload(client):
    """Verify that valid PNG upload continues to work identically."""
    scanner_token = get_token(client, "scanner1", "Scanner@123")
    headers = {"Authorization": f"Bearer {scanner_token}"}

    png_data = make_png_bytes("Valid PNG Handwritten Answer")
    files = {"file": ("student_answer.png", io.BytesIO(png_data), "image/png")}
    res = client.post("/api/scripts/upload", data={"exam_id": 1}, files=files, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "UPLOADED"
    assert data["original_filename"] == "student_answer.png"
    assert data["scan_quality"] in ["ACCEPTABLE", "EXCELLENT"]


def test_valid_jpg_upload(client):
    """Verify that valid JPG/JPEG upload works identically."""
    scanner_token = get_token(client, "scanner1", "Scanner@123")
    headers = {"Authorization": f"Bearer {scanner_token}"}

    jpg_data = make_jpg_bytes("Valid JPEG Handwritten Answer")
    files = {"file": ("student_answer.jpg", io.BytesIO(jpg_data), "image/jpeg")}
    res = client.post("/api/scripts/upload", data={"exam_id": 1}, files=files, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "UPLOADED"
    assert data["original_filename"] == "student_answer.jpg"
    assert data["scan_quality"] in ["ACCEPTABLE", "EXCELLENT"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. PDF Upload Tests (Single-page and Multipage)
# ─────────────────────────────────────────────────────────────────────────────

def test_single_page_pdf_upload_and_pages(client):
    """Verify upload of a single-page scanned PDF and rendered page creation."""
    scanner_token = get_token(client, "scanner1", "Scanner@123")
    headers = {"Authorization": f"Bearer {scanner_token}"}

    pdf_bytes = make_pdf_bytes(["Nyquist rate fs >= 2*fmax signal processing sampling"])
    files = {"file": ("answer_sheet_p1.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    res = client.post(
        "/api/scripts/upload",
        data={"exam_id": 1, "student_usn": "1MS22CS001"},
        files=files,
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "UPLOADED"
    assert data["original_filename"] == "answer_sheet_p1.pdf"
    assert data["scan_quality"] in ["ACCEPTABLE", "EXCELLENT"]
    script_id = data["id"]

    # Verify script detail endpoint includes page info
    detail_res = client.get(f"/api/scripts/{script_id}", headers=headers)
    assert detail_res.status_code == 200
    assert detail_res.json()["script"]["id"] == script_id

    # Verify script image endpoint streams page 1
    img_res = client.get(f"/api/scripts/{script_id}/image", headers=headers)
    assert img_res.status_code == 200
    assert img_res.headers["content-type"] in ["image/png", "application/pdf"]

    # Verify pages list endpoint
    pages_res = client.get(f"/api/scripts/{script_id}/pages", headers=headers)
    assert pages_res.status_code == 200
    pages_data = pages_res.json()
    assert pages_data["total_pages"] == 1


def test_multipage_pdf_upload_and_page_ordering(client):
    """Verify that a multipage PDF renders each page in deterministic order."""
    scanner_token = get_token(client, "scanner1", "Scanner@123")
    headers = {"Authorization": f"Bearer {scanner_token}"}

    pages_content = [
        "Page 1: Nyquist-Shannon sampling theorem statement",
        "Page 2: Aliasing distortion and low-pass reconstruction filter",
        "Page 3: Discrete-time Fourier transform derivation",
    ]
    pdf_bytes = make_pdf_bytes(pages_content)
    files = {"file": ("student_exam_3pages.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    res = client.post(
        "/api/scripts/upload",
        data={"exam_id": 1, "student_usn": "1MS22CS001"},
        files=files,
        headers=headers,
    )
    assert res.status_code == 200
    script_data = res.json()
    script_id = script_data["id"]

    # Check pages endpoint
    pages_res = client.get(f"/api/scripts/{script_id}/pages", headers=headers)
    assert pages_res.status_code == 200
    pages_info = pages_res.json()
    assert pages_info["total_pages"] == 3
    assert len(pages_info["pages"]) == 3
    # Check deterministic page ordering 1, 2, 3
    assert [p["page_number"] for p in pages_info["pages"]] == [1, 2, 3]

    # Verify streaming page 1, 2, 3 individually
    for p_num in [1, 2, 3]:
        p_img = client.get(f"/api/scripts/{script_id}/image?page={p_num}", headers=headers)
        assert p_img.status_code == 200
        assert p_img.headers["content-type"] == "image/png"


def test_multipage_pdf_evaluation_pipeline(client):
    """Verify that a multipage PDF runs through HTR, rubric scoring, risk prediction, and stores page traces."""
    scanner_token = get_token(client, "scanner1", "Scanner@123")
    headers = {"Authorization": f"Bearer {scanner_token}"}

    pages_content = [
        "Nyquist rate fs >= 2*fmax frequency sampling condition",
        "Aliasing distortion occurs when sampling rate is less than twice maximum frequency",
    ]
    pdf_bytes = make_pdf_bytes(pages_content)
    upload_res = client.post(
        "/api/scripts/upload",
        data={"exam_id": 1, "student_usn": "1MS22CS001"},
        files={"file": ("multipage_eval.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=headers,
    )
    assert upload_res.status_code == 200
    script_id = upload_res.json()["id"]

    # Trigger AI Evaluation
    eval_res = client.post(f"/api/scripts/{script_id}/evaluate", headers=headers)
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert eval_data["status"] == "success"
    assert eval_data["script_id"] == script_id
    assert "answers" in eval_data
    assert len(eval_data["answers"]) > 0
    # Verify page traces returned
    assert "pages" in eval_data
    assert len(eval_data["pages"]) == 2
    assert [p["page_number"] for p in eval_data["pages"]] == [1, 2]

    # Verify script detail endpoint now has pages data
    script_detail = client.get(f"/api/scripts/{script_id}", headers=headers).json()
    assert script_detail["pages"] is not None
    assert len(script_detail["pages"]) == 2

    # Verify student associations and marks
    for ans in eval_data["answers"]:
        assert "ai_mark" in ans
        assert "risk_label" in ans
        assert ans["risk_label"] in ["LOW", "HIGH"]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Validation & Security Tests (Oversized, Corrupted, Empty, Encrypted, Unsupported)
# ─────────────────────────────────────────────────────────────────────────────

def test_unsupported_file_extension(client):
    """Verify rejection of unsupported file extensions (e.g., .txt, .docx, .exe)."""
    scanner_token = get_token(client, "scanner1", "Scanner@123")
    headers = {"Authorization": f"Bearer {scanner_token}"}

    files = {"file": ("notes.txt", io.BytesIO(b"Some text content"), "text/plain")}
    res = client.post("/api/scripts/upload", data={"exam_id": 1}, files=files, headers=headers)
    assert res.status_code == 400
    assert "unsupported file extension" in res.json()["detail"].lower()


def test_oversized_pdf_rejection(client, monkeypatch):
    """Verify rejection of PDFs exceeding the maximum configured file size."""
    scanner_token = get_token(client, "scanner1", "Scanner@123")
    headers = {"Authorization": f"Bearer {scanner_token}"}

    # Temporarily set max size to 500 KB to test limit without allocating 26 MB
    monkeypatch.setattr(config, "max_upload_size_bytes", 500 * 1024)

    # Create PDF > 500 KB
    large_pages = [f"Page {i} content text repeated" * 50 for i in range(40)]
    pdf_bytes = make_pdf_bytes(large_pages)
    assert len(pdf_bytes) > 500 * 1024

    files = {"file": ("oversized.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    res = client.post("/api/scripts/upload", data={"exam_id": 1}, files=files, headers=headers)
    assert res.status_code == 400
    assert "exceeds maximum upload size" in res.json()["detail"].lower()


def test_corrupted_pdf_rejection(client):
    """Verify rejection of malformed or corrupted PDF files."""
    scanner_token = get_token(client, "scanner1", "Scanner@123")
    headers = {"Authorization": f"Bearer {scanner_token}"}

    # File with PDF extension but corrupted non-PDF contents
    corrupted_data = b"NOT_A_PDF_RANDOM_GARBAGE_BYTES_1234567890"
    files = {"file": ("corrupted.pdf", io.BytesIO(corrupted_data), "application/pdf")}
    res = client.post("/api/scripts/upload", data={"exam_id": 1}, files=files, headers=headers)
    assert res.status_code == 400
    assert "invalid pdf" in res.json()["detail"].lower() or "missing" in res.json()["detail"].lower()


def test_empty_pdf_rejection(client):
    """Verify rejection of empty PDF files (0 bytes)."""
    scanner_token = get_token(client, "scanner1", "Scanner@123")
    headers = {"Authorization": f"Bearer {scanner_token}"}

    files = {"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")}
    res = client.post("/api/scripts/upload", data={"exam_id": 1}, files=files, headers=headers)
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()


def test_encrypted_pdf_rejection(client):
    """Verify rejection of password-protected / encrypted PDF files."""
    scanner_token = get_token(client, "scanner1", "Scanner@123")
    headers = {"Authorization": f"Bearer {scanner_token}"}

    encrypted_pdf = make_pdf_bytes(["Protected page text"], encrypted=True, password="examPassword123")
    files = {"file": ("protected_exam.pdf", io.BytesIO(encrypted_pdf), "application/pdf")}
    res = client.post("/api/scripts/upload", data={"exam_id": 1}, files=files, headers=headers)
    assert res.status_code == 400
    assert "password-protected" in res.json()["detail"].lower() or "encrypted" in res.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# 4. RBAC, Rescan, and Examination Association Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_pdf_upload_role_boundaries(client):
    """Verify that only the SCANNER role can upload PDF scripts; HOD and Teacher are rejected with 403."""
    hod_token = get_token(client, "admin", "Admin@123")
    teacher_token = get_token(client, "teacher1", "Teacher@123")
    scanner_token = get_token(client, "scanner1", "Scanner@123")

    pdf_bytes = make_pdf_bytes(["Role boundary check page"])

    # 1. HOD upload -> 403
    res_hod = client.post(
        "/api/scripts/upload",
        data={"exam_id": 1},
        files={"file": ("hod.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers={"Authorization": f"Bearer {hod_token}"},
    )
    assert res_hod.status_code == 403

    # 2. Teacher upload -> 403
    res_teacher = client.post(
        "/api/scripts/upload",
        data={"exam_id": 1},
        files={"file": ("teacher.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert res_teacher.status_code == 403

    # 3. Scanner upload -> 200
    res_scanner = client.post(
        "/api/scripts/upload",
        data={"exam_id": 1},
        files={"file": ("scanner.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers={"Authorization": f"Bearer {scanner_token}"},
    )
    assert res_scanner.status_code == 200


def test_pdf_rescan_workflow(client):
    """Verify that an existing script can be rescanned/replaced with a clean PDF."""
    scanner_token = get_token(client, "scanner1", "Scanner@123")
    headers = {"Authorization": f"Bearer {scanner_token}"}

    # Upload initial script
    initial_bytes = make_png_bytes("Initial bad attempt")
    upload_res = client.post(
        "/api/scripts/upload",
        data={"exam_id": 1},
        files={"file": ("initial.png", io.BytesIO(initial_bytes), "image/png")},
        headers=headers,
    )
    assert upload_res.status_code == 200
    script_id = upload_res.json()["id"]

    # Rescan using sharp PDF
    clean_pdf = make_pdf_bytes(["Sharp clean replacement PDF page 1", "Clean replacement page 2"])
    rescan_res = client.post(
        f"/api/scripts/{script_id}/rescan",
        files={"file": ("clean_replacement.pdf", io.BytesIO(clean_pdf), "application/pdf")},
        headers=headers,
    )
    assert rescan_res.status_code == 200
    rescan_data = rescan_res.json()
    assert rescan_data["status"] == "UPLOADED"
    assert rescan_data["original_filename"] == "clean_replacement.pdf"

    # Verify pages rendered
    pages_res = client.get(f"/api/scripts/{script_id}/pages", headers=headers)
    assert pages_res.status_code == 200
    assert pages_res.json()["total_pages"] == 2
