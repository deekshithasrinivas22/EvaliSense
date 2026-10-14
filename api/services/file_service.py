"""File upload and document processing service for EvaliSense.

Handles:
- PDF to image conversion for answer scripts, question papers, and answer keys
- File validation (type, size, integrity)
- Secure storage path generation
- Checksum computation
"""
from __future__ import annotations

import hashlib
import io
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
from fastapi import HTTPException, UploadFile

from config import config
from utils.logging import get_logger

logger = get_logger(__name__)

# Supported MIME types
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png": [".png"],
    "image/bmp": [".bmp"],
    "image/tiff": [".tif", ".tiff"],
}

ALLOWED_PDF_TYPE = {"application/pdf": [".pdf"]}

ALLOWED_DOCUMENT_TYPES = {**ALLOWED_IMAGE_TYPES, **ALLOWED_PDF_TYPE}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# Magic bytes for file signature validation
FILE_SIGNATURES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG": "image/png",
    b"BM": "image/bmp",
    b"II\x2a\x00": "image/tiff",
    b"MM\x00\x2a": "image/tiff",
    b"%PDF": "application/pdf",
}


def validate_file_signature(content: bytes, expected_mime: str) -> bool:
    """Validate file content against expected MIME type using magic bytes."""
    for signature, mime in FILE_SIGNATURES.items():
        if content[:len(signature)] == signature:
            if mime == expected_mime:
                return True
            # Allow jpeg variants
            if expected_mime.startswith("image/") and mime.startswith("image/"):
                return True
    return False


def compute_checksum(content: bytes) -> str:
    """Compute SHA-256 checksum of file content."""
    return hashlib.sha256(content).hexdigest()


def get_mime_type(filename: str) -> str | None:
    """Determine MIME type from file extension."""
    ext = Path(filename).suffix.lower()
    for mime, exts in ALLOWED_DOCUMENT_TYPES.items():
        if ext in exts:
            return mime
    return None


def validate_upload_file(
    file: UploadFile,
    content: bytes,
    allowed_types: dict[str, list[str]] | None = None,
    max_size: int = MAX_FILE_SIZE,
) -> tuple[bool, str, dict[str, Any]]:
    """Validate an uploaded file for type, size, and integrity.

    Returns (is_valid, message, metadata).
    """
    if allowed_types is None:
        allowed_types = ALLOWED_DOCUMENT_TYPES

    if not file.filename:
        return False, "No filename provided", {}

    ext = Path(file.filename).suffix.lower()
    all_exts = []
    for exts_list in allowed_types.values():
        all_exts.extend(exts_list)

    if ext not in all_exts:
        return False, f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(set(all_exts)))}", {}

    if len(content) > max_size:
        return False, f"File exceeds maximum size of {max_size // (1024*1024)}MB", {}

    if len(content) < 10:
        return False, "File is empty or too small", {}

    mime_type = get_mime_type(file.filename)
    if not mime_type:
        return False, "Could not determine file type", {}

    # Validate file signature
    if not validate_file_signature(content, mime_type):
        return False, "File content does not match expected file type (possible corruption)", {}

    checksum = compute_checksum(content)

    metadata = {
        "mime_type": mime_type,
        "file_size": len(content),
        "checksum": checksum,
        "extension": ext,
    }

    return True, "File validation passed", metadata


def save_uploaded_file(
    content: bytes,
    category: str,
    exam_id: int,
    original_filename: str,
    sub_folder: str | None = None,
) -> tuple[Path, str]:
    """Save file content to the storage directory with a safe generated name.

    Returns (storage_path, safe_filename).
    """
    ext = Path(original_filename).suffix.lower()
    safe_uid = str(uuid.uuid4())[:12]
    safe_filename = f"{category}_{safe_uid}{ext}"

    storage_base = config.storage_dir / category / f"exam_{exam_id}"
    if sub_folder:
        storage_base = storage_base / sub_folder
    storage_base.mkdir(parents=True, exist_ok=True)

    storage_path = storage_base / safe_filename
    with open(storage_path, "wb") as f:
        f.write(content)

    return storage_path, safe_filename


def pdf_to_images(content: bytes) -> list[np.ndarray]:
    """Convert PDF content to a list of images (one per page).

    Uses PIL for basic PDF-to-image conversion. For production, consider
    using pdf2image with poppler, but this approach works with just Pillow.
    """
    images = []
    try:
        # Try using pdf2image if available (best quality)
        from pdf2image import convert_from_bytes
        pil_images = convert_from_bytes(content, dpi=200)
        for pil_img in pil_images:
            img_array = np.array(pil_img.convert("RGB"))
            # Convert RGB to BGR for OpenCV
            img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
            images.append(img_bgr)
        return images
    except ImportError:
        pass

    try:
        # Fallback: try using fitz (PyMuPDF) if available
        import fitz
        doc = fitz.open(stream=content, filetype="pdf")
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(dpi=200)
            img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            if pix.n == 4:  # RGBA
                img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGBA2BGR)
            elif pix.n == 3:  # RGB
                img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
            else:
                img_bgr = img_array
            images.append(img_bgr)
        doc.close()
        return images
    except ImportError:
        pass

    # Last resort: Try treating first page as an image via PIL
    try:
        pil_img = Image.open(io.BytesIO(content))
        # Handle multi-frame images (some TIFFs)
        frame_count = getattr(pil_img, 'n_frames', 1)
        for i in range(frame_count):
            pil_img.seek(i)
            img_rgb = pil_img.convert("RGB")
            img_array = np.array(img_rgb)
            img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
            images.append(img_bgr)
        return images
    except Exception:
        pass

    logger.warning("No PDF conversion library available. Install pdf2image or PyMuPDF for PDF support.")
    return images


def count_pdf_pages(content: bytes) -> int:
    """Count pages in a PDF file."""
    try:
        from pdf2image import pdfinfo_from_bytes
        info = pdfinfo_from_bytes(content)
        return info.get("Pages", 1)
    except (ImportError, Exception):
        pass

    try:
        import fitz
        doc = fitz.open(stream=content, filetype="pdf")
        count = len(doc)
        doc.close()
        return count
    except (ImportError, Exception):
        pass

    # Fallback: count page markers in raw PDF
    try:
        count = content.count(b"/Type /Page") - content.count(b"/Type /Pages")
        return max(1, count)
    except Exception:
        return 1
