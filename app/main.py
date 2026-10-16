
from datetime import date
from enum import Enum
from pathlib import Path
from uuid import uuid4

import shutil
import subprocess
import sys
import tempfile

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.llm_service import analyze_bug, propose_patch


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


class BugAnalysisInput(BaseModel):
    issue: str = Field(min_length=10, max_length=3000)
    source_code: str = Field(min_length=1, max_length=12000)


class RepositoryAnalysisInput(BaseModel):
    issue: str = Field(min_length=10, max_length=3000)


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
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    return {
        "employee_id": employee_id,
        "remaining_leave_days": leave_balances[employee_id],
    }


@app.post("/leave-requests", status_code=201)
def apply_for_leave(request: LeaveRequestInput):
    employee_id = request.employee_id

    if employee_id not in leave_balances:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    requested_days = (
        request.end_date - request.start_date
    ).days + 1

    # BUG-001: Intentionally incorrect for the agent POC.
    # The correct comparison is requested_days > leave_balances[employee_id].
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
            request.start_date
            <= date.fromisoformat(existing["end_date"])
            and request.end_date
            >= date.fromisoformat(existing["start_date"])
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
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    if employee_id is None:
        return leave_requests

    return [
        request
        for request in leave_requests
        if request["employee_id"] == employee_id
    ]


# Agent endpoint 1: Analyse code supplied by the caller.
@app.post("/agent/analyze")
def analyze_issue(request: BugAnalysisInput):
    try:
        analysis = analyze_bug(
            issue=request.issue,
            source_code=request.source_code,
        )

        return {
            "status": "analysis_completed",
            "model": "qwen2.5:3b",
            "analysis": analysis,
        }

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc


# Agent endpoint 2: Analyse the actual repository file.
@app.post("/agent/analyze-repo")
def analyze_repository_issue(request: RepositoryAnalysisInput):
    project_root = Path(__file__).resolve().parent.parent
    source_path = project_root / "app" / "main.py"

    try:
        source_code = source_path.read_text(encoding="utf-8")

        analysis = analyze_bug(
            issue=request.issue,
            source_code=source_code,
        )

        return {
            "status": "analysis_completed",
            "file_analyzed": "app/main.py",
            "analysis": analysis,
        }

    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not read the repository source file.",
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc


# Agent endpoint 3: Propose a patch without modifying files.
@app.post("/agent/propose-fix")
def propose_issue_fix(request: RepositoryAnalysisInput):
    project_root = Path(__file__).resolve().parent.parent
    source_path = project_root / "app" / "main.py"

    try:
        source_code = source_path.read_text(encoding="utf-8")

        patch = propose_patch(
            issue=request.issue,
            source_code=source_code,
        )

        old_text = patch["old_text"]
        match_count = source_code.count(old_text)

        if match_count != 1:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": (
                        "AI-generated patch does not match source code."
                    ),
                    "old_text_returned_by_ai": repr(old_text),
                    "match_count": match_count,
                    "expected_condition": (
                        "if requested_days < leave_balances[employee_id]:"
                    ),
                },
            )

        return {
            "status": "patch_proposed",
            "file": "app/main.py",
            "old_text": old_text,
            "new_text": patch["new_text"],
            "explanation": patch["explanation"],
            "applied": False,
        }

    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not read the repository source file.",
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc


# Agent endpoint 4: Verify a proposed patch in a temporary workspace.
@app.post("/agent/verify-fix")
def verify_proposed_fix(request: RepositoryAnalysisInput):
    project_root = Path(__file__).resolve().parent.parent
    source_path = project_root / "app" / "main.py"
    tests_path = project_root / "tests"

    try:
        source_code = source_path.read_text(encoding="utf-8")

        patch = propose_patch(
            issue=request.issue,
            source_code=source_code,
        )

        old_text = patch["old_text"]
        new_text = patch["new_text"]

        match_count = source_code.count(old_text)

        if match_count != 1:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": (
                        "AI-generated patch does not match source code."
                    ),
                    "old_text_returned_by_ai": repr(old_text),
                    "match_count": match_count,
                    "expected_condition": (
                        "if requested_days < leave_balances[employee_id]:"
                    ),
                },
            )

        if not tests_path.is_dir():
            raise HTTPException(
                status_code=500,
                detail="Tests directory was not found.",
            )

        # Work only in a temporary copy, never in the original project.
        with tempfile.TemporaryDirectory(
            prefix="aisdlc-verify-"
        ) as temp_dir:
            workspace = Path(temp_dir)

            shutil.copytree(
                project_root / "app",
                workspace / "app",
                ignore=shutil.ignore_patterns(
                    "__pycache__",
                    "*.pyc",
                ),
            )

            shutil.copytree(
                tests_path,
                workspace / "tests",
                ignore=shutil.ignore_patterns(
                    "__pycache__",
                    "*.pyc",
                ),
            )

            patched_source = source_code.replace(
                old_text,
                new_text,
                1,
            )

            (workspace / "app" / "main.py").write_text(
                patched_source,
                encoding="utf-8",
            )

            # Use the current virtual environment's Python and pytest.
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                ],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

            return {
                "status": (
                    "verification_passed"
                    if result.returncode == 0
                    else "verification_failed"
                ),
                "file": "app/main.py",
                "explanation": patch["explanation"],
                "tests_passed": result.returncode == 0,
                "test_output": (
                    result.stdout + "\n" + result.stderr
                )[-6000:],
                "original_files_modified": False,
            }

    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail="Tests exceeded the 60-second time limit.",
        ) from exc

    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not prepare the verification workspace.",
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
