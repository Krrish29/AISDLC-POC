
from datetime import date
from enum import Enum
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

app = FastAPI(title="AISDLC Leave Management System")


# Demo employee leave balances
leave_balances = {
    "EMP001": 12,
    "EMP002": 5,
}

leave_requests = []


class LeaveStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LeaveRequestInput(BaseModel):
    employee_id: str = Field(min_length=1)
    start_date: date
    end_date: date
    reason: str = Field(min_length=3, max_length=200)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date cannot be before start date")

        if self.start_date < date.today():
            raise ValueError("Leave cannot start in the past")

        return self


@app.get("/")
def home():
    return {
        "message": "Leave Management System is running",
        "project": "AISDLC POC",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/leave-balance/{employee_id}")
def get_leave_balance(employee_id: str):
    if employee_id not in leave_balances:
        raise HTTPException(status_code=404, detail="Employee not found")

    return {
        "employee_id": employee_id,
        "remaining_leave_days": leave_balances[employee_id],
    }


@app.post("/leave-requests", status_code=201)
def apply_for_leave(request: LeaveRequestInput):
    employee_id = request.employee_id

    if employee_id not in leave_balances:
        raise HTTPException(status_code=404, detail="Employee not found")

    requested_days = (request.end_date - request.start_date).days + 1

    if requested_days < leave_balances[employee_id]:
        raise HTTPException(
            status_code=400,
            detail="Insufficient leave balance",
        )

    for existing in leave_requests:
        same_employee = existing["employee_id"] == employee_id
        active_request = existing["status"] in {
            LeaveStatus.PENDING.value,
            LeaveStatus.APPROVED.value,
        }
        overlaps = (
            request.start_date <= date.fromisoformat(existing["end_date"])
            and request.end_date >= date.fromisoformat(existing["start_date"])
        )

        if same_employee and active_request and overlaps:
            raise HTTPException(
                status_code=409,
                detail="Overlapping leave request already exists",
            )

    new_request = {
        "request_id": str(uuid4()),
        "employee_id": employee_id,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "requested_days": requested_days,
        "reason": request.reason,
        "status": LeaveStatus.PENDING.value,
    }

    leave_requests.append(new_request)

    return {
        "message": "Leave request submitted successfully",
        "leave_request": new_request,
    }


@app.get("/leave-requests")
def get_leave_requests(employee_id: str | None = None):
    if employee_id is not None and employee_id not in leave_balances:
        raise HTTPException(status_code=404, detail="Employee not found")

    if employee_id is None:
        return leave_requests

    return [
        request
        for request in leave_requests
        if request["employee_id"] == employee_id
    ]


def test_reject_leave_request_exceeding_balance():
    response = client.post(
        "/leave-requests",
        json={
            "employee_id": "EMP002",
            "start_date": "2026-11-10",
            "end_date": "2026-11-16",
            "reason": "Extended personal leave"
        }
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Insufficient leave balance"
