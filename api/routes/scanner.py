"""Scanner role workflows, upload, and issue management routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from api.auth.dependencies import require_scanner
from api.database.models import AnswerScript, Exam, ScanIssue, User
from api.database.session import get_db
from api.schemas.workflow import AnswerScriptResponse, ScanIssueResponse
from api.services.scanning_service import rescan_script, resolve_scan_issue, save_and_register_script

router = APIRouter(prefix="/api/scanner", tags=["Scanner Operations"])


@router.post("/scripts/upload", response_model=AnswerScriptResponse)
def scanner_upload_script(
    exam_id: int = Form(...),
    student_usn: str | None = Form(None),
    student_id: int | None = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(require_scanner),
    db: Session = Depends(get_db),
):
    """Upload a handwritten student answer sheet (Scanner only)."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    script = save_and_register_script(
        db=db,
        exam=exam,
        uploader=current_user,
        file=file,
        student_usn=student_usn,
        student_id=student_id,
    )
    return AnswerScriptResponse(**script.to_dict())


@router.get("/scripts", response_model=list[AnswerScriptResponse])
def get_scanner_scripts(
    status_filter: str | None = Query(None, alias="status", description="Filter by script status"),
    current_user: User = Depends(require_scanner),
    db: Session = Depends(get_db),
):
    """Retrieve scripts uploaded by the logged-in scanner."""
    query = db.query(AnswerScript).filter(AnswerScript.uploaded_by == current_user.id)
    if status_filter:
        query = query.filter(AnswerScript.status == status_filter)

    scripts = query.order_by(AnswerScript.uploaded_at.desc()).all()
    return [AnswerScriptResponse(**s.to_dict()) for s in scripts]


@router.get("/scripts/{script_id}")
def get_scanner_script_detail(
    script_id: int,
    current_user: User = Depends(require_scanner),
    db: Session = Depends(get_db),
):
    """Retrieve details of an uploaded answer script for the scanner."""
    script = db.query(AnswerScript).filter(AnswerScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Answer script not found.")

    if script.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied: Script was not uploaded by you.")

    return {
        "script": script.to_dict(),
        "issues": [issue.to_dict() for issue in script.scan_issues],
        "answers": [ans.to_dict() for ans in script.answers],
    }


@router.post("/scripts/{script_id}/reupload", response_model=AnswerScriptResponse)
def scanner_reupload_script(
    script_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(require_scanner),
    db: Session = Depends(get_db),
):
    """Re-upload / replace a failed script (Scanner only)."""
    script = db.query(AnswerScript).filter(AnswerScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Answer script not found.")

    if script.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied: Script was not uploaded by you.")

    updated_script = rescan_script(db, script_id, file, user=current_user)
    return AnswerScriptResponse(**updated_script.to_dict())


@router.get("/issues", response_model=list[ScanIssueResponse])
def get_scan_issues(
    status_filter: str | None = Query(None, alias="status", description="Filter by OPEN, RESOLVED"),
    current_user: User = Depends(require_scanner),
    db: Session = Depends(get_db),
):
    """Retrieve scan and OCR issues for the logged-in scanner."""
    query = (
        db.query(ScanIssue)
        .join(AnswerScript, AnswerScript.id == ScanIssue.script_id)
        .filter(AnswerScript.uploaded_by == current_user.id)
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
