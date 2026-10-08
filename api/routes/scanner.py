"""Scanner role workflows and issue management routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_scanner
from api.database.models import AnswerScript, ScanIssue, User
from api.database.session import get_db
from api.schemas.workflow import AnswerScriptResponse, ScanIssueResponse
from api.services.scanning_service import resolve_scan_issue

router = APIRouter(prefix="/api/scanner", tags=["Scanner Operations"])


@router.get("/scripts", response_model=list[AnswerScriptResponse])
def get_scanner_scripts(
    status_filter: str | None = Query(None, alias="status", description="Filter by script status"),
    current_user: User = Depends(require_scanner),
    db: Session = Depends(get_db),
):
    """Retrieve scripts uploaded by the logged-in scanner (or all for HOD)."""
    user_role = current_user.role.name if current_user.role else ""
    query = db.query(AnswerScript)

    if user_role != "HOD":
        query = query.filter(AnswerScript.uploaded_by == current_user.id)

    if status_filter:
        query = query.filter(AnswerScript.status == status_filter)

    scripts = query.order_by(AnswerScript.uploaded_at.desc()).all()
    return [AnswerScriptResponse(**s.to_dict()) for s in scripts]


@router.get("/issues", response_model=list[ScanIssueResponse])
def get_scan_issues(
    status_filter: str | None = Query(None, alias="status", description="Filter by OPEN, RESOLVED"),
    current_user: User = Depends(require_scanner),
    db: Session = Depends(get_db),
):
    """Retrieve scan and OCR issues."""
    user_role = current_user.role.name if current_user.role else ""
    query = db.query(ScanIssue)

    if user_role != "HOD":
        query = query.join(AnswerScript, AnswerScript.id == ScanIssue.script_id).filter(
            AnswerScript.uploaded_by == current_user.id
        )

    if status_filter:
        query = query.filter(ScanIssue.status == status_filter)

    issues = query.order_by(ScanIssue.created_at.desc()).all()
    return [ScanIssueResponse(**i.to_dict()) for i in issues]


@router.post("/issues/{issue_id}/resolve", response_model=ScanIssueResponse)
def resolve_issue(
    issue_id: int,
    resolution_note: str | None = Form(None),
    current_user: User = Depends(require_scanner),
    db: Session = Depends(get_db),
):
    """Resolve a scan issue."""
    issue = resolve_scan_issue(db, issue_id, user=current_user, resolution_note=resolution_note)
    return ScanIssueResponse(**issue.to_dict())
