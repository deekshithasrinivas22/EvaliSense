"""Question Paper document parsing and automatic question extraction service for EvaliSense.

Handles:
- Upload validation for question paper documents (PDF, PNG, JPG, JPEG, TXT)
- High-fidelity text extraction:
  * Fast direct selectable text extraction from PDFs using PyMuPDF (<50ms)
  * Adaptive bounded OCR fallback for scanned PDF pages using TrOCR
  * Thread-safe singleton model caching to avoid reloading weights per page or request
  * Direct OCR for image uploads (PNG, JPG, JPEG)
  * Plaintext extraction for TXT files
- Intelligent question segmentation & automatic marks extraction:
  * Detects diverse numbering patterns (Q1, Question 1, 1., 1), I., Part A, etc.)
  * Recognizes section headers (SECTION A, PART I, GROUP 1, etc.)
  * Extracts section-level marking instructions ("All questions carry 2 marks each", "5 x 2 = 10 Marks", etc.)
  * Extracts subquestions ((a), (b), i), ii), etc.) with individual marks
  * Aggregates subquestion marks to parent totals when supported
  * Supports tabular layout formats (| 1 | Question | 5 |)
  * Extracts explicit inline marks in various formats ([5], [5 Marks], (10M), 5 marks, Marks: 10, 5M)
  * Avoids misinterpreting question numbers, years, page numbers, or MCQ option letters as marks
  * Confidence categorization: HIGH (explicit inline/subquestion sum), MEDIUM (inferred from section rule), LOW (unresolved)
  * Retains marks provenance/source rule tracking for teacher auditability
"""
from __future__ import annotations

import io
import re
import threading
from pathlib import Path
from typing import Any

from fastapi import UploadFile
import pymupdf

from api.services.pdf_service import calculate_render_scale
from config import config
from utils.logging import get_logger

logger = get_logger(__name__)

ALLOWED_QP_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".txt"}
MAX_QP_FILE_SIZE = 25 * 1024 * 1024  # 25 MB

# Concurrency-safe model singletons for efficient OCR
_cached_htr_pipeline = None
_cached_preprocessor = None
_htr_lock = threading.Lock()


def get_cached_htr_pipeline():
    """Retrieve or initialize singleton HTR pipeline to avoid reloading weights."""
    global _cached_htr_pipeline
    with _htr_lock:
        if _cached_htr_pipeline is None:
            from htr.pipeline import HTRPipeline
            _cached_htr_pipeline = HTRPipeline()
        return _cached_htr_pipeline


def get_cached_image_preprocessor():
    """Retrieve or initialize singleton ImagePreprocessor."""
    global _cached_preprocessor
    with _htr_lock:
        if _cached_preprocessor is None:
            from preprocessing.image_preprocessor import ImagePreprocessor
            _cached_preprocessor = ImagePreprocessor()
        return _cached_preprocessor


def validate_question_paper_file(file: UploadFile, content: bytes) -> tuple[bool, str, dict[str, Any]]:
    """Validate uploaded question paper format, size, and integrity."""
    if not file.filename:
        return False, "No filename provided for uploaded question paper.", {}

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_QP_EXTENSIONS:
        return False, f"Unsupported file format '{ext}'. Allowed formats: PDF, PNG, JPG, JPEG, TXT.", {}

    if len(content) > MAX_QP_FILE_SIZE:
        return False, f"File exceeds maximum size of 25MB (got {len(content) / (1024 * 1024):.1f}MB).", {}

    if len(content) == 0:
        return False, "Uploaded question paper is empty (0 bytes).", {}

    meta: dict[str, Any] = {
        "filename": file.filename,
        "extension": ext,
        "size_bytes": len(content),
    }

    if ext == ".pdf":
        if b"%PDF-" not in content[:1024]:
            return False, "Invalid PDF: missing standard %PDF- header.", {}
        try:
            doc = pymupdf.open(stream=content, filetype="pdf")
            if doc.is_encrypted or doc.needs_pass:
                doc.close()
                return False, "PDF is password-protected or encrypted. Please provide an unencrypted question paper.", {}
            if doc.page_count == 0:
                doc.close()
                return False, "PDF document contains no pages.", {}
            meta["page_count"] = doc.page_count
            doc.close()
        except Exception as exc:
            return False, f"Corrupted or invalid PDF file: {str(exc)}", {}
    elif ext in {".png", ".jpg", ".jpeg"}:
        meta["page_count"] = 1
        is_valid_img = (
            content.startswith(b"\x89PNG\r\n\x1a\n")
            or content.startswith(b"\xff\xd8\xff")
        )
        if not is_valid_img:
            return False, "Corrupted image file or unrecognized image header.", {}
    elif ext == ".txt":
        meta["page_count"] = 1

    return True, "Validation successful.", meta


def extract_text_from_pdf(
    content: bytes,
    ocr_fallback: bool = True,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Extract text from a PDF document, falling back to OCR on scanned/empty pages.

    Returns:
        tuple of (full_text: str, page_records: list[dict], warnings: list[str])
    """
    doc = pymupdf.open(stream=content, filetype="pdf")
    page_records: list[dict[str, Any]] = []
    warnings: list[str] = []
    combined_texts: list[str] = []

    try:
        total_pages = doc.page_count
        for idx in range(total_pages):
            page = doc[idx]
            page_num = idx + 1
            text = page.get_text("text").strip()

            used_ocr = False
            # If selectable text is missing or extremely short (< 20 characters) and OCR is enabled,
            # render page safely and perform OCR using cached pipeline
            if len(text) < 20 and ocr_fallback:
                try:
                    logger.info("Page %d has minimal selectable text; attempting OCR fallback...", page_num)
                    scale, out_w, out_h, eff_dpi = calculate_render_scale(page.rect, target_dpi=200)
                    mat = pymupdf.Matrix(scale, scale)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    img_bytes = pix.tobytes("png")
                    pix = None

                    ocr_text = extract_text_from_image_bytes(img_bytes)
                    if ocr_text.strip():
                        text = ocr_text.strip()
                        used_ocr = True
                        warnings.append(f"Page {page_num} was processed using OCR as it appeared to be scanned.")
                except Exception as exc:
                    logger.warning("OCR fallback failed on page %d: %s", page_num, exc)
                    warnings.append(f"Page {page_num} text could not be extracted via OCR: {str(exc)}")

            if not text:
                warnings.append(f"Page {page_num} yielded no readable text.")

            page_records.append({
                "page_number": page_num,
                "text": text,
                "used_ocr": used_ocr,
                "pt_width": round(page.rect.width, 1),
                "pt_height": round(page.rect.height, 1),
            })
            if text:
                combined_texts.append(text)

        full_text = "\n\n".join(combined_texts)
        return full_text, page_records, warnings

    finally:
        doc.close()


def extract_text_from_image_bytes(image_bytes: bytes) -> str:
    """Run preprocessing and OCR recognition on image bytes using cached pipelines."""
    import cv2
    import numpy as np

    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        return ""

    preprocessor = get_cached_image_preprocessor()
    gray = preprocessor.to_grayscale(img)
    enhanced = preprocessor.enhance_contrast(gray)

    pipeline = get_cached_htr_pipeline()
    result = pipeline.recognize_image(enhanced)
    return result.full_text or ""


def extract_text_from_docx_bytes(content: bytes) -> str:
    """Extract plain text paragraphs from a .docx file using standard library."""
    import xml.etree.ElementTree as ET
    import zipfile

    try:
        with io.BytesIO(content) as bio:
            with zipfile.ZipFile(bio) as z:
                xml_content = z.read("word/document.xml")
                tree = ET.fromstring(xml_content)
                paragraphs = []
                for p in tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                    texts = [
                        node.text
                        for node in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                        if node.text
                    ]
                    if texts:
                        paragraphs.append("".join(texts))
                return "\n".join(paragraphs)
    except Exception as exc:
        logger.warning("DOCX extraction error: %s", exc)
        return ""


def extract_text_from_document(
    file: UploadFile,
    content: bytes,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Route document to appropriate text extraction workflow."""
    ext = Path(file.filename or "").suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(content)
    elif ext in {".png", ".jpg", ".jpeg"}:
        text = extract_text_from_image_bytes(content)
        warnings = []
        if not text.strip():
            warnings.append("No text could be recognized from the uploaded image.")
        return text, [{"page_number": 1, "text": text, "used_ocr": True}], warnings
    elif ext == ".txt":
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1", errors="replace")
        return text, [{"page_number": 1, "text": text, "used_ocr": False}], []
    elif ext == ".docx":
        text = extract_text_from_docx_bytes(content)
        warnings = []
        if not text.strip():
            warnings.append("No text could be extracted from the uploaded DOCX document.")
        return text, [{"page_number": 1, "text": text, "used_ocr": False}], warnings
    else:
        raise ValueError(f"Unsupported format: {ext}")


# ─────────────────────────────────────────────────────────────────────────────
# Question Segmentation & Advanced Marks Extraction Engine
# ─────────────────────────────────────────────────────────────────────────────

# Section Header regex: SECTION A, PART - I, GROUP B, MODULE 1, PART A (5 x 2 = 10 Marks), etc.
SECTION_HEADER_PATTERN = re.compile(
    r"^(?:(SECTION|PART|GROUP|MODULE)\s*[-:]?\s*([A-Z0-9IVX]+))(?:\s*[:\-–—]?\s*(.*))?$",
    re.IGNORECASE,
)

# Section-level marking instruction patterns
SECTION_RULES = [
    # "All questions carry 2 marks each" / "Each question carries 2 marks"
    (re.compile(r"(?:all|each|every)\s+questions?\s+(?:carry|carries|carrying|worth)\s+(\d+(?:\.\d+)?)\s*marks?", re.IGNORECASE), "carry_each"),
    # "each carrying 10 marks" / "each worth 5 marks"
    (re.compile(r"each\s+(?:carrying|worth)\s+(\d+(?:\.\d+)?)\s*marks?", re.IGNORECASE), "carrying_each"),
    # "(5 x 2 = 10 Marks)" or "5 * 2 = 10" or "4 x 5 = 20 Marks" -> group 1 is question count, group 2 is marks per question
    (re.compile(r"\(?\s*\d+\s*[xX*×]\s*(\d+(?:\.\d+)?)\s*=\s*\d+(?:\.\d+)?\s*(?:marks?)?\s*\)?", re.IGNORECASE), "multiplication"),
    # "2 marks each" or "10 Marks each"
    (re.compile(r"(\d+(?:\.\d+)?)\s*marks?\s+each\b", re.IGNORECASE), "marks_each"),
    # "Answer any 5 questions, each carrying 10 marks"
    (re.compile(r"answer\s+any\s+(?:\d+|[a-z]+)\s+questions?.*?(?:carrying\s+(\d+(?:\.\d+)?)\s*marks?|(\d+(?:\.\d+)?)\s*marks?\s*each)", re.IGNORECASE), "answer_any"),
]

# Range rule: "Questions 1 to 5 carry 2 marks each"
RANGE_RULE_PATTERN = re.compile(
    r"questions?\s+(\d+)\s*(?:to|-)\s*(\d+)\s+(?:carry|carries|worth)\s+(\d+(?:\.\d+)?)\s*marks?",
    re.IGNORECASE,
)

# Inline marks patterns for questions and subquestions
INLINE_MARKS_PATTERNS = [
    # [10 Marks], [10 marks], [10M], [10 m], [10]
    (re.compile(r"\[\s*(\d+(?:\.\d+)?)\s*(?:marks?|m)?\s*\]", re.IGNORECASE), "bracket"),
    # (10 Marks), (10 marks), (10M), (10 m)
    (re.compile(r"\(\s*(\d+(?:\.\d+)?)\s*(?:marks?|m)\s*\)", re.IGNORECASE), "paren_mark"),
    # (10) strictly at end of line or before end of string (guard against MCQ options)
    (re.compile(r"\(\s*(\d+(?:\.\d+)?)\s*\)(?:\s*$)", re.IGNORECASE), "paren_number_end"),
    # "Marks: 10" or "Max Marks: 10" or "Marks = 10"
    (re.compile(r"(?:max(?:imum)?\s+)?marks?\s*[:=]\s*(\d+(?:\.\d+)?)", re.IGNORECASE), "marks_label"),
    # "10 Marks" or "10 marks" at line end
    (re.compile(r"(?:--|-|\b)\s*(\d+(?:\.\d+)?)\s*marks?\s*$", re.IGNORECASE), "marks_suffix"),
    # "5M" or "10M" at line end
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*M\b\s*$", re.IGNORECASE), "m_suffix"),
]

# Question starter regex patterns
QUESTION_START_PATTERNS = [
    # Q1., Q1:, Q.1, Q 1:, Q1 -, Question 1:, Question 1., Question 1 -
    re.compile(r"^(?:Q(?:uestion)?\.?\s*(\d+))\s*[:\.\-]\s*", re.IGNORECASE),
    # Q1, Q2 (without punctuation) followed by space
    re.compile(r"^(?:Q(?:uestion)?\s*(\d+))\s+", re.IGNORECASE),
    # 1., 2., 10.
    re.compile(r"^(\d+)\.\s+"),
    # 1), 2), 10)
    re.compile(r"^(\d+)\)\s+"),
]

# Subquestion starter regex patterns: (a), (b), a), b), (i), (ii), i), ii), i., ii.
SUBQUESTION_PATTERN = re.compile(
    r"^(?:\(([a-z]|[ivx]+)\)|([a-z]|[ivx]+)\)|([a-z]|[ivx]+)\.)\s+",
    re.IGNORECASE,
)

# MCQ options pattern: (a) opt1 (b) opt2 or (1) opt1 (2) opt2
MCQ_OPTIONS_PATTERN = re.compile(
    r"(?:\([1-4a-d]\)|\b[A-D]\.\s+).*?(?:\([1-4a-d]\)|\b[A-D]\.\s+)",
    re.IGNORECASE,
)

# Preamble indicators
PREAMBLE_KEYWORDS = [
    "instructions", "duration", "maximum marks", "max marks", "course code",
    "semester", "department", "time:", "roll no", "reg no", "date of exam",
]


def extract_inline_mark_with_meta(text: str) -> tuple[float | None, str, str | None]:
    """Search for explicit inline marks annotation in text.

    Returns:
        tuple of (marks: float | None, cleaned_text: str, source_repr: str | None)
    """
    for pattern, pat_type in INLINE_MARKS_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                # Group 1 is the marks value
                raw_val = match.group(1) if match.lastindex and match.lastindex >= 1 else None
                if not raw_val:
                    continue
                val = float(raw_val)

                # Avoid false positives: years, 0 marks, or numbers > 100
                if val <= 0 or val > 100.0 or (1990 <= val <= 2040 and pat_type in ["paren_number_end", "bracket"]):
                    continue

                # Guard: if paren_number_end matches (1) or (2) but line contains MCQ options
                if pat_type == "paren_number_end" and val in [1.0, 2.0, 3.0, 4.0] and MCQ_OPTIONS_PATTERN.search(text):
                    continue

                matched_str = match.group(0).strip()
                # Clean annotation from text
                cleaned_text = pattern.sub("", text).strip()
                # Clean trailing dashes or colons
                cleaned_text = re.sub(r"[\s\-–—:]+$", "", cleaned_text).strip()
                return val, cleaned_text, matched_str
            except Exception:
                pass

    return None, text, None


def parse_section_rule(line: str) -> tuple[float | None, str | None]:
    """Check if a line contains a section-level marking rule."""
    for pattern, rule_type in SECTION_RULES:
        match = pattern.search(line)
        if match:
            try:
                # Groups might have val in group 1 or group 2
                val_str = match.group(1) or (match.group(2) if match.lastindex and match.lastindex >= 2 else None)
                if val_str:
                    val = float(val_str)
                    if 0.5 <= val <= 100.0:
                        return val, match.group(0).strip()
            except Exception:
                pass
    return None, None


def parse_questions_from_text(raw_text: str) -> tuple[list[dict[str, Any]], str, list[str]]:
    """Segment document text into individual questions with robust marks detection,
    subquestion aggregation, section tracking, and confidence scoring.

    Returns:
        tuple of (questions: list[dict], preamble: str, warnings: list[str])
    """
    if not raw_text or not raw_text.strip():
        return [], "", ["Document contains no extracted text to parse."]

    lines = [line.strip() for line in raw_text.splitlines()]
    non_empty_lines = [l for l in lines if l]

    questions: list[dict[str, Any]] = []
    preamble_lines: list[str] = []
    warnings: list[str] = []

    # Current section state
    current_section: str | None = None
    section_default_marks: dict[str, float] = {}
    section_rule_texts: dict[str, str] = {}
    range_marks_rules: list[tuple[int, int, float, str]] = []

    current_q_num: int | None = None
    current_q_lines: list[str] = []
    current_subquestions: list[dict[str, Any]] = []
    current_subquestions_raw: list[str] = []
    current_q_section: str | None = None

    def commit_current_question():
        nonlocal current_q_num, current_q_lines, current_subquestions, current_subquestions_raw, current_q_section
        if current_q_num is None and not current_q_lines:
            return

        # Separate parent header lines (before subquestions) from subquestion lines
        parent_lines = []
        for l in current_q_lines:
            if SUBQUESTION_PATTERN.match(l):
                break
            parent_lines.append(l)
        parent_header_text = " ".join(parent_lines).strip()
        parent_inline_mark, _, parent_source = extract_inline_mark_with_meta(parent_header_text)

        # Check entire body for inline mark if no subquestions exist
        combined_body = " ".join(current_q_lines).strip()
        full_inline_mark, cleaned_body, full_source = extract_inline_mark_with_meta(combined_body)

        assigned_marks: float | None = None
        confidence: str = "LOW"
        marks_source: str = ""
        q_warnings: list[str] = []

        # Check subquestion marks total
        sub_marks_sum = 0.0
        sub_marks_count = 0
        for sq in current_subquestions:
            if sq.get("marks") is not None:
                sub_marks_sum += sq["marks"]
                sub_marks_count += 1

        if parent_inline_mark is not None:
            # Explicit mark on parent header line: e.g. "Q3. Answer both parts [5 Marks]:"
            assigned_marks = parent_inline_mark
            confidence = "HIGH"
            marks_source = f"Detected inline: {parent_source}"
            if sub_marks_count > 0:
                if round(sub_marks_sum, 2) == round(parent_inline_mark, 2):
                    marks_source += f" (matches subquestion sum: {sub_marks_sum}M)"
                else:
                    q_warnings.append(
                        f"Subquestion marks total ({sub_marks_sum}) does not match question mark ({parent_inline_mark})."
                    )
        elif sub_marks_count > 0:
            # Parent had no inline mark, but subquestions have individual marks
            assigned_marks = round(sub_marks_sum, 2)
            sub_detail = ", ".join(f"{sq['label']}={sq['marks']}M" for sq in current_subquestions if sq.get("marks") is not None)
            if sub_marks_count == len(current_subquestions):
                confidence = "HIGH"
                marks_source = f"Calculated from subquestions ({sub_detail})"
            else:
                confidence = "MEDIUM"
                marks_source = f"Calculated from partial subquestions ({sub_detail})"
                q_warnings.append(f"Only {sub_marks_count}/{len(current_subquestions)} subquestions specified marks.")
        elif full_inline_mark is not None:
            # Explicit inline mark found on single question
            assigned_marks = full_inline_mark
            confidence = "HIGH"
            marks_source = f"Detected inline: {full_source}"
        elif current_q_num is not None:
            # Check range-based rules (e.g. Questions 1 to 5 carry 2 marks each)
            range_match = None
            for r_from, r_to, r_val, r_text in range_marks_rules:
                if r_from <= current_q_num <= r_to:
                    range_match = (r_val, r_text)
                    break

            if range_match:
                assigned_marks = range_match[0]
                confidence = "MEDIUM"
                marks_source = f"Range rule: '{range_match[1]}'"
            elif current_q_section and current_q_section in section_default_marks:
                # Apply section default rule
                assigned_marks = section_default_marks[current_q_section]
                confidence = "MEDIUM"
                marks_source = f"Section rule ({current_q_section}): '{section_rule_texts.get(current_q_section, '')}'"

        if assigned_marks is None:
            confidence = "LOW"
            marks_source = "Unresolved: Requires teacher mark input"
            q_warnings.append("MARKS REQUIRED: Please specify maximum marks for this question.")

        if not cleaned_body:
            cleaned_body = f"Question {current_q_num or (len(questions) + 1)}"
            q_warnings.append("Question text appears incomplete.")

        questions.append({
            "question_number": current_q_num or (len(questions) + 1),
            "section": current_q_section,
            "question_text": cleaned_body,
            "max_marks": assigned_marks,
            "confidence": confidence,
            "marks_source": marks_source,
            "subquestions": list(current_subquestions),
            "subquestions_text": list(current_subquestions_raw),
            "warnings": q_warnings,
        })

        current_q_num = None
        current_q_lines = []
        current_subquestions = []
        current_subquestions_raw = []

    in_preamble = True

    for line in non_empty_lines:
        # 1. Check for Section Header
        sec_match = SECTION_HEADER_PATTERN.match(line)
        if sec_match:
            commit_current_question()
            prefix = sec_match.group(1).upper()
            sec_id = sec_match.group(2).upper()
            sec_name = f"{prefix} {sec_id}"
            current_section = sec_name
            current_q_section = sec_name

            # Check if section header line itself has instructions (e.g. "SECTION A: 2 Marks Each" or "PART - A (5 x 2 = 10 Marks)")
            trailer = sec_match.group(3) if sec_match.lastindex and sec_match.lastindex >= 3 else ""
            rule_val, rule_txt = parse_section_rule(line)
            if rule_val is None and trailer:
                rule_val, rule_txt = parse_section_rule(trailer)

            if rule_val is not None:
                section_default_marks[current_section] = rule_val
                section_rule_texts[current_section] = rule_txt or line
            continue

        # 2. Check for Section or Range Marking Instruction lines
        rule_val, rule_txt = parse_section_rule(line)
        if rule_val is not None and current_section:
            section_default_marks[current_section] = rule_val
            section_rule_texts[current_section] = rule_txt or line
            continue

        range_match = RANGE_RULE_PATTERN.search(line)
        if range_match:
            try:
                r_from = int(range_match.group(1))
                r_to = int(range_match.group(2))
                r_val = float(range_match.group(3))
                range_marks_rules.append((r_from, r_to, r_val, range_match.group(0)))
                continue
            except Exception:
                pass

        # 3. Check for Question Starters
        matched_q_num = None
        cleaned_line = line

        # Support tabular layout: e.g. | 1 | Define OOP | 2 |
        if "|" in line:
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) >= 2 and parts[0].isdigit():
                try:
                    matched_q_num = int(parts[0])
                    cleaned_line = parts[1]
                    # If third column is numeric, it is marks
                    if len(parts) >= 3:
                        try:
                            t_mark = float(parts[2])
                            cleaned_line += f" [{t_mark} Marks]"
                        except Exception:
                            pass
                except Exception:
                    pass

        if matched_q_num is None:
            for pattern in QUESTION_START_PATTERNS:
                match = pattern.match(line)
                if match:
                    try:
                        matched_q_num = int(match.group(1))
                        cleaned_line = line[match.end():].strip()
                        break
                    except Exception:
                        pass

        if matched_q_num is not None:
            # Start of a new question
            in_preamble = False
            commit_current_question()
            current_q_num = matched_q_num
            current_q_section = current_section

            if cleaned_line:
                # Check if this line is a subquestion
                sub_match = SUBQUESTION_PATTERN.match(cleaned_line)
                if sub_match:
                    sub_label = sub_match.group(0).strip()
                    sq_mark, sq_clean, _ = extract_inline_mark_with_meta(cleaned_line)
                    current_subquestions.append({
                        "label": sub_label,
                        "text": sq_clean,
                        "marks": sq_mark,
                    })
                    current_subquestions_raw.append(cleaned_line)
                current_q_lines.append(cleaned_line)
        else:
            if in_preamble:
                # Check if line looks like exam preamble / header metadata
                lower = line.lower()
                is_preamble = any(k in lower for k in PREAMBLE_KEYWORDS)
                if is_preamble or (len(preamble_lines) < 6 and not any(ch.isdigit() for ch in line[:3])):
                    preamble_lines.append(line)
                    continue
                else:
                    # Haven't seen Q1 yet, start Q1
                    in_preamble = False
                    current_q_num = 1
                    current_q_section = current_section
                    current_q_lines.append(line)
            else:
                # Continuing existing question
                sub_match = SUBQUESTION_PATTERN.match(line)
                if sub_match:
                    sub_label = sub_match.group(0).strip()
                    sq_mark, sq_clean, _ = extract_inline_mark_with_meta(line)
                    current_subquestions.append({
                        "label": sub_label,
                        "text": sq_clean,
                        "marks": sq_mark,
                    })
                    current_subquestions_raw.append(line)
                current_q_lines.append(line)

    commit_current_question()

    # Fallback if no questions separated
    if not questions and non_empty_lines:
        all_text = " ".join(non_empty_lines)
        marks, cleaned, src = extract_inline_mark_with_meta(all_text)
        questions.append({
            "question_number": 1,
            "section": current_section,
            "question_text": cleaned,
            "max_marks": marks,
            "confidence": "HIGH" if marks is not None else "LOW",
            "marks_source": f"Detected inline: {src}" if src else "Unresolved: Teacher input required",
            "subquestions": [],
            "subquestions_text": [],
            "warnings": ["Question numbering could not be automatically separated. Please review and divide into questions if needed."],
        })
        warnings.append("Automatic question numbering was uncertain; grouped into a single draft question for review.")

    # Deduplicate consecutive numbers if needed
    seen: set[int] = set()
    for q in questions:
        if q["question_number"] in seen:
            new_num = max(seen) + 1
            q["warnings"].append(f"Auto-renumbered to Question #{new_num} to avoid duplication.")
            q["question_number"] = new_num
        seen.add(q["question_number"])

    missing_count = sum(1 for q in questions if q.get("max_marks") is None)
    if missing_count > 0:
        warnings.append(f"{missing_count} question(s) are missing explicit mark allocations and require teacher input.")

    preamble = "\n".join(preamble_lines).strip()
    return questions, preamble, warnings


def apply_bulk_marks_to_questions(
    questions: list[dict[str, Any]],
    filter_type: str,
    filter_value: Any,
    marks: float,
) -> list[dict[str, Any]]:
    """Bulk update marks for a subset of parsed questions.

    Args:
        questions: list of question dicts
        filter_type: 'section', 'range', 'unresolved', or 'all'
        filter_value: section name, [start_q, end_q], or None
        marks: non-negative mark value
    """
    for q in questions:
        should_apply = False
        if filter_type == "all":
            should_apply = True
        elif filter_type == "unresolved" and (q.get("max_marks") is None or q.get("max_marks") <= 0):
            should_apply = True
        elif filter_type == "section" and q.get("section") == filter_value:
            should_apply = True
        elif filter_type == "range" and isinstance(filter_value, (list, tuple)) and len(filter_value) == 2:
            start_num, end_num = filter_value
            if start_num <= q.get("question_number", 0) <= end_num:
                should_apply = True

        if should_apply:
            q["max_marks"] = marks
            q["confidence"] = "HIGH"
            q["marks_source"] = f"Bulk assigned by teacher ({marks} Marks)"
            # Clear MARKS REQUIRED warning if present
            q["warnings"] = [w for w in q.get("warnings", []) if "MARKS REQUIRED" not in w]

    return questions
