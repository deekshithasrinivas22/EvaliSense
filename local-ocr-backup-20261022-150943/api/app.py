"""FastAPI backend for EvaliSense.

Provides REST endpoints for:
- Image upload and preprocessing
- HTR (handwritten text recognition)
- Rubric-based answer evaluation
- Grading-error risk prediction
- Examiner review and final mark submission
- Model/dataset information

Run with:
    uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload
"""
from __future__ import annotations

import json
import hashlib
import shutil
import time
import uuid
from threading import Lock
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from config import config
from utils.logging import get_logger, setup_logging

setup_logging(level=config.log_level)
logger = get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────
# App initialisation
# ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="EvaliSense API",
    description="AI-Powered Handwritten Examination Evaluation with ML-Based Grading Error Prediction",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure data directories exist
config.ensure_dirs()

# Initialize database and seed system roles/admin on startup
from api.database.session import init_db
try:
    init_db()
except Exception as _e:
    logger.error("Failed to initialize database: %s", _e)

# Include role-based and academic routers
from api.routes import all_routers
for _router in all_routers:
    app.include_router(_router)

from api.answer_key_files import build_answer_key_router
app.include_router(build_answer_key_router(config.storage_dir / "teacher_answer_keys"))

# Mount static frontend
_frontend_dir = config.project_root / "frontend"
if _frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_frontend_dir)), name="static")

# Dataset images served via /api/dataset-image endpoint (see below)

# In-memory store for evaluation sessions (use a DB in production)
_sessions: dict[str, dict[str, Any]] = {}

# Lazy-loaded components
_htr_pipeline = None
_htr_init_lock = Lock()
_evaluator = None
_risk_model = None


def _get_htr():
    global _htr_pipeline
    with _htr_init_lock:
        if _htr_pipeline is None:
            from htr.local_document import LocalDocumentPipeline
            _htr_pipeline = LocalDocumentPipeline()
            logger.info("HTR pipeline initialised")
    return _htr_pipeline


def _get_evaluator():
    global _evaluator
    if _evaluator is None:
        from evaluation import AnswerEvaluator
        _evaluator = AnswerEvaluator(
            model_name=config.embedding_model_name,
            similarity_threshold=config.similarity_threshold,
        )
        logger.info("Answer evaluator initialised")
    return _evaluator


def _get_risk_model():
    global _risk_model
    if _risk_model is None:
        if config.risk_model_path.exists():
            from models import GradingRiskModel
            _risk_model = GradingRiskModel.load(config.risk_model_path)
            logger.info("Risk model loaded from %s", config.risk_model_path)
        else:
            logger.warning("No trained risk model found at %s", config.risk_model_path)
    return _risk_model


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────

def _render_frontend(frontend_dir: Path) -> str:
    """Assemble trusted, local feature fragments before browser initialization.

    Include markers are deliberately limited to flat files under partials/.
    Fragments contain HTML only; script loading stays in the page shell.
    """
    import re

    root = frontend_dir.resolve()
    shell = (root / "index.html").read_text(encoding="utf-8")
    include_pattern = re.compile(r"<!--\s*include:(partials/[a-z0-9_/-]+\.html)\s*-->")

    def include(match):
        relative_path = match.group(1)
        fragment = (root / relative_path).resolve()
        if not fragment.is_relative_to(root / "partials"):
            raise ValueError("Frontend include must stay inside partials/.")
        content = fragment.read_text(encoding="utf-8")
        if "include:" in content:
            raise ValueError("Nested frontend includes are not supported.")
        return content

    rendered = include_pattern.sub(include, shell)
    if "<!-- include:" in rendered:
        raise ValueError("Unresolved frontend include marker.")
    return rendered


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the assembled frontend, or API info if it is not installed."""
    index = _frontend_dir / "index.html"
    if index.exists():
        try:
            return HTMLResponse(_render_frontend(_frontend_dir))
        except (OSError, ValueError):
            logger.exception("Could not assemble frontend feature files")
            return HTMLResponse("<h1>Frontend files are incomplete</h1><p>Copy index.html and the entire frontend/partials folder, then reload.</p>", status_code=500)
    return JSONResponse({"message": "EvaliSense API", "version": "0.1.0", "docs": "/docs"})


@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": time.time()}


@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    """Upload a handwritten answer image, PDF, or text file."""
    if not file.filename:
        raise HTTPException(400, "No filename provided.")

    ext = Path(file.filename).suffix.lower()
    allowed_exts = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".pdf", ".txt"}
    if ext not in allowed_exts:
        raise HTTPException(400, f"Unsupported file format: {ext}. Allowed: {', '.join(sorted(allowed_exts))}")

    session_id = str(uuid.uuid4())[:12]
    session_dir = config.results_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    original_path = session_dir / f"original{ext}"
    content_bytes = await file.read()

    with open(original_path, "wb") as f:
        f.write(content_bytes)

    session_data = {
        "session_id": session_id,
        "original_path": str(original_path),
        "filename": file.filename,
        "upload_sha256": hashlib.sha256(content_bytes).hexdigest(),
        "file_type": ext.lstrip("."),
        "status": "uploaded",
        "created_at": time.time(),
    }

    # For text files, extract text content immediately
    if ext == ".txt":
        try:
            text_content = content_bytes.decode("utf-8", errors="replace")
            session_data["extracted_text"] = text_content
            session_data["status"] = "text_uploaded"
        except Exception:
            pass

    _sessions[session_id] = session_data

    logger.info("File uploaded: %s (%s) → session %s", file.filename, ext, session_id)
    return {
        "session_id": session_id,
        "filename": file.filename,
        "file_type": ext.lstrip("."),
        "status": session_data["status"],
        "extracted_text": session_data.get("extracted_text", None),
    }


def _preprocess_demo_session(session):
    """CPU/image work runs in a worker, leaving the web server responsive."""
    original = Path(session["original_path"])
    if not original.is_file():
        raise HTTPException(404, "Original file not found.")
    file_type = session.get("file_type", original.suffix.lstrip(".").lower())
    session.pop("htr_result", None)
    session.pop("recognition_progress", None)
    session.pop("pdf_embedded_text", None)
    session.pop("pdf_pages", None)
    session.pop("processed_path", None)
    if file_type == "txt":
        session["preprocessing"] = {"metadata": {"skipped": True, "reason": "TXT already contains text; TrOCR is not needed."}}
        session["status"] = "preprocessed"
        return
    preprocessor = None
    def process_image(path, output):
        nonlocal preprocessor
        if preprocessor is None:
            from preprocessing import ImagePreprocessor
            preprocessor = ImagePreprocessor()
        return preprocessor.process(str(path), str(output))
    if file_type == "pdf":
        import fitz
        pages = []
        with fitz.open(str(original)) as doc:
            if doc.needs_pass:
                raise HTTPException(400, "Upload an unlocked PDF.")
            if not doc.page_count or doc.page_count > config.max_pdf_pages:
                raise HTTPException(400, f"PDF must contain between 1 and {config.max_pdf_pages} pages.")
            for number, page in enumerate(doc, 1):
                text = page.get_text(sort=True).strip()
                if text:
                    pages.append({"page_number": number, "text": text})
                    continue
                width, height = page.rect.width, page.rect.height
                scale = min(config.pdf_render_dpi / 72, config.pdf_max_render_width / width,
                            config.pdf_max_render_height / height,
                            (config.pdf_max_render_pixels / (width * height)) ** 0.5)
                image_path = original.parent / f"pdf_page{number}.png"
                page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).save(str(image_path))
                processed = original.parent / f"processed_page{number}.png"
                process_image(image_path, processed)
                pages.append({"page_number": number, "processed_path": str(processed), "recognition_path": str(image_path)})
        session["pdf_pages"] = pages
        scanned = [page for page in pages if "processed_path" in page]
        if scanned:
            session["processed_path"] = scanned[0]["processed_path"]
        else:
            session["pdf_embedded_text"] = "\n\n".join(page["text"] for page in pages)
        session["preprocessing"] = {"metadata": {"page_count": len(pages), "scanned_pages": len(scanned),
            "text_pages": len(pages) - len(scanned), "skipped": not scanned,
            "reason": "Readable PDF text is reused; only scanned pages need TrOCR."}}
    else:
        processed = original.parent / "processed.png"
        result = process_image(original, processed)
        session["processed_path"] = str(processed)
        session["preprocessing"] = {"input_shape": list(result.original.shape) if result.original is not None else None,
            "output_shape": list(result.final.shape) if result.final is not None else None, "metadata": result.metadata}
    session["status"] = "preprocessed"


@app.post("/api/preprocess/{session_id}")
async def preprocess(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")
    if session.get("recognition_in_progress") or session.get("preprocessing_in_progress"):
        raise HTTPException(409, "This session is already processing. Wait for it to finish.")
    session["preprocessing_in_progress"] = True
    try:
        await run_in_threadpool(_preprocess_demo_session, session)
        return {"session_id": session_id, "status": "preprocessed", "details": session["preprocessing"]}
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Preprocessing failed")
        raise HTTPException(500, f"Preprocessing failed: {error}")
    finally:
        session["preprocessing_in_progress"] = False


def _recognize_demo_session(session):
    from htr.result import HTRResult, RecognizedLine
    started = time.perf_counter()
    file_type = session.get("file_type", "")
    if file_type == "pdf" and not session.get("pdf_pages"):
        _preprocess_demo_session(session)
    if file_type == "txt":
        sources = [{"page_number": 1, "text": session.get("extracted_text", "")}]
    elif session.get("pdf_pages"):
        sources = session["pdf_pages"]
    elif file_type == "pdf" and session.get("pdf_embedded_text"):
        sources = [{"page_number": 1, "text": session["pdf_embedded_text"]}]
    else:
        sources = [{"page_number": 1, "processed_path": session.get("processed_path", session.get("original_path"))}]
    lines, text_parts, page_metadata = [], [], []
    pipeline = None
    for index, source in enumerate(sources, 1):
        if "text" in source:
            text = source["text"]
            recognized = [RecognizedLine(i + 1, line, 1.0) for i, line in enumerate(text.splitlines()) if line.strip()]
            page_metadata.append({"page_number": index, "method": "text"})
        else:
            # Use original scan pixels for recognition; adaptive thresholding
            # creates outlined strokes and enhances reverse-side bleed-through.
            path = source.get("recognition_path")
            if not path:
                rendered = Path(session["original_path"]).parent / f"pdf_page{index}.png"
                path = str(rendered) if file_type == "pdf" and rendered.is_file() else session["original_path"]
            if not path or not Path(path).is_file():
                raise HTTPException(404, "Preprocessed image not found. Run preprocessing again.")
            pipeline = pipeline or _get_htr()
            def update(progress):
                session["recognition_progress"] = {**progress, "page_number": index, "total_pages": len(sources),
                    "phase": "page_completed" if progress["phase"] == "completed" else progress["phase"]}
            result = pipeline.recognize_path(path, on_progress=update)
            text, recognized = result.full_text, result.lines
            for warning in result.metadata.get('quality_warnings',[]):
                local_number=warning['line_number']
                original_marker=f"[Unclear line {local_number} — review scan]"
                marker=f"[Unclear page {index} line {local_number} — review scan]"
                warning['marker']=marker
                text=text.replace(original_marker,marker)
                for item in recognized:
                    if item.line_number==local_number: item.text=marker
            page_metadata.append({"page_number": index, "method": "local_ocr", **result.metadata})
        text_parts.append(text)
        for line in recognized:
            line.line_number = len(lines) + 1
            lines.append(line)
    full_text = "\n\n".join(part for part in text_parts if part.strip())
    if not full_text.strip():
        raise HTTPException(422, "No text lines were recognized. Try a clearer image cropped to the written answer.")
    confidences = [line.confidence for line in lines if line.confidence is not None]
    metadata = {"elapsed_seconds": round(time.perf_counter() - started, 2), "pages": page_metadata,
        "method": "local_ocr" if pipeline else "direct_text", "device": pipeline.recognizer.device if pipeline else None,
        "ocr_version": "local-fields-v5", "source_filename": session.get("filename"),
        "source_sha256": hashlib.sha256(Path(session["original_path"]).read_bytes()).hexdigest(),
        "source_kind": "uploaded_file" if session.get("filename") else "dataset"}
    return HTRResult(full_text, lines, sum(confidences) / len(confidences) if confidences else None, metadata)


def _demo_recognition_response(session_id, result, cached=False):
    return {"session_id": session_id, "status": "recognized", "text": result["full_text"],
        "lines": result["lines"], "average_confidence": result["average_confidence"],
        "metadata": result.get("metadata", {}), "cached": cached}


@app.get("/api/htr/status")
async def htr_status():
    import importlib.util
    dependencies = {name: importlib.util.find_spec(name) is not None for name in ("cv2", "numpy", "scipy", "rapidocr", "onnxruntime")}
    recognizer = getattr(_htr_pipeline, "recognizer", None)
    loaded = getattr(_htr_pipeline, "model", None) is not None
    return {"dependencies_available": all(dependencies.values()), "dependencies": dependencies,
            "model_loaded": loaded, "device": recognizer.device if loaded else "auto", "model": getattr(recognizer, "display_name", "Local PP-OCRv5") }


@app.get("/api/recognize/{session_id}/progress")
async def recognition_progress(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")
    progress = dict(session.get("recognition_progress", {"phase": "not_started"}))
    if session.get("recognition_in_progress"):
        progress["elapsed_seconds"] = round(time.time() - session["recognition_started_at"], 1)
    return progress


@app.post("/api/recognize/{session_id}")
async def recognize(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")
    if session.get("recognition_in_progress") or session.get("preprocessing_in_progress"):
        raise HTTPException(409, "This session is already processing. Please wait.")
    if session.get("htr_result", {}).get("metadata", {}).get("ocr_version") == "local-fields-v5":
        return _demo_recognition_response(session_id, session["htr_result"], cached=True)
    session["recognition_in_progress"] = True
    session["recognition_started_at"] = time.time()
    session["recognition_progress"] = {"phase": "starting", "completed_lines": 0, "total_lines": 0}
    try:
        result = await run_in_threadpool(_recognize_demo_session, session)
        session["htr_result"] = result.to_dict()
        session["status"] = "recognized"
        session["recognition_progress"] = {"phase": "completed", "completed_lines": len(result.lines),
            "total_lines": len(result.lines), "elapsed_seconds": result.metadata.get("elapsed_seconds", 0)}
        return _demo_recognition_response(session_id, session["htr_result"])
    except HTTPException as error:
        session["recognition_progress"] = {"phase": "failed", "message": error.detail}
        raise
    except Exception as error:
        session["recognition_progress"] = {"phase": "failed", "message": str(error)}
        logger.exception("Local recognition failed")
        raise HTTPException(500, f"Local recognition failed: {error}")
    finally:
        session["recognition_in_progress"] = False


@app.post("/api/extract-questions")
async def extract_questions(file: UploadFile = File(...)):
    """Extract questions and marks from an uploaded question paper (PDF, TXT, or image).
    Returns structured JSON with detected questions and allocated marks."""
    import re

    if not file.filename:
        raise HTTPException(400, "No filename provided.")

    ext = Path(file.filename).suffix.lower()
    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(400, "The uploaded file is empty.")
    extracted_text = ""

    # Step 1: Extract raw text based on file type
    if ext == ".txt":
        extracted_text = content_bytes.decode("utf-8", errors="replace")

    elif ext == ".pdf":
        import fitz
        try:
            with fitz.open(stream=content_bytes, filetype="pdf") as doc:
                if doc.needs_pass:
                    raise HTTPException(400, "This PDF is password-protected. Upload an unlocked copy.")
                pages_text = []
                for page_number, page in enumerate(doc, 1):
                    page_text = page.get_text(sort=True)
                    if not page_text.strip() and page.get_images():
                        raise HTTPException(400, f"Page {page_number} is an image without readable text. Upload an OCR text PDF or TXT transcription so questions are not skipped.")
                    pages_text.append(page_text)
                extracted_text = "\n".join(pages_text)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "Could not read this PDF. Check that it is valid and unlocked.")

    elif ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
        # Save temporarily, preprocess, and run OCR
        session_id = str(uuid.uuid4())[:12]
        session_dir = config.results_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        img_path = session_dir / f"original{ext}"
        with open(img_path, "wb") as f:
            f.write(content_bytes)
        try:
            from preprocessing import ImagePreprocessor
            preprocessor = ImagePreprocessor()
            processed_path = session_dir / "processed.png"
            preprocessor.process(str(img_path), str(processed_path))

            pipeline = _get_htr()
            result = pipeline.recognize_path(str(processed_path), session_dir / "debug")
            extracted_text = result.full_text
        except Exception as e:
            logger.warning("OCR extraction failed: %s", e)
            raise HTTPException(500, f"Could not extract text from image: {e}")
    else:
        raise HTTPException(400, f"Unsupported file format: {ext}")

    if not extracted_text.strip():
        raise HTTPException(400, "No readable text found. For scanned PDFs, upload an OCR text PDF or a TXT transcription.")

    # Step 2: Parse extracted text to find questions and marks
    questions = _parse_questions_from_text(extracted_text)

    logger.info("Extracted %d questions from %s", len(questions), file.filename)
    return {
        "filename": file.filename,
        "extracted_text": extracted_text,
        "questions": questions,
        "total_questions": len(questions),
        "total_marks": sum(q.get("max_marks", 0) for q in questions),
        "needs_review": sum(bool(q.get("warnings")) for q in questions)
    }


def _parse_questions_from_text(text: str) -> list:
    """Extract evidence-based types and marks; surface ambiguity for teacher review.

    Numbering is preserved. Repeated numbers require teacher correction in the
    preview instead of silently overwriting another question during import.
    """
    import re

    number = r"\d+(?:\.\d+)?"
    unit = r"(?:marks?|m|pts?|points?)"
    # Only treat trailing notation as allotted marks, not numbers in the prose.
    mark_end = re.compile(
        rf"(?:[\[(]\s*(?P<bracket>{number})\s*{unit}\s*[\])]|"
        rf"[\[]\s*(?P<bare>{number})\s*[\]]|"
        rf"(?:marks?|points?)\s*[:=]\s*(?P<label>{number})|"
        rf"(?P<suffix>{number})\s*(?:marks?|(?-i:M)|pts?|points?))\s*[.]?\s*$", re.I)
    mark_only = re.compile(rf"^\(\s*(?P<n>{number})\s*\)$")
    q_start = re.compile(
        r"^(?:(?:Question|Q)\.?\s*(\d+)\s*[.):]?|([0-9]+)\s*[.):])\s*(.*)$", re.I)
    section_start = re.compile(r"^(?:section|part)\s+([A-Z0-9IVX]+)\b", re.I)
    mcq_heading = re.compile(r"\b(?:MCQs?|multiple[ -]choice|choose (?:the )?(?:correct|best)|select (?:the )?(?:correct|best))\b", re.I)
    written_heading = re.compile(r"\b(?:short[ -]answers?|long[ -]answers?|descriptive|essay|answer (?:the following|in detail))\b", re.I)
    # Option labels are split only at whitespace boundaries; text is retained.
    labels = re.compile(r"(?<!\S)(?:\(([a-hA-H])\)|([a-hA-H])[).])\s+")
    range_rule = re.compile(
        rf"\b(?:questions?|Q)\s*(\d+)\s*(?:to|[-–])\s*(\d+).*?({number})\s*{unit}\s*each\b", re.I)

    def trailing_marks(value):
        match = mark_end.search(value)
        if not match:
            return value, None, None
        amount = next(v for v in match.groupdict().values() if v is not None)
        return value[:match.start()].strip(), float(amount), match.group(0).strip()

    def per_question_rule(value):
        product = re.search(rf"(?:\d+)\s*[x×*]\s*({number})\s*=\s*{number}", value, re.I)
        if product:
            return float(product.group(1)), product.group(0)
        each = re.search(rf"({number})\s*{unit}\s*(?:each|per question)\b", value, re.I)
        if not each:
            each = re.search(rf"\beach\s+(?:question\s+)?(?:carries?|is\s+(?:of|worth))?\s*({number})\s*{unit}\b", value, re.I)
        return (float(each.group(1)), each.group(0)) if each else (None, None)

    questions = []
    current = None
    section = ''
    section_type = None
    section_marks = None
    section_evidence = None
    range_rules = []

    def finish(q):
        if not q:
            return
        body = '\n'.join(q.pop('_lines')).strip()
        explicit = q.pop('_marks')
        warnings = []
        parts = list(labels.finditer(body))
        labelled = []
        stem = body
        if parts:
            stem = body[:parts[0].start()].strip()
            for i, match in enumerate(parts):
                content = body[match.end():parts[i+1].start() if i+1 < len(parts) else len(body)].strip()
                description, marks, evidence = trailing_marks(content)
                labelled.append({'label': (match.group(1) or match.group(2)).upper(),
                                 'text': description, 'marks': marks, 'evidence': evidence})
        if parts:
            stem, parent_marks, parent_evidence = trailing_marks(stem)
            if parent_marks is not None:
                explicit.insert(0, (parent_marks, parent_evidence))
        q['candidate_options'] = [{'label': x['label'], 'text': x['text']} for x in labelled]
        heading_type = q.pop('_section_type')
        hint_mcq = bool(mcq_heading.search(stem))
        hint_written = bool(re.search(r"\b(?:explain|describe|derive|prove|discuss|differentiate|calculate|demonstrate|define|evaluate)\b", stem, re.I))
        labels_valid = len(labelled) >= 2 and [x['label'] for x in labelled] == list('ABCDEFGH')[:len(labelled)]
        marked_parts = any(x['marks'] is not None for x in labelled)
        if (heading_type == 'MCQ' or hint_mcq) and labels_valid:
            kind, type_source = 'MCQ', 'MCQ instruction and labelled options'
        elif labels_valid and not marked_parts and not hint_written and heading_type != 'WRITTEN':
            kind, type_source = 'MCQ', 'Sequential unmarked answer choices'
            warnings.append('Check that the labelled choices are options, not written subquestions.')
        elif heading_type == 'MCQ' or hint_mcq:
            kind, type_source = 'UNKNOWN', 'MCQ instruction but missing or irregular choices'
            warnings.append('MCQ options could not be separated reliably; check the source paper.')
        elif labelled and not marked_parts and heading_type != 'WRITTEN' and not hint_written:
            kind, type_source = 'UNKNOWN', 'Ambiguous labelled text'
            warnings.append('Check whether labelled text contains options or written subquestions.')
        else:
            kind, type_source = 'WRITTEN', 'Written-answer instruction or question structure'
        if kind == 'WRITTEN' and labelled and not marked_parts and heading_type != 'WRITTEN':
            warnings.append('Unmarked lettered parts were treated as written subquestions; verify the type.')
        q['question_type'] = kind
        q['type_source'] = type_source
        q['type_needs_review'] = kind == 'UNKNOWN' or bool(warnings)
        q['options'] = [{'label': x['label'], 'text': x['text']} for x in labelled] if kind == 'MCQ' else []
        q['criteria'] = []
        if kind == 'WRITTEN':
            q['criteria'] = [{'id': f"c{i+1}", 'description': f"({x['label'].lower()}) {x['text']}",
                              'marks': x['marks'] or 0, 'keywords': []} for i, x in enumerate(labelled)]
        # MCQ option text never becomes rubric criteria or contributes marks.
        candidates = [value for value, _ in explicit]
        if len(set(candidates)) > 1:
            warnings.append('Conflicting question marks found; verify the allotted mark.')
        amount = candidates[0] if candidates else None
        source = explicit[0][1] if explicit else None
        if amount is None and kind == 'WRITTEN' and labelled and all(x['marks'] is not None for x in labelled):
            amount = sum(x['marks'] for x in labelled)
            source = 'Sum of explicitly marked subquestions'
        inherited = q.pop('_section_marks')
        inherited_evidence = q.pop('_section_evidence')
        matched_range = next((r for r in reversed(range_rules) if r[0] <= q['question_number'] <= r[1]), None)
        if amount is None and matched_range:
            amount, source = matched_range[2], matched_range[3]
        if amount is None and inherited is not None:
            amount, source = inherited, inherited_evidence
        if amount is None or amount <= 0:
            warnings.append('Allotted marks were not found. Enter them from the question paper.')
        q['max_marks'] = amount if amount is not None else 0
        q['marks_source'] = source or 'Not found'
        q['marks_need_review'] = amount is None or amount <= 0 or len(set(candidates)) > 1
        q['question_text'] = stem if kind == 'MCQ' else body
        if not q['question_text']:
            q['question_text'] = body
            warnings.append('Question text could not be separated from its choices.')
        if not q['question_text']:
            return
        q['warnings'] = warnings
        q['reference_answer'] = ''
        questions.append(q)

    for raw in text.replace('\ufeff', '').splitlines():
        line = re.sub(r'[\t\u00a0]+', ' ', raw).strip()
        if not line:
            continue
        section_match = section_start.match(line)
        instruction = (not q_start.match(line) and
                       bool(re.match(r'^(?:instructions?|note|answer\s+(?:any|all|the following)|each\s+question|questions?\s+\d+\s*(?:to|[-–])|choose\s+the|select\s+the|multiple[ -]choice|MCQs?\b|short[ -]answer|long[ -]answer|descriptive|essay)', line, re.I)))
        if section_match or instruction:
            finish(current)
            current = None
            if section_match:
                section = section_match.group(1).upper()
                section_type = None
                section_marks = None
                section_evidence = None
                range_rules = []
            if mcq_heading.search(line):
                section_type = 'MCQ'
            elif written_heading.search(line):
                section_type = 'WRITTEN'
            rule = range_rule.search(line)
            if rule:
                range_rules.append((int(rule.group(1)), int(rule.group(2)), float(rule.group(3)), rule.group(0)))
            value, evidence = per_question_rule(line)
            if value is not None and not rule:
                section_marks, section_evidence = value, evidence
            continue
        if re.match(r'^(?:page\s+\d+(?:\s+of\s+\d+)?|time\s*:|date\s*:|max(?:imum)?\s*marks\s*:|total\s*marks\s*:|question\s+paper\b|.*\buniversity\s*$|.*\bexamination\s*$|OR\s*$)', line, re.I):
            continue
        match = q_start.match(line)
        if match:
            finish(current)
            body = match.group(3).strip()
            # If choices/subparts share this line, their marks belong to them.
            if labels.search(body):
                clean, amount, evidence = body, None, None
            else:
                clean, amount, evidence = trailing_marks(body)
            current = {'question_number': int(match.group(1) or match.group(2)),
                       'section': section, '_lines': [clean], '_marks': [],
                       '_section_type': section_type, '_section_marks': section_marks,
                       '_section_evidence': section_evidence}
            if amount is not None:
                current['_marks'].append((amount, evidence))
        elif current:
            if labels.search(line):
                current['_lines'].append(line)
            else:
                clean, amount, evidence = trailing_marks(line)
                # A bare parenthesized number is accepted only on a marks-only line.
                if amount is None and mark_only.fullmatch(line):
                    amount, clean, evidence = float(mark_only.fullmatch(line).group('n')), '', line
                if amount is not None:
                    # Wrapped option/subquestion content belongs to that part.
                    if current['_lines'] and labels.search(current['_lines'][-1]) and clean:
                        current['_lines'][-1] += ' ' + line
                    else:
                        current['_marks'].append((amount, evidence))
                        if clean:
                            current['_lines'].append(clean)
                elif current['_lines'] and labels.search(current['_lines'][-1]):
                    current['_lines'][-1] += ' ' + line
                else:
                    current['_lines'].append(clean)
    finish(current)
    seen = set()
    for order, q in enumerate(questions, 1):
        q['paper_order'] = order
        if q['question_number'] in seen:
            q['warnings'].append('Repeated question number. Give each question a unique number in the preview before import.')
        seen.add(q['question_number'])
    return questions


@app.post("/api/evaluate/{session_id}")
async def evaluate(session_id: str, rubric_json: str = Form(...)):
    """Evaluate the recognised text against a rubric."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")

    htr_result = session.get("htr_result")
    if not htr_result:
        raise HTTPException(400, "HTR has not been run yet. Call /api/recognize first.")

    try:
        from evaluation import Rubric
        rubric_data = json.loads(rubric_json)
        rubric = Rubric.from_dict(rubric_data)
    except (json.JSONDecodeError, Exception) as exc:
        raise HTTPException(400, f"Invalid rubric JSON: {exc}")

    warnings = rubric.validate()
    if warnings:
        logger.warning("Rubric validation: %s", warnings)

    try:
        evaluator = _get_evaluator()
        student_text = htr_result.get("full_text", "")
        eval_result = evaluator.evaluate(student_text, rubric)

        session["eval_result"] = eval_result.to_dict()
        session["rubric"] = rubric.to_dict()
        session["status"] = "evaluated"

        logger.info("Evaluation complete for session %s: %.1f / %.1f",
                     session_id, eval_result.total_score, eval_result.max_score)
        return {
            "session_id": session_id,
            "status": "evaluated",
            "result": eval_result.to_dict(),
        }
    except Exception as exc:
        logger.error("Evaluation failed: %s", exc)
        raise HTTPException(500, f"Evaluation failed: {exc}")


@app.post("/api/predict-risk/{session_id}")
async def predict_risk(session_id: str):
    """Run grading-error risk prediction."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")

    htr_result = session.get("htr_result")
    eval_result = session.get("eval_result")
    if not eval_result:
        raise HTTPException(400, "Evaluation has not been run yet.")

    from features import extract_features

    feature_vec = extract_features(htr_result, eval_result)
    session["features"] = feature_vec.to_dict()

    risk_model = _get_risk_model()
    if risk_model is None:
        # No trained model — provide feature-based heuristic
        risk_prediction = _heuristic_risk(feature_vec.to_dict())
        session["risk_prediction"] = risk_prediction
        session["status"] = "risk_predicted"
        return {"session_id": session_id, "status": "risk_predicted",
                "prediction": risk_prediction,
                "note": "No trained ML model available — using heuristic risk estimation."}

    prediction = risk_model.predict(feature_vec.values, feature_vec.names)
    session["risk_prediction"] = prediction.to_dict()
    session["status"] = "risk_predicted"

    return {"session_id": session_id, "status": "risk_predicted",
            "prediction": prediction.to_dict()}


@app.post("/api/submit-review/{session_id}")
async def submit_review(
    session_id: str,
    examiner_mark: float = Form(...),
    examiner_notes: str = Form(""),
):
    """Submit the examiner's final mark."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")

    eval_result = session.get("eval_result", {})
    max_score = eval_result.get("max_score", 0)
    if examiner_mark < 0:
        raise HTTPException(400, "Examiner mark cannot be negative.")
    if max_score > 0 and examiner_mark > max_score:
        raise HTTPException(400, f"Examiner mark ({examiner_mark}) exceeds max ({max_score}).")

    ai_mark = eval_result.get("total_score", 0)
    disagreement = abs(ai_mark - examiner_mark)

    session["examiner_review"] = {
        "examiner_mark": examiner_mark,
        "ai_mark": ai_mark,
        "max_marks": max_score,
        "disagreement": round(disagreement, 2),
        "examiner_notes": examiner_notes,
        "action": "approved" if disagreement < 0.01 else "modified",
    }
    session["status"] = "reviewed"

    # Persist session as ground-truth record
    _save_session_result(session)

    logger.info("Examiner review for session %s: examiner=%.1f, ai=%.1f, diff=%.1f",
                 session_id, examiner_mark, ai_mark, disagreement)
    return {
        "session_id": session_id,
        "status": "reviewed",
        "review": session["examiner_review"],
    }


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    """Retrieve full session state."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")
    return session


@app.get("/api/sessions")
async def list_sessions():
    """List all active sessions."""
    return {
        "count": len(_sessions),
        "sessions": [
            {"session_id": s["session_id"], "status": s["status"],
             "filename": s.get("filename")}
            for s in _sessions.values()
        ],
    }


@app.get("/api/model-info")
async def model_info():
    """Return information about the loaded risk model."""
    risk_model = _get_risk_model()
    if risk_model is None:
        return {"status": "not_loaded", "message": "No trained risk model available."}
    return {
        "status": "loaded",
        "model_name": risk_model.model_name,
        "feature_names": risk_model.feature_names,
        "metrics": risk_model.metrics.to_dict() if risk_model.metrics else None,
    }


@app.get("/api/datasets")
async def list_datasets():
    """Browse available datasets."""
    external_dir = config.project_root / "data" / "external"
    raw_dir = config.raw_dir
    datasets = []

    # External datasets
    if external_dir.exists():
        for d in sorted(external_dir.iterdir()):
            if d.is_dir():
                meta = d / "metadata.jsonl"
                count = 0
                if meta.exists():
                    with open(meta, "r", encoding="utf-8") as f:
                        count = sum(1 for _ in f)
                else:
                    count = len(list(d.rglob("*.png"))) + len(list(d.rglob("*.jpg")))

                datasets.append({
                    "name": d.name,
                    "path": str(d),
                    "sample_count": count,
                    "has_metadata": meta.exists(),
                    "type": "external",
                })

    # Raw uploaded images
    if raw_dir.exists():
        raw_images = list(raw_dir.glob("*.png")) + list(raw_dir.glob("*.jpg"))
        if raw_images:
            datasets.append({
                "name": "raw_uploads",
                "path": str(raw_dir),
                "sample_count": len(raw_images),
                "has_metadata": False,
                "type": "raw",
            })

    # Sample rubrics
    rubric_count = len(list(config.samples_dir.glob("*.json")))
    datasets.append({
        "name": "sample_rubrics",
        "path": str(config.samples_dir),
        "sample_count": rubric_count,
        "has_metadata": False,
        "type": "rubrics",
    })

    return {"datasets": datasets, "total": len(datasets)}


@app.get("/api/datasets/{name}/samples")
async def get_dataset_samples(name: str, offset: int = 0, limit: int = 20):
    """Get samples from a specific dataset."""
    external_dir = config.project_root / "data" / "external"
    dataset_dir = external_dir / name

    if not dataset_dir.exists():
        raise HTTPException(404, f"Dataset '{name}' not found.")

    meta_path = dataset_dir / "metadata.jsonl"
    if not meta_path.exists():
        # No metadata — just list image files
        images = sorted(list(dataset_dir.rglob("*.png")) + list(dataset_dir.rglob("*.jpg")))
        total = len(images)
        page = images[offset:offset + limit]
        return {
            "dataset": name,
            "total": total,
            "offset": offset,
            "limit": limit,
            "samples": [{"image_file": str(p.relative_to(dataset_dir))} for p in page],
        }

    # Load metadata page
    samples = []
    total = 0
    with open(meta_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            total += 1
            if i >= offset and len(samples) < limit:
                samples.append(json.loads(line.strip()))

    return {
        "dataset": name,
        "total": total,
        "offset": offset,
        "limit": limit,
        "samples": samples,
    }


@app.post("/api/recognize-from-dataset")
async def recognize_from_dataset(
    dataset: str = Form(...),
    image_file: str = Form(...),
):
    """Run HTR directly on a dataset image (no upload needed)."""
    data_root = config.project_root / "data"
    image_path = data_root / image_file

    if not image_path.exists():
        # Try external prefix
        image_path = data_root / "external" / dataset / image_file

    if not image_path.exists():
        raise HTTPException(404, f"Image not found: {image_file}")

    session_id = str(uuid.uuid4())[:12]

    try:
        pipeline = _get_htr()
        import cv2 as _cv2
        image = _cv2.imread(str(image_path), _cv2.IMREAD_COLOR)
        if image is None:
            raise HTTPException(400, f"Could not read image: {image_path}")

        # For pre-segmented line images (IAM), recognize directly
        recognized = pipeline.recognizer.recognize(image, line_number=1)

        htr_result = {
            "full_text": recognized.text,
            "lines": [{"line_number": 1, "text": recognized.text,
                        "confidence": recognized.confidence}],
            "average_confidence": recognized.confidence,
            "metadata": {"model": getattr(pipeline.recognizer, "model_name", None),
                          "source": f"dataset:{dataset}", "image_file": image_file},
        }

        _sessions[session_id] = {
            "session_id": session_id,
            "original_path": str(image_path),
            "filename": image_path.name,
            "status": "recognized",
            "htr_result": htr_result,
            "created_at": time.time(),
        }

        logger.info("Dataset HTR: %s → \"%s\" (conf=%.3f)",
                     image_path.name, recognized.text, recognized.confidence or 0)
        return {
            "session_id": session_id,
            "status": "recognized",
            "text": recognized.text,
            "confidence": recognized.confidence,
            "image_file": image_file,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Dataset HTR failed: %s", exc)
        raise HTTPException(500, f"HTR failed: {exc}")


@app.get("/api/dataset-image/{dataset}/{path:path}")
async def serve_dataset_image(dataset: str, path: str):
    """Serve a dataset image file."""
    external_dir = config.project_root / "data" / "external"
    image_path = (external_dir / dataset / path).resolve()

    # Prevent path traversal
    if not str(image_path).startswith(str(external_dir.resolve())):
        raise HTTPException(403, "Access denied.")
    if not image_path.exists():
        raise HTTPException(404, "Image not found.")

    return FileResponse(str(image_path))


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _heuristic_risk(features: dict[str, float]) -> dict[str, Any]:
    """Simple heuristic risk estimation when no ML model is trained."""
    factors: list[str] = []
    risk_score = 0.0

    ocr = features.get("ocr_confidence", 1.0)
    if ocr < 0.5:
        factors.append(f"OCR confidence is low ({ocr:.2f})")
        risk_score += 0.3

    eval_conf = features.get("evaluation_confidence", 1.0)
    if eval_conf < 0.5:
        factors.append(f"Evaluation confidence is low ({eval_conf:.2f})")
        risk_score += 0.25

    sim = features.get("overall_semantic_similarity", 1.0)
    if sim < 0.4:
        factors.append(f"Semantic similarity is uncertain ({sim:.2f})")
        risk_score += 0.2

    cov = features.get("rubric_coverage", 1.0)
    if cov < 0.5:
        factors.append(f"Rubric coverage is incomplete ({cov:.1%})")
        risk_score += 0.15

    dev = features.get("mark_deviation_from_mean_criterion", 0.0)
    if dev > 0.2:
        factors.append(f"Score deviates from criterion evidence ({dev:.2f})")
        risk_score += 0.1

    risk_score = min(1.0, risk_score)
    label = "HIGH" if risk_score > 0.4 else "LOW"

    if not factors:
        factors.append("No individual risk indicators identified")

    return {
        "risk_label": label,
        "risk_probability": round(risk_score, 4),
        "contributing_factors": factors,
        "feature_values": features,
        "metadata": {"method": "heuristic", "note": "No trained ML model available"},
    }


def _save_session_result(session: dict[str, Any]) -> None:
    """Persist a completed session as a JSONL record for future training."""
    try:
        results_file = config.results_dir / "completed_evaluations.jsonl"
        review = session.get("examiner_review", {})
        record = {
            "record_id": session["session_id"],
            "question": session.get("rubric", {}).get("question", ""),
            "student_answer": session.get("htr_result", {}).get("full_text", ""),
            "ai_mark": review.get("ai_mark", 0),
            "expert_mark": review.get("examiner_mark", 0),
            "max_marks": review.get("max_marks", 0),
            "absolute_error": review.get("disagreement", 0),
            "is_grading_error": review.get("disagreement", 0) >= config.grading_error_threshold,
            "features": session.get("features", {}),
            "metadata": {"source": "examiner_review", "is_synthetic": False},
        }
        with open(results_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info("Saved evaluation record to %s", results_file)
    except Exception as exc:
        logger.error("Failed to save session result: %s", exc)

from api.script_evaluation import build_script_router
app.include_router(build_script_router(_sessions, _get_evaluator))


@app.get('/api/recognize/{session_id}/page/{page_number}/line/{line_number}')
async def recognition_line_crop(session_id: str, page_number: int, line_number: int):
    """Review the original image evidence for an OCR line; never accept a file path."""
    import cv2
    from fastapi.responses import Response
    session=_sessions.get(session_id)
    if not session: raise HTTPException(404,'Session not found')
    pages=session.get('htr_result',{}).get('metadata',{}).get('pages',[])
    page=next((p for p in pages if p['page_number']==page_number),None)
    region=next((r for r in (page or {}).get('regions',[]) if r['line_number']==line_number),None)
    if not region or not region.get('bounding_box'): raise HTTPException(404,'OCR crop not available')
    sources=session.get('pdf_pages',[])
    source=sources[page_number-1] if 0<page_number<=len(sources) else {}
    path=source.get('recognition_path')
    if not path:
        rendered=Path(session['original_path']).parent/f'pdf_page{page_number}.png'
        path=str(rendered) if session.get('file_type')=='pdf' and rendered.is_file() else session['original_path']
    image=await run_in_threadpool(cv2.imread,str(path))
    if image is None: raise HTTPException(404,'Source image not available')
    x,y,w,h=map(int,region['bounding_box'])
    ih,iw=image.shape[:2];x1,y1=max(0,x-8),max(0,y-8);x2,y2=min(iw,x+w+8),min(ih,y+h+8)
    if x2<=x1 or y2<=y1: raise HTTPException(404,'Invalid crop')
    crop=image[y1:y2,x1:x2]
    scale=min(1.,1600/crop.shape[1],450/crop.shape[0])
    if scale<1: crop=cv2.resize(crop,None,fx=scale,fy=scale)
    ok,encoded=cv2.imencode('.png',crop)
    if not ok: raise HTTPException(500,'Could not encode crop')
    return Response(content=encoded.tobytes(),media_type='image/png',headers={'Cache-Control':'no-store'})
