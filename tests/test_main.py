
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200


def test_existing_employee_leave_balance():
    response = client.get("/leave-balance/EMP001")
    assert response.status_code == 200


def test_unknown_employee_leave_balance():
    response = client.get("/leave-balance/EMP999")
    assert response.status_code == 404


def test_submit_valid_leave_request():
    response = client.post(
        "/leave-requests",
        json={
            "employee_id": "EMP001",
            "start_date": "2026-11-10",
            "end_date": "2026-11-12",
            "reason": "Personal work"
        }
    )
    assert response.status_code == 201


def test_reject_unknown_employee_request():
    response = client.post(
        "/leave-requests",
        json={
            "employee_id": "EMP999",
            "start_date": "2026-11-10",
            "end_date": "2026-11-12",
            "reason": "Personal work"
        }
    )
    assert response.status_code == 404
