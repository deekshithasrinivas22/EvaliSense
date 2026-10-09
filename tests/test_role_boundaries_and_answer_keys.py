"""Comprehensive tests for strict role boundaries, answer key versioning, and exam evaluation."""
from __future__ import annotations

import io
import json
import uuid
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.database.session import SessionLocal
from api.database.models import (
    User, Subject, Exam, ExamQuestion,
    AnswerScript, AnswerAnswer, TeacherAssignment
)


@pytest.fixture
def client():
    return TestClient(app)


def get_token(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, f"Login failed for {username}: {res.text}"
    return res.json()["access_token"]


def make_valid_png_bytes(text: str = "Handwritten answer script text sample") -> bytes:
    img = np.ones((400, 600, 3), dtype=np.uint8) * 255
    cv2.putText(img, text, (30, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    _, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def test_script_upload_role_boundaries(client):
    """Verify that ONLY the SCANNER role can upload scripts; HOD and Teacher are rejected with 403."""
    hod_token = get_token(client, "admin", "Admin@123")
    teacher_token = get_token(client, "teacher1", "Teacher@123")
    scanner_token = get_token(client, "scanner1", "Scanner@123")

    img_bytes = make_valid_png_bytes("Student Script Upload Verification")

    # 1. HOD tries to upload via /api/scripts/upload -> 403 Forbidden
    res_hod = client.post(
        "/api/scripts/upload",
        data={"exam_id": 1, "student_usn": "1MS22CS001"},
        files={"file": ("script.png", io.BytesIO(img_bytes), "image/png")},
        headers={"Authorization": f"Bearer {hod_token}"},
    )
    assert res_hod.status_code == 403
    assert "scanner" in res_hod.json()["detail"].lower()

    # 2. HOD tries to upload via /api/scanner/scripts/upload -> 403 Forbidden
    res_hod_scanner_route = client.post(
        "/api/scanner/scripts/upload",
        data={"exam_id": 1, "student_usn": "1MS22CS001"},
        files={"file": ("script.png", io.BytesIO(img_bytes), "image/png")},
        headers={"Authorization": f"Bearer {hod_token}"},
    )
    assert res_hod_scanner_route.status_code == 403

    # 3. Teacher tries to upload via /api/scripts/upload -> 403 Forbidden
    res_teacher = client.post(
        "/api/scripts/upload",
        data={"exam_id": 1, "student_usn": "1MS22CS001"},
        files={"file": ("script.png", io.BytesIO(img_bytes), "image/png")},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert res_teacher.status_code == 403

    # 4. Teacher tries to upload via /api/scanner/scripts/upload -> 403 Forbidden
    res_teacher_scanner_route = client.post(
        "/api/scanner/scripts/upload",
        data={"exam_id": 1, "student_usn": "1MS22CS001"},
        files={"file": ("script.png", io.BytesIO(img_bytes), "image/png")},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert res_teacher_scanner_route.status_code == 403

    # 5. Scanner CAN upload successfully via /api/scripts/upload
    res_scanner = client.post(
        "/api/scripts/upload",
        data={"exam_id": 1, "student_usn": "1MS22CS001"},
        files={"file": ("script.png", io.BytesIO(img_bytes), "image/png")},
        headers={"Authorization": f"Bearer {scanner_token}"},
    )
    assert res_scanner.status_code == 200
    script_data = res_scanner.json()
    assert "id" in script_data
    assert script_data["exam_id"] == 1


def test_script_rescan_role_boundaries(client):
    """Verify that ONLY the SCANNER role can re-upload/rescan; HOD and Teacher are rejected with 403."""
    hod_token = get_token(client, "admin", "Admin@123")
    teacher_token = get_token(client, "teacher1", "Teacher@123")
    scanner_token = get_token(client, "scanner1", "Scanner@123")

    img_bytes = make_valid_png_bytes("Clean Rescan Image")

    # 1. HOD tries to rescan -> 403 Forbidden
    res_hod = client.post(
        "/api/scripts/1/rescan",
        files={"file": ("clean_scan.png", io.BytesIO(img_bytes), "image/png")},
        headers={"Authorization": f"Bearer {hod_token}"},
    )
    assert res_hod.status_code == 403

    # 2. Teacher tries to rescan -> 403 Forbidden
    res_teacher = client.post(
        "/api/scripts/1/rescan",
        files={"file": ("clean_scan.png", io.BytesIO(img_bytes), "image/png")},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert res_teacher.status_code == 403

    # 3. Scanner CAN rescan via /api/scripts/1/rescan
    res_scanner = client.post(
        "/api/scripts/1/rescan",
        files={"file": ("clean_scan.png", io.BytesIO(img_bytes), "image/png")},
        headers={"Authorization": f"Bearer {scanner_token}"},
    )
    assert res_scanner.status_code == 200
    assert res_scanner.json()["status"] == "UPLOADED"


def test_answer_key_role_boundaries_and_versioning(client):
    """Verify answer key management: Teacher allowed for assigned exam, versioning archives older versions,
    Scanner blocked, unassigned Teacher blocked."""
    hod_token = get_token(client, "admin", "Admin@123")
    teacher1_token = get_token(client, "teacher1", "Teacher@123")
    scanner_token = get_token(client, "scanner1", "Scanner@123")

    # Exam 1 is in CS501 (assigned to teacher1)
    # 1. Scanner is denied access to answer key upload -> 403
    key_file_v1 = ("key_v1.txt", io.BytesIO(b"Official Answer Key Version 1 content"), "text/plain")
    res_scanner = client.post(
        "/api/teacher/exams/1/answer-key",
        files={"file": key_file_v1},
        headers={"Authorization": f"Bearer {scanner_token}"},
    )
    assert res_scanner.status_code == 403

    # 2. Teacher1 uploads version 1 for assigned exam 1 -> 200 OK
    res_v1 = client.post(
        "/api/teacher/exams/1/answer-key",
        files={"file": ("key_v1.txt", io.BytesIO(b"Official Answer Key Version 1 content"), "text/plain")},
        headers={"Authorization": f"Bearer {teacher1_token}"},
    )
    assert res_v1.status_code == 200
    v1_data = res_v1.json()
    v1_key = v1_data["answer_key"]
    assert v1_key["version"] >= 1
    assert v1_key["is_active"] is True
    key1_id = v1_key["id"]

    # 3. Teacher1 uploads next version for assigned exam 1 -> 200 OK (new active, old archived)
    res_v2 = client.post(
        "/api/teacher/exams/1/answer-key",
        files={"file": ("key_v2.txt", io.BytesIO(b"Official Answer Key Version 2 updated"), "text/plain")},
        headers={"Authorization": f"Bearer {teacher1_token}"},
    )
    assert res_v2.status_code == 200
    v2_data = res_v2.json()
    v2_key = v2_data["answer_key"]
    assert v2_key["version"] > v1_key["version"]
    assert v2_key["is_active"] is True
    key2_id = v2_key["id"]

    # Verify key list has active version and past version archived
    res_list = client.get(
        "/api/teacher/exams/1/answer-key",
        headers={"Authorization": f"Bearer {teacher1_token}"},
    )
    assert res_list.status_code == 200
    list_data = res_list.json()
    assert list_data["has_active_key"] is True
    assert list_data["active_key"]["id"] == key2_id
    assert len(list_data["versions"]) >= 2
    # Ensure version 1 is archived
    v1_record = next(v for v in list_data["versions"] if v["id"] == key1_id)
    assert v1_record["is_active"] is False

    # 4. Download answer key file via secure endpoint
    res_dl = client.get(
        f"/api/teacher/answer-keys/{key2_id}/file",
        headers={"Authorization": f"Bearer {teacher1_token}"},
    )
    assert res_dl.status_code == 200
    assert b"Version 2 updated" in res_dl.content

    # 5. Create an exam in an unassigned subject and verify Teacher1 is denied
    uid = uuid.uuid4().hex[:6]
    sub_res = client.post(
        "/api/subjects",
        json={"code": f"UN{uid}", "name": "Unassigned Subject", "department_id": 1, "semester": 5, "max_marks": 50},
        headers={"Authorization": f"Bearer {hod_token}"},
    )
    assert sub_res.status_code == 200
    unassigned_sub_id = sub_res.json()["id"]

    exam_res = client.post(
        "/api/exams",
        json={"subject_id": unassigned_sub_id, "name": f"Unassigned Exam {uid}", "exam_type": "INTERNAL", "total_marks": 50, "academic_year": "2026-2027"},
        headers={"Authorization": f"Bearer {hod_token}"},
    )
    assert exam_res.status_code == 200
    unassigned_exam_id = exam_res.json()["id"]

    res_unauth = client.post(
        f"/api/teacher/exams/{unassigned_exam_id}/answer-key",
        files={"file": ("key_unauth.txt", io.BytesIO(b"unauthorized"), "text/plain")},
        headers={"Authorization": f"Bearer {teacher1_token}"},
    )
    assert res_unauth.status_code == 403
    assert "not assigned" in res_unauth.json()["detail"].lower()


def test_teacher_assignment_ownership_isolation(client):
    """Verify that a teacher cannot review an evaluation assignment assigned to another teacher."""
    teacher1_token = get_token(client, "teacher1", "Teacher@123")
    teacher2_token = get_token(client, "teacher2", "Teacher@123")

    # Set up an assignment assigned specifically to teacher1 in DB
    db = SessionLocal()
    try:
        t1 = db.query(User).filter(User.username == "teacher1").first()
        t2 = db.query(User).filter(User.username == "teacher2").first()

        # Find or create an answer
        ans = db.query(AnswerAnswer).first()
        if not ans:
            script = db.query(AnswerScript).first()
            question = db.query(ExamQuestion).first()
            ans = AnswerAnswer(
                script_id=script.id,
                question_id=question.id,
                extracted_text="Sample text",
                status="EVALUATED",
            )
            db.add(ans)
            db.flush()

        # Create assignment specifically for teacher1
        assign = TeacherAssignment(
            answer_id=ans.id,
            teacher_id=t1.id,
            assignment_status="ASSIGNED",
        )
        db.add(assign)
        db.commit()
        assign_id = assign.id
    finally:
        db.close()

    # Teacher2 attempts to review Teacher1's assignment -> 403 Forbidden
    res_t2 = client.post(
        f"/api/teacher/assignments/{assign_id}/review",
        json={"final_mark": 4.5, "teacher_notes": "Attempt by wrong teacher", "decision": "MODIFIED"},
        headers={"Authorization": f"Bearer {teacher2_token}"},
    )
    assert res_t2.status_code == 403
    assert "forbidden" in res_t2.json()["detail"].lower()

    # Teacher1 reviews their own assignment -> 200 OK
    res_t1 = client.post(
        f"/api/teacher/assignments/{assign_id}/review",
        json={"final_mark": 4.0, "teacher_notes": "Verified by assigned teacher", "decision": "APPROVED"},
        headers={"Authorization": f"Bearer {teacher1_token}"},
    )
    assert res_t1.status_code == 200
    assert res_t1.json()["status"] == "success"
    assert res_t1.json()["final_mark"]["final_mark"] == 4.0


def test_subject_summary_results_endpoint(client):
    """Verify GET /api/subjects/{subject_id}/results returns aggregated performance across examinations."""
    hod_token = get_token(client, "admin", "Admin@123")
    res = client.get("/api/subjects/1/results", headers={"Authorization": f"Bearer {hod_token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["subject_id"] == 1
    assert "exam_results" in data
    assert "students_summary" in data
