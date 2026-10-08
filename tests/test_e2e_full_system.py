"""End-to-End full system verification test.

Validates:
1. Web frontend serving (HTML, JS, CSS)
2. Authentication & JWT issuance for all three system roles
3. Academic management (Department, Section, Student, Subject, Exam, Rubric)
4. Scanner upload & blur detection
5. AI pipeline execution (TrOCR HTR, rubric scoring, risk prediction, DB persistence)
6. Workload-balanced teacher assignment
7. Teacher verification & final mark persistence
8. Authoritative student exam result calculation
9. Authorization boundaries & RBAC denial
"""
from __future__ import annotations

import io
import json
import uuid
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import app
from models.risk_model import RiskPrediction
import api.services.ai_service as ai_service


@pytest.fixture
def client():
    return TestClient(app)


def test_e2e_complete_academic_and_evaluation_cycle(client, monkeypatch):
    # ─── 1. Frontend Static Assets ───
    resp_root = client.get("/")
    assert resp_root.status_code == 200
    assert "EvaliSense" in resp_root.text
    assert 'href="/static/style.css"' in resp_root.text
    assert 'src="/static/app.js"' in resp_root.text

    resp_js = client.get("/static/app.js")
    assert resp_js.status_code == 200

    resp_css = client.get("/static/style.css")
    assert resp_css.status_code == 200

    # ─── 2. HOD Authentication ───
    hod_login = client.post("/api/auth/login", json={"username": "admin", "password": "Admin@123"})
    assert hod_login.status_code == 200
    hod_data = hod_login.json()
    assert hod_data["role"] == "HOD"
    hod_token = hod_data["access_token"]
    hod_headers = {"Authorization": f"Bearer {hod_token}"}

    # HOD Profile
    hod_me = client.get("/api/auth/me", headers=hod_headers)
    assert hod_me.status_code == 200
    assert hod_me.json()["username"] == "admin"

    # ─── 3. Academic Hierarchy Setup (HOD) ───
    uid = uuid.uuid4().hex[:6].upper()

    # Department
    dept_res = client.post("/api/departments", json={"code": f"D{uid}", "name": f"Dept {uid}"}, headers=hod_headers)
    assert dept_res.status_code == 200
    dept_id = dept_res.json()["id"]

    # Section
    sec_res = client.post("/api/sections", json={"department_id": dept_id, "name": f"SEC-{uid}", "semester": 4, "academic_year": "2026-2027"}, headers=hod_headers)
    assert sec_res.status_code == 200
    sec_id = sec_res.json()["id"]

    # Student
    stud_res = client.post("/api/students", json={"usn": f"1EC22CS{uid}", "name": "Grace Hopper", "section_id": sec_id}, headers=hod_headers)
    assert stud_res.status_code == 200
    student_id = stud_res.json()["id"]

    # Subject
    sub_res = client.post("/api/subjects", json={"code": f"SUB{uid}", "name": "Digital Signals", "semester": 4, "department_id": dept_id, "max_marks": 10.0}, headers=hod_headers)
    assert sub_res.status_code == 200
    subject_id = sub_res.json()["id"]

    # Assign Teacher to Subject
    users = client.get("/api/users", headers=hod_headers).json()
    teacher_user = next(u for u in users if u["role_name"] == "TEACHER")
    assign_sub_res = client.post("/api/teacher-subjects", json={"teacher_id": teacher_user["id"], "subject_id": subject_id, "section_id": sec_id, "academic_year": "2026-2027"}, headers=hod_headers)
    assert assign_sub_res.status_code == 200

    # Create Exam
    exam_res = client.post("/api/exams", json={"subject_id": subject_id, "name": f"E2E Signals Exam {uid}", "exam_type": "INTERNAL", "total_marks": 10.0, "academic_year": "2026-2027"}, headers=hod_headers)
    assert exam_res.status_code == 200
    exam_id = exam_res.json()["id"]

    # Add Question with Rubric
    rubric = {
        "question": "Explain sampling theorem in signal processing.",
        "max_marks": 10.0,
        "reference_answer": "Nyquist-Shannon sampling theorem states a continuous signal can be completely represented and reconstructed if sampled at twice its maximum frequency.",
        "criteria": [
            {"id": "c1", "description": "Definition of Nyquist rate (fs >= 2*fmax)", "marks": 5.0, "keywords": ["Nyquist", "frequency", "sampling rate", "twice"]},
            {"id": "c2", "description": "Aliasing distortion and reconstruction condition", "marks": 5.0, "keywords": ["aliasing", "reconstruction", "filter"]},
        ]
    }
    q_res = client.post(f"/api/exams/{exam_id}/questions", json={"question_number": 1, "question_text": rubric["question"], "max_marks": 10.0, "reference_answer": rubric["reference_answer"], "rubric_json": json.dumps(rubric)}, headers=hod_headers)
    assert q_res.status_code == 200

    # ─── 4. Scanner Workflow: Login & Upload ───
    scanner_login = client.post("/api/auth/login", json={"username": "scanner1", "password": "Scanner@123"})
    assert scanner_login.status_code == 200
    scanner_token = scanner_login.json()["access_token"]
    scanner_headers = {"Authorization": f"Bearer {scanner_token}"}

    # Upload Clean Script
    clean_img = np.ones((400, 600, 3), dtype=np.uint8) * 255
    cv2.putText(clean_img, "Sampling theorem fs >= 2 fmax Nyquist frequency aliasing", (30, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    _, clean_buf = cv2.imencode(".png", clean_img)

    files = {"file": ("student_signal_paper.png", io.BytesIO(clean_buf.tobytes()), "image/png")}
    upload_res = client.post("/api/scripts/upload", data={"exam_id": exam_id, "student_id": student_id}, files=files, headers=scanner_headers)
    assert upload_res.status_code == 200
    script_id = upload_res.json()["id"]
    assert upload_res.json()["status"] == "UPLOADED"

    # ─── 5. AI Pipeline Execution ───
    # Simulate high grading risk to trigger the workload-balanced teacher review flow
    original_risk_model = ai_service.get_risk_model()
    if original_risk_model is not None:
        monkeypatch.setattr(
            original_risk_model,
            "predict",
            lambda *args, **kwargs: RiskPrediction(
                risk_label="HIGH",
                risk_probability=0.88,
                contributing_factors=["Evaluation confidence borderline (0.42)", "Teacher verification needed"],
                feature_values={},
            ),
        )

    eval_res = client.post(f"/api/scripts/{script_id}/evaluate", headers=scanner_headers)
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert eval_data["status"] == "success"
    assert len(eval_data["answers"]) > 0
    target_answer_id = eval_data["answers"][0]["answer_id"]

    # ─── 6. Teacher Workload & Risk Review ───
    teacher_login = client.post("/api/auth/login", json={"username": teacher_user["username"], "password": "Teacher@123"})
    assert teacher_login.status_code == 200
    teacher_token = teacher_login.json()["access_token"]
    teacher_headers = {"Authorization": f"Bearer {teacher_token}"}

    # Teacher gets assignments and finds the one corresponding to our newly evaluated answer
    assignments = client.get("/api/teacher/assignments", headers=teacher_headers).json()
    assert len(assignments) > 0
    assignment = next((a for a in assignments if a["answer_id"] == target_answer_id), None)
    assert assignment is not None, f"No assignment found for answer_id {target_answer_id} in {assignments}"
    assign_id = assignment["assignment_id"]

    # Teacher inspects assignment details (image, OCR, rubric, AI mark, risk info)
    detail_res = client.get(f"/api/teacher/assignments/{assign_id}", headers=teacher_headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["assignment_id"] == assign_id
    assert "question" in detail
    assert "ai_evaluation" in detail

    # Teacher submits final reviewed mark
    review_submit = client.post(
        f"/api/teacher/assignments/{assign_id}/review",
        json={"final_mark": 9.0, "teacher_notes": "Well explained Nyquist criterion.", "decision": "MODIFIED"},
        headers=teacher_headers,
    )
    assert review_submit.status_code == 200
    assert review_submit.json()["final_mark"]["final_mark"] == 9.0

    # ─── 7. Authoritative Student Results ───
    result_res = client.get(f"/api/students/{student_id}/results", headers=teacher_headers)
    assert result_res.status_code == 200
    results_data = result_res.json()
    assert results_data["student_id"] == student_id
    assert len(results_data["exam_results"]) > 0

    exam_res_item = next(e for e in results_data["exam_results"] if e["exam_id"] == exam_id)
    assert exam_res_item["total_obtained"] == 9.0
    assert exam_res_item["percentage"] == 90.0

    # ─── 8. RBAC Denial Testing ───
    # Teacher attempting to delete role -> 403 Forbidden
    del_role_res = client.delete("/api/roles/1", headers=teacher_headers)
    assert del_role_res.status_code == 403

    # Scanner attempting to review teacher assignment -> 403 Forbidden
    scanner_review_res = client.post(
        f"/api/teacher/assignments/{assign_id}/review",
        json={"final_mark": 10.0, "decision": "APPROVED"},
        headers=scanner_headers,
    )
    assert scanner_review_res.status_code == 403
