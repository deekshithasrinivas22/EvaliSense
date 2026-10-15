"""PDF validation, page rendering, and processing service for EvaliSense.

Handles:
- PDF document validation (MIME, magic header, file size, page limits, dimensions)
- Detection of corrupted, encrypted, or empty PDFs
- High-resolution (approx. 300 DPI) page rendering to PNG images
- Low memory consumption via single-page sequential streaming and cleanup
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pymupdf
from fastapi import UploadFile

from config import config
from utils.logging import get_logger

logger = get_logger(__name__)

ALLOWED_PDF_EXTENSIONS = {".pdf"}
ALLOWED_PDF_MIME_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/acrobat",
    "applications/vnd.pdf",
    "text/pdf",
    "application/octet-stream",  # generic binary often sent by browsers
}


def calculate_render_scale(
    rect: pymupdf.Rect,
    target_dpi: int | None = None,
    max_width: int | None = None,
    max_height: int | None = None,
    max_pixels: int | None = None,
) -> tuple[float, int, int, float]:
    """Calculate adaptive rendering scale, output dimensions, and effective DPI.

    Preserves the original aspect ratio and page order, and ensures the rendered page stays within
    configured width, height, and total pixel limits.

    Args:
        rect: Page rectangle in PDF points.
        target_dpi: Desired target DPI (defaults to config.pdf_render_dpi, e.g. 200).
        max_width: Maximum allowed pixel width (defaults to config.pdf_max_render_width).
        max_height: Maximum allowed pixel height (defaults to config.pdf_max_render_height).
        max_pixels: Maximum allowed total pixels (defaults to config.pdf_max_render_pixels).

    Returns:
        tuple of (scale: float, width_px: int, height_px: int, effective_dpi: float)
    """
    w_pt = float(rect.width)
    h_pt = float(rect.height)
    if w_pt <= 0 or h_pt <= 0:
        raise ValueError(f"Invalid PDF page dimensions: {w_pt}x{h_pt} pt")

    dpi = target_dpi if target_dpi is not None else config.pdf_render_dpi
    max_w = max_width if max_width is not None else config.pdf_max_render_width
    max_h = max_height if max_height is not None else config.pdf_max_render_height
    max_px = max_pixels if max_pixels is not None else config.pdf_max_render_pixels

    # Nominal scale factor based on target DPI (72 PDF points = 1 inch)
    nominal_scale = dpi / 72.0
    cand_w = w_pt * nominal_scale
    cand_h = h_pt * nominal_scale
    cand_pixels = cand_w * cand_h

    scale_factor = 1.0
    if cand_w > max_w:
        scale_factor = min(scale_factor, max_w / cand_w)
    if cand_h > max_h:
        scale_factor = min(scale_factor, max_h / cand_h)
    if cand_pixels > max_px:
        scale_factor = min(scale_factor, math.sqrt(max_px / cand_pixels))

    effective_scale = nominal_scale * scale_factor
    out_w = max(1, int(round(w_pt * effective_scale)))
    out_h = max(1, int(round(h_pt * effective_scale)))
    effective_dpi = effective_scale * 72.0

    return effective_scale, out_w, out_h, effective_dpi


def get_pdf_page_render_info(
    pdf_path: Path | str,
    target_dpi: int | None = None,
) -> list[dict[str, Any]]:
    """Inspect all pages and calculate their safe rendering dimensions without writing images to disk."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    doc = pymupdf.open(str(path))
    info_list: list[dict[str, Any]] = []
    try:
        for idx in range(doc.page_count):
            page = doc[idx]
            scale, out_w, out_h, eff_dpi = calculate_render_scale(page.rect, target_dpi=target_dpi)
            info_list.append({
                "page_number": idx + 1,
                "pt_width": round(page.rect.width, 2),
                "pt_height": round(page.rect.height, 2),
                "rendered_width": out_w,
                "rendered_height": out_h,
                "scale": round(scale, 4),
                "effective_dpi": round(eff_dpi, 1),
                "total_pixels": out_w * out_h,
            })
        return info_list
    finally:
        doc.close()


def validate_pdf_document(
    file: UploadFile,
    content: bytes,
) -> tuple[bool, str, dict[str, Any]]:
    """Validate uploaded PDF document format, size, encryption, and visual quality.

    Returns:
        tuple of (is_valid: bool, error_or_success_message: str, metadata: dict)
    """
    if not file.filename:
        return False, "No filename provided for uploaded document.", {}

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_PDF_EXTENSIONS:
        return False, f"Unsupported file extension '{ext}' for PDF. Allowed: {', '.join(sorted(ALLOWED_PDF_EXTENSIONS))}", {}

    max_size = config.max_upload_size_bytes
    if len(content) > max_size:
        return (
            False,
            f"File exceeds maximum upload size of {max_size / (1024 * 1024):.0f}MB (got {len(content) / (1024 * 1024):.1f}MB).",
            {},
        )

    if len(content) == 0:
        return False, "Uploaded PDF file is empty (0 bytes).", {}

    # Inspect magic header (%PDF-)
    # Per PDF specifications, %PDF- must appear in the first 1024 bytes.
    header_sample = content[:1024]
    if b"%PDF-" not in header_sample:
        return False, "Invalid PDF file: Missing standard %PDF- header.", {}

    # MIME type check if supplied by client
    if file.content_type:
        mime = file.content_type.lower().strip()
        if mime not in ALLOWED_PDF_MIME_TYPES:
            return False, f"Invalid MIME type '{file.content_type}' for PDF document.", {}

    # Attempt opening with PyMuPDF
    doc = None
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:
        logger.warning("PyMuPDF failed to parse PDF document: %s", exc)
        return False, f"Corrupted or malformed PDF file: {str(exc)}", {}

    try:
        # Check password protection / encryption
        if doc.is_encrypted or doc.needs_pass:
            return False, "PDF document is password-protected or encrypted. Please provide an unencrypted answer sheet.", {}

        page_count = doc.page_count
        if page_count == 0:
            return False, "PDF document contains no pages or is empty.", {}

        if page_count > config.max_pdf_pages:
            return (
                False,
                f"PDF exceeds the maximum allowed limit of {config.max_pdf_pages} pages (got {page_count} pages).",
                {"page_count": page_count},
            )

        # Inspect page geometry and safeguard against corrupted/zero dimensions or unrenderable documents
        for i in range(page_count):
            try:
                page = doc[i]
                rect = page.rect
                if rect.width <= 0 or rect.height <= 0:
                    return False, f"PDF page #{i + 1} has invalid or zero dimensions.", {}

                # Calculate render scale to verify page can be safely scaled and rendered
                scale, out_w, out_h, eff_dpi = calculate_render_scale(rect)
                if out_w <= 0 or out_h <= 0 or eff_dpi < 20.0:
                    return (
                        False,
                        f"PDF page #{i + 1} dimensions ({rect.width:.0f}x{rect.height:.0f} pt) cannot be safely rendered.",
                        {},
                    )
            except Exception as exc:
                return False, f"Error inspecting PDF page #{i + 1}: {str(exc)}", {}

        # Quality check: Render page 0 preview to assess sharpness/blur
        try:
            page0 = doc[0]
            scale, out_w, out_h, eff_dpi = calculate_render_scale(page0.rect)
            mat = pymupdf.Matrix(scale, scale)
            pix = page0.get_pixmap(matrix=mat, alpha=False)

            # Convert pixmap samples to OpenCV BGR image
            img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 3:
                cv_img = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
            elif pix.n == 1:
                cv_img = cv2.cvtColor(img_array, cv2.COLOR_GRAY2BGR)
            else:
                cv_img = cv2.cvtColor(img_array[:, :, :3], cv2.COLOR_RGB2BGR)

            gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
            blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()

            is_blurry = blur_score < 15.0
            quality = "POOR" if is_blurry else ("EXCELLENT" if blur_score > 150 else "ACCEPTABLE")

            metadata = {
                "is_pdf": True,
                "page_count": page_count,
                "width": pix.width,
                "height": pix.height,
                "effective_dpi": round(eff_dpi, 1),
                "blur_score": float(round(blur_score, 2)),
                "quality": quality,
                "is_blurry": is_blurry,
            }

            # Explicit memory cleanup
            pix = None
            del img_array
            del cv_img
            del gray

            if is_blurry:
                return (
                    False,
                    f"PDF first page is excessively blurry (blur score: {blur_score:.1f}). Please provide a sharper scan.",
                    metadata,
                )

            return True, "PDF validation passed", metadata

        except Exception as exc:
            logger.warning("Error rendering PDF page preview: %s", exc)
            return False, f"Failed to render PDF page image: {str(exc)}", {}

    finally:
        if doc is not None:
            doc.close()


def render_pdf_pages(
    pdf_path: Path | str,
    output_dir: Path | str,
    dpi: int | None = None,
    max_width: int | None = None,
    max_height: int | None = None,
    max_pixels: int | None = None,
) -> list[Path]:
    """Render all pages of a PDF document to individual PNG images.

    Uses adaptive resolution scaling to keep each rendered page within configured
    width, height, and pixel safety bounds, preserving aspect ratio and page order.
    Memory consumption is strictly bounded by rendering and writing one page at a time,
    then disposing the pixmap and page resources before proceeding.

    Returns:
        List of Path objects for the rendered page images in sequential order.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    target_dpi = dpi if dpi is not None else config.pdf_render_dpi
    rendered_files: list[Path] = []
    doc = pymupdf.open(str(path))
    try:
        if doc.is_encrypted or doc.needs_pass:
            raise ValueError("Cannot render encrypted PDF document.")

        total_pages = doc.page_count
        logger.info(
            "Rendering %d pages from PDF '%s' (target DPI %d, max bounds %dx%d)...",
            total_pages,
            path.name,
            target_dpi,
            max_width or config.pdf_max_render_width,
            max_height or config.pdf_max_render_height,
        )

        for page_idx in range(total_pages):
            page = doc[page_idx]
            page_file = out_dir / f"page_{page_idx + 1:03d}.png"

            scale, out_w, out_h, eff_dpi = calculate_render_scale(
                page.rect,
                target_dpi=target_dpi,
                max_width=max_width,
                max_height=max_height,
                max_pixels=max_pixels,
            )

            # Render single page with adaptive scale
            mat = pymupdf.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(str(page_file))

            logger.info(
                "Rendered page %d/%d (%dx%d px, scale=%.3f, eff_dpi=%.1f) to '%s'",
                page_idx + 1,
                total_pages,
                pix.width,
                pix.height,
                scale,
                eff_dpi,
                page_file.name,
            )

            # Immediate resource release
            pix = None
            rendered_files.append(page_file)

        logger.info("Successfully rendered %d pages to '%s'", len(rendered_files), out_dir)
        return rendered_files

    finally:
        doc.close()


def create_synthetic_pdf(
    output_path: Path | str,
    pages_text: list[str],
    encrypted: bool = False,
    password: str | None = None,
) -> Path:
    """Create a synthetic PDF document for testing purposes."""
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open()
    try:
        for text in pages_text:
            page = doc.new_page(width=595, height=842)  # A4 standard
            # Insert text line
            page.insert_text(pymupdf.Point(50, 100), text, fontsize=16)

        if encrypted:
            user_pw = password or "secret123"
            # PyMuPDF encryption permissions
            doc.save(
                str(dest),
                encryption=pymupdf.PDF_ENCRYPT_AES_256,
                user_pw=user_pw,
                owner_pw=user_pw,
            )
        else:
            doc.save(str(dest))

        return dest
    finally:
        doc.close()
