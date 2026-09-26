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
    version="0.1.0",
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

# Mount static frontend
_frontend_dir = config.project_root / "frontend"
if _frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_frontend_dir)), name="static")

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
    """Upload a handwritten answer image."""
    if not file.filename:
        raise HTTPException(400, "No filename provided.")

    ext = Path(file.filename).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
        raise HTTPException(400, f"Unsupported file format: {ext}")

    session_id = str(uuid.uuid4())[:12]
    session_dir = config.results_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    original_path = session_dir / f"original{ext}"
    with open(original_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    _sessions[session_id] = {
        "session_id": session_id,
        "original_path": str(original_path),
        "filename": file.filename,
        "status": "uploaded",
        "created_at": time.time(),
    }

    logger.info("Image uploaded: %s → session %s", file.filename, session_id)
    return {"session_id": session_id, "filename": file.filename, "status": "uploaded"}


@app.post("/api/preprocess/{session_id}")
async def preprocess(session_id: str):
    """Run preprocessing on an uploaded image."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")

    from preprocessing import ImagePreprocessor

    original_path = Path(session["original_path"])
    if not original_path.exists():
        raise HTTPException(404, "Original image not found.")

    try:
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
    except Exception as exc:
        logger.error("Preprocessing failed: %s", exc)
        raise HTTPException(500, f"Preprocessing failed: {exc}")


@app.post("/api/recognize/{session_id}")
async def recognize(session_id: str):
    """Run HTR on the (optionally preprocessed) image."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")

    image_path = session.get("processed_path", session.get("original_path"))
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
