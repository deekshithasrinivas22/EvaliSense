"""Unit and integration tests for authentication and RBAC authorization boundaries."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.auth.security import hash_password, verify_password, create_access_token, decode_access_token


@pytest.fixture
def client():
    return TestClient(app)


def test_password_hashing():
    """Verify Argon2 password hashing and verification."""
    password = "SuperSecretPassword123"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword", hashed) is False


def test_jwt_token_cycle():
    """Verify JWT token encoding and decoding."""
    payload = {"sub": "1", "username": "admin", "role": "HOD"}
    token = create_access_token(payload)
    decoded = decode_access_token(token)
    assert decoded is not None
    assert decoded["username"] == "admin"
    assert decoded["role"] == "HOD"


def test_login_success(client):
    """Test successful login with seeded admin account."""
    res = client.post("/api/auth/login", json={"username": "admin", "password": "Admin@123"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" == "access_token" in data
    assert data["role"] == "HOD"
    assert data["username"] == "admin"


def test_login_invalid_password(client):
    """Test login failure with invalid password."""
    res = client.post("/api/auth/login", json={"username": "admin", "password": "IncorrectPassword"})
    assert res.status_code == 401


def test_unauthenticated_access_denied(client):
    """Verify unauthenticated request to protected route is denied."""
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_rbac_teacher_cannot_access_hod_endpoint(client):
    """Verify teacher account cannot access HOD-only route."""
    # Login as teacher1
    t_res = client.post("/api/auth/login", json={"username": "teacher1", "password": "Teacher@123"})
    assert t_res.status_code == 200
    teacher_token = t_res.json()["access_token"]

    # Attempt to create a role (HOD-only)
    role_res = client.post(
        "/api/roles",
        json={"name": "UNAUTHORIZED_ROLE"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert role_res.status_code == 403


def test_rbac_scanner_cannot_submit_teacher_review(client):
    """Verify scanner cannot submit teacher evaluation review."""
    s_res = client.post("/api/auth/login", json={"username": "scanner1", "password": "Scanner@123"})
    assert s_res.status_code == 200
    scanner_token = s_res.json()["access_token"]

    res = client.post(
        "/api/teacher/assignments/1/review",
        json={"final_mark": 10.0, "decision": "APPROVED"},
        headers={"Authorization": f"Bearer {scanner_token}"},
    )
    assert res.status_code == 403
