"""Comprehensive test suite for Question Paper Upload, Automatic Marks Extraction,
and Complete Question Paper & Answer Key Document and Version Management in EvaliSense.

Verifies:
1. Marks Extraction Engine:
   - Section-level carry rules ("All questions carry 2 marks each", "5 x 2 = 10 Marks", "carrying 5 marks each").
   - Subquestion inline marks summation into parent question marks (e.g., (a) 2M + (b) 3M = 5M).
   - Marks extraction confidence levels (HIGH, MEDIUM, LOW) and provenance tracking.
   - Low confidence / missing marks correctly flagged as MARKS REQUIRED without hallucinated numbers.
   - Bulk marks assignment helper function (apply_bulk_marks_to_questions).
2. Question Paper Document & Version Management:
   - Uploading multiple versions increments version number (v1, v2).
   - Listing question papers includes metadata, versioning, and is_active flag.
   - Switching/activating a different question paper version.
   - Archiving and restoring question paper versions.
   - Academic integrity safeguard: preventing deletion of question papers when evaluated answer scripts exist.
   - Safe deletion of question paper versions when no evaluated scripts depend on them.
   - Secure downloading of question paper files.
3. Answer Key Document & Version Management:
   - AnswerKeyFile serialization provides backwards-compatible file_name and created_at fields (fixing File: undefined / Invalid Date).
   - Archiving and restoring answer key versions.
   - Academic integrity safeguard: preventing deletion of answer keys when evaluated answer scripts exist.
   - Safe deletion of unlinked/draft answer keys.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.database.session import SessionLocal
from api.database.models import (
    AnswerKeyFile,
    AnswerScript,
    Exam,
    ExamQuestion,
    QuestionPaperFile,
    User,
)
from api.services.question_extraction_service import (
    apply_bulk_marks_to_questions,
    extract_inline_mark_with_meta,
    parse_questions_from_text,
)


@pytest.fixture
def client():
    return TestClient(app)


def get_token(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, f"Login failed for {username}: {res.text}"
    return res.json()["access_token"]


# =============================================================================
# 1. Automatic Marks Extraction Engine Tests
# =============================================================================

class TestMarksExtractionEngine:
    """Tests for multi-strategy marks parsing, section rules, subquestions, and confidence."""

    def test_inline_marks_formats(self):
        """Test extraction of various standard inline marks formats."""
        cases = [
            ("Explain the architecture of 8086 microprocessor. [10 Marks]", 10.0),
            ("Explain the architecture of 8086 microprocessor. [5]", 5.0),
            ("State Coulomb's Law. (2 marks)", 2.0),
            ("Differentiate RAM and ROM. (4 Marks)", 4.0),
            ("Define polymorphism in OOP. Marks: 3", 3.0),
            ("What is a deadlock? 5M", 5.0),
            ("Solve the following differential equation. [12.5 Marks]", 12.5),
        ]
        for text, expected_mark in cases:
            mark, cleaned_text, source = extract_inline_mark_with_meta(text)
            assert mark == expected_mark, f"Failed for '{text}': got {mark}, expected {expected_mark}"
            assert source is not None

    def test_section_carry_each_rule(self):
        """Test 'All questions carry 2 marks each' section instruction."""
        text = """
DEPARTMENT OF COMPUTER SCIENCE
MIDTERM EXAMINATION

SECTION A
Answer all questions. All questions carry 2 marks each.

1. Define algorithm.
2. What is Big-O notation?
3. State the time complexity of binary search.

SECTION B
Answer all questions. Each question carries 5 marks.

4. Explain merge sort algorithm with example.
5. Discuss quicksort worst-case scenario.
"""
        questions, preamble, warnings = parse_questions_from_text(text)
        assert len(questions) == 5

        # Section A questions should inherit 2 marks (MEDIUM confidence)
        for q in questions[:3]:
            assert q["max_marks"] == 2.0
            assert q["confidence"] == "MEDIUM"
            assert "section" in q["marks_source"].lower()
            assert q["section"] == "SECTION A"

        # Section B questions should inherit 5 marks (MEDIUM confidence)
        for q in questions[3:]:
            assert q["max_marks"] == 5.0
            assert q["confidence"] == "MEDIUM"
            assert "section" in q["marks_source"].lower()
            assert q["section"] == "SECTION B"

    def test_section_multiplication_formula_rule(self):
        """Test section header with formula 'PART - A (10 x 2 = 20 Marks)'."""
        text = """
PART - A (5 x 2 = 10 Marks)
1. What is an operating system?
2. Define a process.
3. What is a thread?
4. Explain context switching.
5. Define mutual exclusion.

PART - B (2 x 10 = 20 Marks)
6. Describe paging and segmentation in memory management.
7. Explain Dijkstra's Banker's algorithm for deadlock avoidance.
"""
        questions, preamble, warnings = parse_questions_from_text(text)
        assert len(questions) == 7

        for q in questions[:5]:
            assert q["max_marks"] == 2.0
            assert q["confidence"] == "MEDIUM"
            assert "section" in q["marks_source"].lower()

        for q in questions[5:]:
            assert q["max_marks"] == 10.0
            assert q["confidence"] == "MEDIUM"
            assert "section" in q["marks_source"].lower()

    def test_subquestion_marks_summation(self):
        """Test subquestions with individual marks summing into parent question marks."""
        text = """
1. (a) Define linear convolution. [3 Marks]
   (b) Compute the convolution of x(n) and h(n). [7 Marks]

2. Explain sampling theorem and its significance. [10 Marks]
"""
        questions, preamble, warnings = parse_questions_from_text(text)
        assert len(questions) == 2

        q1 = questions[0]
        assert q1["question_number"] == 1
        assert len(q1["subquestions"]) == 2
        assert q1["subquestions"][0]["marks"] == 3.0
        assert q1["subquestions"][1]["marks"] == 7.0
        assert q1["max_marks"] == 10.0
        assert q1["confidence"] == "HIGH"
        assert "subquestion" in q1["marks_source"].lower()

        q2 = questions[1]
        assert q2["question_number"] == 2
        assert q2["max_marks"] == 10.0
        assert q2["confidence"] == "HIGH"

    def test_missing_marks_flagged_without_hallucination(self):
        """Test questions without any mark indications receive None and LOW confidence warning."""
        text = """
1. What is Ohm's law?
2. State Kirchhoff's current law.
"""
        questions, preamble, warnings = parse_questions_from_text(text)
        assert len(questions) == 2
        for q in questions:
            assert q["max_marks"] is None
            assert q["confidence"] == "LOW"
            assert any("MARKS REQUIRED" in w for w in q["warnings"])
        assert any("missing explicit mark allocations" in w for w in warnings)

    def test_bulk_marks_assignment_helper(self):
        """Test apply_bulk_marks_to_questions with multiple targeting modes."""
        questions = [
            {"question_number": 1, "max_marks": None, "section": "Part A"},
            {"question_number": 2, "max_marks": 2.0, "section": "Part A"},
            {"question_number": 3, "max_marks": None, "section": "Part B"},
            {"question_number": 4, "max_marks": 10.0, "section": "Part B"},
            {"question_number": 5, "max_marks": None, "section": "Part B"},
        ]

        # 1. Assign to unresolved only
        updated = apply_bulk_marks_to_questions(questions, filter_type="unresolved", filter_value=None, marks=5.0)
        assert updated[0]["max_marks"] == 5.0
        assert updated[1]["max_marks"] == 2.0  # Preserved
        assert updated[2]["max_marks"] == 5.0
        assert updated[3]["max_marks"] == 10.0  # Preserved
        assert updated[4]["max_marks"] == 5.0

        # 2. Assign to section only
        updated = apply_bulk_marks_to_questions(questions, filter_type="section", filter_value="Part A", marks=3.0)
        assert updated[0]["max_marks"] == 3.0
        assert updated[1]["max_marks"] == 3.0
        assert updated[3]["max_marks"] == 10.0  # Part B untouched

        # 3. Assign to range
        updated = apply_bulk_marks_to_questions(questions, filter_type="range", filter_value=[4, 5], marks=7.0)
        assert updated[3]["max_marks"] == 7.0
        assert updated[4]["max_marks"] == 7.0


# =============================================================================
# 2. Question Paper Document & Version Management Tests
# =============================================================================

class TestQuestionPaperManagement:
    """Tests for question paper upload, listing, activation, archiving, download, and deletion."""

    def test_question_paper_versioning_and_listing(self, client):
        """Uploading multiple question papers increments version and updates list."""
        teacher_token = get_token(client, "teacher1", "Teacher@123")
        headers = {"Authorization": f"Bearer {teacher_token}"}

        # Upload v1
        content_v1 = b"Q1. First version question. [5 Marks]"
        res1 = client.post(
            "/api/teacher/exams/1/upload-question-paper",
            files={"file": ("qp_v1.txt", io.BytesIO(content_v1), "text/plain")},
            headers=headers,
        )
        assert res1.status_code == 200, res1.text
        data1 = res1.json()
        assert data1["status"] == "success"
        v1_version = data1["version"]
        qp_id_1 = data1["question_paper"]["id"]

        # Upload v2
        content_v2 = b"Q1. Second version question. [5 Marks]\nQ2. Extra question. [5 Marks]"
        res2 = client.post(
            "/api/teacher/exams/1/upload-question-paper",
            files={"file": ("qp_v2.txt", io.BytesIO(content_v2), "text/plain")},
            headers=headers,
        )
        assert res2.status_code == 200, res2.text
        data2 = res2.json()
        assert data2["version"] == v1_version + 1
        qp_id_2 = data2["question_paper"]["id"]

        # List question papers
        res_list = client.get("/api/teacher/exams/1/question-papers", headers=headers)
        assert res_list.status_code == 200
        list_data = res_list.json()
        assert list_data["count"] >= 2
        assert list_data["active_question_paper"] is not None
        # Most recently uploaded should be active
        assert list_data["active_question_paper"]["id"] == qp_id_2

    def test_question_paper_activation_and_archiving(self, client):
        """Verify activating previous version and archiving a question paper."""
        teacher_token = get_token(client, "teacher1", "Teacher@123")
        headers = {"Authorization": f"Bearer {teacher_token}"}

        # Get existing question papers for exam 1
        res_list = client.get("/api/teacher/exams/1/question-papers", headers=headers)
        assert res_list.status_code == 200
        qps = res_list.json()["question_papers"]
        assert len(qps) >= 2

        older_qp = qps[-1]  # older version
        newer_qp = qps[0]   # newer version

        # Activate older version
        res_act = client.post(f"/api/teacher/exams/1/question-papers/{older_qp['id']}/activate", headers=headers)
        assert res_act.status_code == 200
        assert res_act.json()["question_paper"]["is_active"] is True

        # Archive newer version
        res_arch = client.post(f"/api/teacher/exams/1/question-papers/{newer_qp['id']}/archive", headers=headers)
        assert res_arch.status_code == 200
        assert res_arch.json()["question_paper"]["status"] == "ARCHIVED"

        # Restore newer version
        res_rest = client.post(f"/api/teacher/exams/1/question-papers/{newer_qp['id']}/restore", headers=headers)
        assert res_rest.status_code == 200
        assert res_rest.json()["question_paper"]["status"] == "ACTIVE"
        assert res_rest.json()["question_paper"]["is_active"] is True

    def test_question_paper_download_file(self, client):
        """Verify secure file download endpoint for question papers."""
        teacher_token = get_token(client, "teacher1", "Teacher@123")
        headers = {"Authorization": f"Bearer {teacher_token}"}

        # Upload a distinct file to download
        sample_text = b"EVALISENSE TEST QP CONTENT FOR DOWNLOAD VERIFICATION"
        res = client.post(
            "/api/teacher/exams/1/upload-question-paper",
            files={"file": ("test_dl.txt", io.BytesIO(sample_text), "text/plain")},
            headers=headers,
        )
        assert res.status_code == 200
        qp_id = res.json()["question_paper"]["id"]

        # Download file
        res_dl = client.get(f"/api/teacher/question-papers/{qp_id}/file", headers=headers)
        assert res_dl.status_code == 200
        assert sample_text in res_dl.content

    def test_question_paper_deletion_safeguard(self, client):
        """Question paper cannot be deleted if evaluated student scripts exist in the exam."""
        teacher_token = get_token(client, "teacher1", "Teacher@123")
        headers = {"Authorization": f"Bearer {teacher_token}"}

        # Exam 1 has evaluated student scripts from seeding or pipeline
        # Attempting to delete its active question paper should be blocked
        res_list = client.get("/api/teacher/exams/1/question-papers", headers=headers)
        qps = res_list.json()["question_papers"]
        assert len(qps) > 0
        target_qp_id = qps[0]["id"]

        # Check if exam 1 has completed/evaluated scripts
        db = SessionLocal()
        try:
            has_eval = (
                db.query(AnswerScript)
                .filter(
                    AnswerScript.exam_id == 1,
                    AnswerScript.status.in_(["EVALUATED", "COMPLETED", "TEACHER_REVIEW", "FINALIZED"]),
                )
                .first()
                is not None
            )
        finally:
            db.close()

        res_del = client.delete(f"/api/teacher/exams/1/question-papers/{target_qp_id}", headers=headers)
        if has_eval:
            assert res_del.status_code == 400
            assert "Cannot delete" in res_del.json()["detail"]
            assert "archive" in res_del.json()["detail"].lower()
        else:
            # If no evaluated scripts, deletion succeeds safely
            assert res_del.status_code == 200


# =============================================================================
# 3. Answer Key Document & Version Management Tests
# =============================================================================

class TestAnswerKeyManagement:
    """Tests for answer key serialization compatibility, archiving, restoring, and deletion safeguards."""

    def test_answer_key_dict_serialization_compatibility(self, client):
        """AnswerKeyFile.to_dict() must provide both original_filename/uploaded_at and file_name/created_at."""
        db = SessionLocal()
        try:
            ak = db.query(AnswerKeyFile).filter(AnswerKeyFile.exam_id == 1).first()
            assert ak is not None, "Exam 1 must have at least one answer key record."
            ak_dict = ak.to_dict()

            # Backwards-compatible aliases preventing frontend 'File: undefined' and 'Invalid Date'
            assert "file_name" in ak_dict
            assert "original_filename" in ak_dict
            assert ak_dict["file_name"] == ak_dict["original_filename"]

            assert "created_at" in ak_dict
            assert "uploaded_at" in ak_dict
            assert ak_dict["created_at"] is not None

            assert "status" in ak_dict
            assert ak_dict["status"] in ["ACTIVE", "ARCHIVED", "DELETED"]
        finally:
            db.close()

    def test_answer_key_archive_and_restore(self, client):
        """Verify archiving and restoring an answer key version."""
        teacher_token = get_token(client, "teacher1", "Teacher@123")
        headers = {"Authorization": f"Bearer {teacher_token}"}

        # Create a new answer key version for testing archive/restore
        dummy_content = b"Answer Key vTest for EvaliSense"
        res_upload = client.post(
            "/api/teacher/exams/1/answer-key",
            files={"file": ("key_test.txt", io.BytesIO(dummy_content), "text/plain")},
            data={"questions_json": json.dumps([{"question_number": 1, "max_marks": 5}])},
            headers=headers,
        )
        assert res_upload.status_code == 200
        key_id = res_upload.json()["answer_key"]["id"]

        # Archive the answer key
        res_arch = client.post(f"/api/teacher/exams/1/answer-keys/{key_id}/archive", headers=headers)
        assert res_arch.status_code == 200
        assert res_arch.json()["answer_key"]["status"] == "ARCHIVED"
        assert res_arch.json()["answer_key"]["is_active"] is False

        # Restore the answer key
        res_rest = client.post(f"/api/teacher/exams/1/answer-keys/{key_id}/restore", headers=headers)
        assert res_rest.status_code == 200
        assert res_rest.json()["answer_key"]["status"] == "ACTIVE"
        assert res_rest.json()["answer_key"]["is_active"] is True

    def test_answer_key_deletion_safeguard(self, client):
        """Answer key cannot be deleted if evaluated scripts exist for the exam."""
        teacher_token = get_token(client, "teacher1", "Teacher@123")
        headers = {"Authorization": f"Bearer {teacher_token}"}

        db = SessionLocal()
        try:
            ak = db.query(AnswerKeyFile).filter(AnswerKeyFile.exam_id == 1, AnswerKeyFile.is_active == True).first()
            assert ak is not None
            key_id = ak.id

            has_eval = (
                db.query(AnswerScript)
                .filter(
                    AnswerScript.exam_id == 1,
                    AnswerScript.status.in_(["EVALUATED", "COMPLETED", "TEACHER_REVIEW", "FINALIZED"]),
                )
                .first()
                is not None
            )
        finally:
            db.close()

        res_del = client.delete(f"/api/teacher/exams/1/answer-keys/{key_id}", headers=headers)
        if has_eval:
            assert res_del.status_code == 400
            assert "Cannot delete" in res_del.json()["detail"]
            assert "archive" in res_del.json()["detail"].lower()
        else:
            assert res_del.status_code == 200
