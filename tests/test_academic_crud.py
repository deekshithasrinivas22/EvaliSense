"""Tests for academic CRUD endpoints: Roles, Users, Departments, Sections, Students, Subjects, Exams, Questions."""
from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient

from api.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def hod_token(client):
    res = client.post("/api/auth/login", json={"username": "admin", "password": "Admin@123"})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_role_crud(client, hod_token):
    """Test creating, listing, updating, and deleting custom roles."""
    headers = {"Authorization": f"Bearer {hod_token}"}

    # Create
    create_res = client.post(
        "/api/roles",
        json={"name": "EXTERNAL_AUDITOR", "description": "Auditor role"},
        headers=headers,
    )
    assert create_res.status_code == 200
    role_id = create_res.json()["id"]

    # List
    list_res = client.get("/api/roles", headers=headers)
    assert list_res.status_code == 200
    assert any(r["name"] == "EXTERNAL_AUDITOR" for r in list_res.json())

    # Update
    update_res = client.put(
        f"/api/roles/{role_id}",
        json={"description": "Updated auditor description"},
        headers=headers,
    )
    assert update_res.status_code == 200
    assert update_res.json()["description"] == "Updated auditor description"

    # Delete
    del_res = client.delete(f"/api/roles/{role_id}", headers=headers)
    assert del_res.status_code == 200


def test_user_crud(client, hod_token):
    """Test creating, getting, updating and deactivating users."""
    headers = {"Authorization": f"Bearer {hod_token}"}

    # Look up teacher role
    roles_res = client.get("/api/roles", headers=headers)
    teacher_role = next(r for r in roles_res.json() if r["name"] == "TEACHER")

    # Create user
    user_payload = {
        "role_id": teacher_role["id"],
        "username": "prof_curie",
        "password": "Password123!",
        "full_name": "Marie Curie",
        "email": "curie@evalisense.edu",
        "employee_id": "EMP-TCH-CURIE",
    }
    create_res = client.post("/api/users", json=user_payload, headers=headers)
    assert create_res.status_code in [200, 400]  # If already exists from prior run
    if create_res.status_code == 200:
        uid = create_res.json()["id"]

        # Get
        get_res = client.get(f"/api/users/{uid}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["full_name"] == "Marie Curie"

        # Update
        up_res = client.put(f"/api/users/{uid}", json={"phone": "+91 9999888877"}, headers=headers)
        assert up_res.status_code == 200
        assert up_res.json()["phone"] == "+91 9999888877"

        # Deactivate
        del_res = client.delete(f"/api/users/{uid}", headers=headers)
        assert del_res.status_code == 200


def test_department_and_section_crud(client, hod_token):
    """Test Department and Section creation and listing."""
    headers = {"Authorization": f"Bearer {hod_token}"}

    # Create department
    d_res = client.post(
        "/api/departments",
        json={"name": "Information Science", "code": "ISE"},
        headers=headers,
    )
    assert d_res.status_code in [200, 400]
    dept_id = d_res.json()["id"] if d_res.status_code == 200 else 1

    # Create section
    s_res = client.post(
        "/api/sections",
        json={"department_id": dept_id, "name": "ISE-A", "semester": 6, "academic_year": "2026-2027"},
        headers=headers,
    )
    assert s_res.status_code == 200
    assert s_res.json()["name"] == "ISE-A"


def test_student_and_subject_crud(client, hod_token):
    """Test Student and Subject creation."""
    headers = {"Authorization": f"Bearer {hod_token}"}

    sections = client.get("/api/sections", headers=headers).json()
    assert len(sections) > 0
    section_id = sections[0]["id"]
    dept_id = sections[0]["department_id"]

    # Student
    st_res = client.post(
        "/api/students",
        json={"usn": "1MS22IS099", "name": "Nikola Tesla", "section_id": section_id},
        headers=headers,
    )
    assert st_res.status_code in [200, 400]

    # Subject
    sub_res = client.post(
        "/api/subjects",
        json={"code": "IS601", "name": "Software Architecture", "semester": 6, "department_id": dept_id, "max_marks": 50.0},
        headers=headers,
    )
    assert sub_res.status_code in [200, 400]


def test_exam_and_question_crud(client, hod_token):
    """Test Exam and Question creation with Rubric."""
    headers = {"Authorization": f"Bearer {hod_token}"}

    subjects = client.get("/api/subjects", headers=headers).json()
    assert len(subjects) > 0
    subject_id = subjects[0]["id"]

    # Exam
    exam_res = client.post(
        "/api/exams",
        json={
            "subject_id": subject_id,
            "name": "Unit Test Exam",
            "exam_type": "INTERNAL",
            "academic_year": "2026-2027",
            "total_marks": 10.0,
        },
        headers=headers,
    )
    assert exam_res.status_code == 200
    exam_id = exam_res.json()["id"]

    # Question with Rubric
    rubric = {
        "question": "What is polymorphism?",
        "max_marks": 5.0,
        "reference_answer": "Polymorphism is an OOP concept allowing objects of different classes to respond to the same message.",
        "criteria": [
            {"id": "c1", "description": "Definition of polymorphism", "marks": 3.0, "keywords": ["OOP", "object", "form"]},
            {"id": "c2", "description": "Examples (compile-time vs runtime)", "marks": 2.0, "keywords": ["overloading", "overriding"]},
        ],
    }

    q_res = client.post(
        f"/api/exams/{exam_id}/questions",
        json={
            "question_number": 1,
            "question_text": "What is polymorphism in object oriented programming?",
            "max_marks": 5.0,
            "reference_answer": rubric["reference_answer"],
            "rubric_json": json.dumps(rubric),
        },
        headers=headers,
    )
    assert q_res.status_code == 200
    assert q_res.json()["question_number"] == 1
