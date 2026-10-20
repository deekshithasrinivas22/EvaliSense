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
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

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

# Mount static frontend
_frontend_dir = config.project_root / "frontend"
if _frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_frontend_dir)), name="static")

# Dataset images served via /api/dataset-image endpoint (see below)

# In-memory store for evaluation sessions (use a DB in production)
_sessions: dict[str, dict[str, Any]] = {}

# Lazy-loaded components
_htr_pipeline = None
_evaluator = None
_risk_model = None


def _get_htr():
    global _htr_pipeline
    if _htr_pipeline is None:
        from htr import HTRPipeline
        _htr_pipeline = HTRPipeline()
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

@app.get("/")
async def root():
    """Serve the frontend or return API info."""
    index = _frontend_dir / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "EvaliSense API", "version": "0.1.0", "docs": "/docs"}


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


@app.post("/api/preprocess/{session_id}")
async def preprocess(session_id: str):
    """Run preprocessing on an uploaded file (image, PDF, or text)."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")

    original_path = Path(session["original_path"])
    if not original_path.exists():
        raise HTTPException(404, "Original file not found.")

    file_type = session.get("file_type", original_path.suffix.lstrip(".").lower())

    try:
        # Handle text files — no preprocessing needed
        if file_type == "txt":
            session["status"] = "preprocessed"
            session["preprocessing"] = {"metadata": {"skipped": True, "reason": "Text file needs no image preprocessing"}}
            return {"session_id": session_id, "status": "preprocessed", "details": session["preprocessing"]}

        # Handle PDF files — convert first page to image, then preprocess
        if file_type == "pdf":
            import fitz  # pymupdf
            pdf_doc = fitz.open(str(original_path))
            if pdf_doc.page_count == 0:
                raise HTTPException(400, "PDF has no pages.")

            # Render first page at 300 DPI for high quality OCR
            page = pdf_doc[0]
            mat = fitz.Matrix(300 / 72, 300 / 72)
            pix = page.get_pixmap(matrix=mat)
            image_path = original_path.parent / "pdf_page1.png"
            pix.save(str(image_path))
            pdf_doc.close()

            # Also extract embedded text from all pages
            pdf_doc2 = fitz.open(str(original_path))
            pdf_text_parts = []
            for p in pdf_doc2:
                pdf_text_parts.append(p.get_text())
            pdf_doc2.close()
            embedded_text = "\n".join(pdf_text_parts).strip()

            if embedded_text:
                session["pdf_embedded_text"] = embedded_text

            # Now preprocess the rendered image
            session["original_path_image"] = str(image_path)
            original_path = image_path

        from preprocessing import ImagePreprocessor

        preprocessor = ImagePreprocessor()
        processed_path = original_path.parent / "processed.png"
        result = preprocessor.process(str(original_path), str(processed_path))

        session["processed_path"] = str(processed_path)
        session["preprocessing"] = {
            "input_shape": list(result.original.shape) if result.original is not None else None,
            "output_shape": list(result.final.shape) if result.final is not None else None,
            "metadata": result.metadata,
        }
        session["status"] = "preprocessed"

        logger.info("Preprocessing complete for session %s", session_id)
        return {"session_id": session_id, "status": "preprocessed", "details": session["preprocessing"]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Preprocessing failed: %s", exc)
        raise HTTPException(500, f"Preprocessing failed: {exc}")


@app.post("/api/recognize/{session_id}")
async def recognize(session_id: str):
    """Run HTR on the (optionally preprocessed) image, or return extracted text for PDF/TXT."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")

    file_type = session.get("file_type", "")

    # For text files, return the text directly
    if file_type == "txt" and session.get("extracted_text"):
        text = session["extracted_text"]
        lines = text.split("\n")
        session["htr_result"] = {
            "full_text": text,
            "lines": [{"line_number": i + 1, "text": l, "confidence": 1.0} for i, l in enumerate(lines)],
            "average_confidence": 1.0
        }
        session["status"] = "recognized"
        return {
            "session_id": session_id,
            "status": "recognized",
            "text": text,
            "lines": [{"line_number": i + 1, "text": l, "confidence": 1.0} for i, l in enumerate(lines)],
            "average_confidence": 1.0,
        }

    # For PDFs with embedded text, prefer that over OCR
    if file_type == "pdf" and session.get("pdf_embedded_text"):
        text = session["pdf_embedded_text"]
        lines = text.split("\n")
        session["htr_result"] = {
            "full_text": text,
            "lines": [{"line_number": i + 1, "text": l, "confidence": 0.95} for i, l in enumerate(lines) if l.strip()],
            "average_confidence": 0.95
        }
        session["status"] = "recognized"
        return {
            "session_id": session_id,
            "status": "recognized",
            "text": text,
            "lines": [{"line_number": i + 1, "text": l, "confidence": 0.95} for i, l in enumerate(lines) if l.strip()],
            "average_confidence": 0.95,
        }

    # For images (and PDFs converted to images), run HTR
    image_path = session.get("processed_path", session.get("original_path_image", session.get("original_path")))
    if not image_path or not Path(image_path).exists():
        raise HTTPException(404, "Image not found for recognition.")

    try:
        pipeline = _get_htr()
        debug_dir = Path(session["original_path"]).parent / "debug"
        result = pipeline.recognize_path(image_path, debug_dir)

        session["htr_result"] = result.to_dict()
        session["status"] = "recognized"

        logger.info("HTR complete for session %s: %d lines, confidence=%.3f",
                     session_id, len(result.lines),
                     result.average_confidence or 0)
        return {
            "session_id": session_id,
            "status": "recognized",
            "text": result.full_text,
            "lines": [{"line_number": l.line_number, "text": l.text,
                        "confidence": l.confidence} for l in result.lines],
            "average_confidence": result.average_confidence,
        }
    except Exception as exc:
        logger.error("HTR failed: %s", exc)
        raise HTTPException(500, f"HTR failed: {exc}")


@app.post("/api/extract-questions")
async def extract_questions(file: UploadFile = File(...)):
    """Extract questions and marks from an uploaded question paper (PDF, TXT, or image).
    Returns structured JSON with detected questions and allocated marks."""
    import re

    if not file.filename:
        raise HTTPException(400, "No filename provided.")

    ext = Path(file.filename).suffix.lower()
    content_bytes = await file.read()
    extracted_text = ""

    # Step 1: Extract raw text based on file type
    if ext == ".txt":
        extracted_text = content_bytes.decode("utf-8", errors="replace")

    elif ext == ".pdf":
        import fitz
        tmp_path = config.results_dir / f"qp_{uuid.uuid4().hex[:8]}.pdf"
        with open(tmp_path, "wb") as f:
            f.write(content_bytes)
        try:
            doc = fitz.open(str(tmp_path))
            pages_text = [page.get_text() for page in doc]
            doc.close()
            extracted_text = "\n".join(pages_text)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

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
        raise HTTPException(400, "Could not extract any text from the uploaded file.")

    # Step 2: Parse extracted text to find questions and marks
    questions = _parse_questions_from_text(extracted_text)

    logger.info("Extracted %d questions from %s", len(questions), file.filename)
    return {
        "filename": file.filename,
        "extracted_text": extracted_text,
        "questions": questions,
        "total_questions": len(questions),
        "total_marks": sum(q.get("max_marks", 0) for q in questions)
    }


def _parse_questions_from_text(text: str) -> list:
    """Parse text to extract questions with their number, text, and allocated marks."""
    import re

    questions = []
    lines = text.split("\n")
    lines = [l.strip() for l in lines if l.strip()]

    # Common patterns for questions in exam papers:
    # Q1. text ... [5 marks] / (5 marks) / (5M) / 5 Marks
    # 1. text
    # 1) text
    # Question 1: text
    q_pattern = re.compile(
        r'^(?:Q(?:uestion)?\.?\s*)?(\d+)\s*[\.\)\:]?\s*(.+)',
        re.IGNORECASE
    )
    marks_pattern = re.compile(
        r'[\[\(]\s*(\d+(?:\.\d+)?)\s*(?:marks?|m|pts?|points?)?\s*[\]\)]'
        r'|(\d+(?:\.\d+)?)\s*(?:marks?|m)\b',
        re.IGNORECASE
    )

    current_q = None

    for line in lines:
        # Skip headers/titles
        if any(kw in line.lower() for kw in ['question paper', 'examination', 'university', 'semester', 'time:', 'date:', 'max marks', 'instructions', 'note:', 'answer any', 'answer all']):
            continue

        q_match = q_pattern.match(line)
        if q_match:
            # Save previous question
            if current_q:
                questions.append(current_q)

            q_num = int(q_match.group(1))
            q_text = q_match.group(2).strip()

            # Extract marks from the line
            marks_val = 0
            m_match = marks_pattern.search(line)
            if m_match:
                marks_str = m_match.group(1) or m_match.group(2)
                marks_val = float(marks_str)
                # Remove marks notation from question text
                q_text = marks_pattern.sub('', q_text).strip()
                q_text = q_text.rstrip('.-–—:').strip()

            current_q = {
                "question_number": q_num,
                "question_text": q_text,
                "max_marks": marks_val,
                "reference_answer": "",
                "criteria": []
            }
        elif current_q:
            # Check if this line has sub-parts (a), b), etc.)
            sub_match = re.match(r'^[a-z]\)\s*(.+)', line, re.IGNORECASE)
            if sub_match:
                sub_text = sub_match.group(1).strip()
                sub_marks = 0
                sm = marks_pattern.search(line)
                if sm:
                    sub_marks = float(sm.group(1) or sm.group(2))
                    sub_text = marks_pattern.sub('', sub_text).strip()

                current_q["criteria"].append({
                    "id": f"c{len(current_q['criteria']) + 1}",
                    "description": sub_text,
                    "marks": sub_marks,
                    "keywords": []
                })
            else:
                # Continuation of question text
                m_check = marks_pattern.search(line)
                if m_check and not current_q["max_marks"]:
                    current_q["max_marks"] = float(m_check.group(1) or m_check.group(2))
                else:
                    current_q["question_text"] += " " + line

    # Don't forget last question
    if current_q:
        questions.append(current_q)

    # If no marks were found, assign default marks
    for q in questions:
        if not q["max_marks"]:
            q["max_marks"] = 5.0  # Default
        # Clean up extra whitespace
        q["question_text"] = " ".join(q["question_text"].split())

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
