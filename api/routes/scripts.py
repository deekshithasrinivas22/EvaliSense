"""Answer scripts scanning, uploading, and processing routes."""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_scanner
from api.database.models import AnswerScript, Exam, Student, User
from api.database.session import get_db
from api.schemas.workflow import AnswerScriptResponse
from api.services.ai_service import process_script_evaluation
from api.services.scanning_service import rescan_script, save_and_register_script
from config import config

router = APIRouter(prefix="/api/scripts", tags=["Answer Scripts"])


@router.post("/upload", response_model=AnswerScriptResponse)
def upload_script(
    exam_id: int = Form(...),
    student_usn: str | None = Form(None),
    student_id: int | None = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a handwritten answer sheet (Scanner or HOD)."""
    user_role = current_user.role.name if current_user.role else ""
    if user_role not in ["SCANNER", "HOD"]:
        raise HTTPException(status_code=403, detail="Only Scanners and HODs can upload scripts.")

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


@router.get("", response_model=list[AnswerScriptResponse])
def list_scripts(
    exam_id: int | None = Query(None, description="Filter by exam ID"),
    status: str | None = Query(None, description="Filter by status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List scripts based on user role."""
    query = db.query(AnswerScript)
    user_role = current_user.role.name if current_user.role else ""

    # Scanners only see their own uploads
    if user_role == "SCANNER":
        query = query.filter(AnswerScript.uploaded_by == current_user.id)

    if exam_id is not None:
        query = query.filter(AnswerScript.exam_id == exam_id)
    if status is not None:
        query = query.filter(AnswerScript.status == status)

    scripts = query.order_by(AnswerScript.uploaded_at.desc()).all()
    return [AnswerScriptResponse(**s.to_dict()) for s in scripts]


@router.get("/{script_id}")
def get_script(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve full details of an answer script including extracted answers and issues."""
    script = db.query(AnswerScript).filter(AnswerScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found.")

    user_role = current_user.role.name if current_user.role else ""
    if user_role == "SCANNER" and script.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied.")

    return {
        "script": script.to_dict(),
        "issues": [issue.to_dict() for issue in script.scan_issues],
        "answers": [ans.to_dict() for ans in script.answers],
    }


@router.get("/{script_id}/status")
def get_script_status(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check processing status and scan issues for a script."""
    script = db.query(AnswerScript).filter(AnswerScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found.")

    return {
        "script_id": script.id,
        "status": script.status,
        "scan_quality": script.scan_quality,
        "issues_count": len(script.scan_issues),
        "issues": [i.to_dict() for i in script.scan_issues if i.status == "OPEN"],
    }


@router.post("/{script_id}/evaluate")
def evaluate_script(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger the AI evaluation pipeline on an uploaded script."""
    script = db.query(AnswerScript).filter(AnswerScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found.")

    if script.status == "REUPLOAD_REQUIRED":
        raise HTTPException(
            status_code=400,
            detail="Script has open quality issues requiring rescan. Cannot evaluate.",
        )

    result = process_script_evaluation(db, script_id, triggering_user=current_user)
    return result


@router.post("/{script_id}/rescan", response_model=AnswerScriptResponse)
def rescan(
    script_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-upload / replace a failed script (Scanner or HOD)."""
    user_role = current_user.role.name if current_user.role else ""
    if user_role not in ["SCANNER", "HOD"]:
        raise HTTPException(status_code=403, detail="Only Scanners and HODs can rescan scripts.")

    script = rescan_script(db, script_id, file, user=current_user)
    return AnswerScriptResponse(**script.to_dict())


@router.get("/{script_id}/image")
def get_script_image(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Securely stream script image."""
    script = db.query(AnswerScript).filter(AnswerScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found.")

    img_path = Path(script.original_path).resolve()
    # Path traversal safety check
    storage_root = config.storage_dir.resolve()
    if not str(img_path).startswith(str(storage_root)) and not str(img_path).startswith(str(config.project_root.resolve())):
        raise HTTPException(status_code=403, detail="Access denied.")

    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found on server.")

    return FileResponse(str(img_path))
