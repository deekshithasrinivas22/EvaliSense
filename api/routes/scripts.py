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
    """Upload a handwritten answer sheet (Scanner only)."""
    user_role = current_user.role.name if current_user.role else ""
    if user_role != "SCANNER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Only the Scanner role is permitted to upload student answer scripts.",
        )

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
    """Retrieve full details of an answer script including extracted answers, issues, and page traces."""
    script = db.query(AnswerScript).filter(AnswerScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found.")

    user_role = current_user.role.name if current_user.role else ""
    if user_role == "SCANNER" and script.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied.")

    orig_path = Path(script.original_path)
    script_dir = orig_path.parent.parent if orig_path.parent.name == "original" else orig_path.parent
    manifest_file = script_dir / "pages" / "pages_manifest.json"
    pages_data = None
    if manifest_file.exists():
        import json
        try:
            pages_data = json.loads(manifest_file.read_text(encoding="utf-8")).get("pages")
        except Exception:
            pages_data = None

    return {
        "script": script.to_dict(),
        "issues": [issue.to_dict() for issue in script.scan_issues],
        "answers": [ans.to_dict() for ans in script.answers],
        "pages": pages_data,
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
    """Re-upload / replace a failed script (Scanner only)."""
    user_role = current_user.role.name if current_user.role else ""
    if user_role != "SCANNER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Only the Scanner role is permitted to re-upload or rescan student answer scripts.",
        )

    script = rescan_script(db, script_id, file, user=current_user)
    return AnswerScriptResponse(**script.to_dict())


@router.get("/{script_id}/image")
def get_script_image(
    script_id: int,
    page: int | None = Query(None, description="Page number for multipage documents (1-indexed)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Securely stream script image or specific rendered page."""
    script = db.query(AnswerScript).filter(AnswerScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found.")

    img_path = Path(script.original_path).resolve()
    # Path traversal safety check
    storage_root = config.storage_dir.resolve()
    if not str(img_path).startswith(str(storage_root)) and not str(img_path).startswith(str(config.project_root.resolve())):
        raise HTTPException(status_code=403, detail="Access denied.")

    is_pdf = img_path.suffix.lower() == ".pdf"
    script_dir = img_path.parent.parent if img_path.parent.name == "original" else img_path.parent
    pages_dir = script_dir / "pages"

    # If page number is specified, stream the specific rendered page
    if page is not None:
        page_file = pages_dir / f"page_{page:03d}.png"
        if page_file.exists():
            return FileResponse(str(page_file), media_type="image/png")
        raise HTTPException(status_code=404, detail=f"Page {page} not found for script #{script_id}.")

    # If document is a PDF and no specific page is requested, stream page 1 image so standard <img> tags render
    if is_pdf:
        first_page = pages_dir / "page_001.png"
        if first_page.exists():
            return FileResponse(str(first_page), media_type="image/png")

    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found on server.")

    return FileResponse(str(img_path))


@router.get("/{script_id}/pages")
def get_script_pages(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve all pages of a script including rendered page URLs and OCR traces."""
    script = db.query(AnswerScript).filter(AnswerScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found.")

    orig_path = Path(script.original_path)
    script_dir = orig_path.parent.parent if orig_path.parent.name == "original" else orig_path.parent
    pages_dir = script_dir / "pages"
    manifest_file = pages_dir / "pages_manifest.json"

    if manifest_file.exists():
        import json
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        for p in manifest.get("pages", []):
            p["image_url"] = f"/api/scripts/{script.id}/image?page={p['page_number']}"
        return manifest

    page_files = sorted(pages_dir.glob("page_*.png")) if pages_dir.exists() else []
    if page_files:
        return {
            "script_id": script.id,
            "total_pages": len(page_files),
            "pages": [
                {
                    "page_number": idx + 1,
                    "image_url": f"/api/scripts/{script.id}/image?page={idx + 1}",
                }
                for idx in range(len(page_files))
            ],
        }

    return {
        "script_id": script.id,
        "total_pages": 1,
        "pages": [{"page_number": 1, "image_url": f"/api/scripts/{script.id}/image"}],
    }
