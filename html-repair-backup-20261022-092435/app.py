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
