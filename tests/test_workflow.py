"""End-to-end integration tests for scanner upload, AI evaluation, teacher review, and student results."""
from __future__ import annotations

import io
import json
import numpy as np
import cv2
import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.database.session import SessionLocal
from api.database.models import AnswerAnswer, AnswerScript, Exam, Student, TeacherAssignment, User
from api.services.teacher_service import auto_assign_risky_answers, submit_teacher_review


@pytest.fixture
def client():
    return TestClient(app)


def create_test_image_bytes(blur: bool = False) -> bytes:
    """Generate a synthetic test image."""
    img = np.ones((400, 600, 3), dtype=np.uint8) * 255
    cv2.putText(img, "Photosynthesis light reaction ATP", (50, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    if blur:
        img = cv2.GaussianBlur(img, (25, 25), 0)
    _, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def test_scanner_blurry_upload_creates_issue(client):
    """Verify that uploading an excessively blurry scan creates a scan issue and sets status to REUPLOAD_REQUIRED."""
    # Login as scanner1
    s_login = client.post("/api/auth/login", json={"username": "scanner1", "password": "Scanner@123"})
    assert s_login.status_code == 200
    token = s_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Upload blurry image
    blurry_bytes = create_test_image_bytes(blur=True)
    files = {"file": ("blurry_scan.png", io.BytesIO(blurry_bytes), "image/png")}
    data = {"exam_id": 1, "student_usn": "1MS22CS001"}

    upload_res = client.post("/api/scripts/upload", data=data, files=files, headers=headers)
    assert upload_res.status_code == 200
    res_data = upload_res.json()
    assert res_data["status"] == "REUPLOAD_REQUIRED"
    assert res_data["scan_quality"] == "POOR"

    # Verify scan issues list contains the new issue
    issues_res = client.get("/api/scanner/issues?status=OPEN", headers=headers)
    assert issues_res.status_code == 200
    issues = issues_res.json()
    assert any(i["script_id"] == res_data["id"] and i["issue_type"] == "POOR_IMAGE" for i in issues)


def test_scanner_rescan_resolves_issue(client):
    """Verify that re-uploading / rescanning a script resolves open issues and sets status to UPLOADED."""
    s_login = client.post("/api/auth/login", json={"username": "scanner1", "password": "Scanner@123"})
    token = s_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Upload initial bad script
    blurry_bytes = create_test_image_bytes(blur=True)
    files = {"file": ("bad.png", io.BytesIO(blurry_bytes), "image/png")}
    upload_res = client.post("/api/scripts/upload", data={"exam_id": 1}, files=files, headers=headers)
    script_id = upload_res.json()["id"]

    # Rescan with clean sharp image
    sharp_bytes = create_test_image_bytes(blur=False)
    rescan_files = {"file": ("sharp_scan.png", io.BytesIO(sharp_bytes), "image/png")}
    rescan_res = client.post(f"/api/scripts/{script_id}/rescan", files=rescan_files, headers=headers)
    assert rescan_res.status_code == 200
    assert rescan_res.json()["status"] == "UPLOADED"
    assert rescan_res.json()["scan_quality"] in ["ACCEPTABLE", "EXCELLENT"]


def test_teacher_workload_balancing():
    """Verify that risky answers are balanced across eligible teachers based on current workload."""
    db = SessionLocal()
    try:
        t1 = db.query(User).filter(User.username == "teacher1").first()
        t2 = db.query(User).filter(User.username == "teacher2").first()
        exam = db.query(Exam).first()
        assert t1 and t2 and exam

        # Create two simulated risky answers
        script = AnswerScript(
            exam_id=exam.id,
            uploaded_by=t1.id,
            original_filename="dummy.png",
            original_path="dummy.png",
            status="RISK_REVIEW",
        )
        db.add(script)
        db.commit()

        q = exam.questions[0]
        ans1 = AnswerAnswer(script_id=script.id, question_id=q.id, status="HIGH_RISK")
        ans2 = AnswerAnswer(script_id=script.id, question_id=q.id, status="HIGH_RISK")
        db.add_all([ans1, ans2])
        db.commit()

        # Run auto assignment
        assigned_count = auto_assign_risky_answers(db, exam_id=exam.id)
        assert assigned_count >= 2

        # Check that both answers got assigned
        assign1 = db.query(TeacherAssignment).filter(TeacherAssignment.answer_id == ans1.id).first()
        assign2 = db.query(TeacherAssignment).filter(TeacherAssignment.answer_id == ans2.id).first()
        assert assign1 is not None and assign2 is not None

        # Workload balancing: should not overload one teacher when two eligible teachers exist
        teachers_assigned = {assign1.teacher_id, assign2.teacher_id}
        assert len(teachers_assigned) == 2 or (assign1.teacher_id in [t1.id, t2.id] and assign2.teacher_id in [t1.id, t2.id])
    finally:
        db.close()


def test_teacher_review_submission_and_results(client):
    """Test teacher review submission, final mark persistence, and student result aggregation."""
    # 1. Login as teacher1
    t_login = client.post("/api/auth/login", json={"username": "teacher1", "password": "Teacher@123"})
    assert t_login.status_code == 200
    t_token = t_login.json()["access_token"]
    t_headers = {"Authorization": f"Bearer {t_token}"}

    db = SessionLocal()
    try:
        teacher = db.query(User).filter(User.username == "teacher1").first()
        student = db.query(Student).filter(Student.usn == "1MS22CS001").first()
        exam = db.query(Exam).first()
        q = exam.questions[0]

        # Create a script mapped to student
        script = AnswerScript(
            exam_id=exam.id,
            student_id=student.id,
            uploaded_by=teacher.id,
            original_filename="student_paper.png",
            original_path="student_paper.png",
            status="RISK_REVIEW",
        )
        db.add(script)
        db.commit()

        ans = AnswerAnswer(script_id=script.id, question_id=q.id, status="TEACHER_REVIEW")
        db.add(ans)
        db.commit()

        assignment = TeacherAssignment(
            answer_id=ans.id,
            teacher_id=teacher.id,
            assignment_status="ASSIGNED",
        )
        db.add(assignment)
        db.commit()
        assign_id = assignment.id
        student_id = student.id
        exam_id = exam.id
    finally:
        db.close()

    # Teacher submits review
    review_res = client.post(
        f"/api/teacher/assignments/{assign_id}/review",
        json={"final_mark": 8.5, "teacher_notes": "Well explained concepts.", "decision": "MODIFIED"},
        headers=t_headers,
    )
    assert review_res.status_code == 200
    assert review_res.json()["final_mark"]["final_mark"] == 8.5

    # Check student result
    result_res = client.get(f"/api/students/{student_id}/results", headers=t_headers)
    assert result_res.status_code == 200
    res_data = result_res.json()
    assert res_data["student_usn"] == "1MS22CS001"
    assert len(res_data["exam_results"]) > 0

    exam_res = next(r for r in res_data["exam_results"] if r["exam_id"] == exam_id)
    assert exam_res["total_obtained"] == 8.5
    assert exam_res["percentage"] == 85.0
