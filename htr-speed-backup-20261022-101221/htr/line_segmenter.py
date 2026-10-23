from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class LineRegion:
    """An ordered crop region for one candidate handwritten line."""

    line_number: int
    bounding_box: tuple[int, int, int, int]
    image: np.ndarray


class HandwritingLineSegmenter:
    """Segment a full page using ink projections after suppressing ruling lines."""

    def __init__(self, minimum_gap: int = 8, minimum_height: int = 8) -> None:
        self.minimum_gap = minimum_gap
        self.minimum_height = minimum_height

    def segment(self, image: np.ndarray) -> list[LineRegion]:
        gray = self._grayscale(image)
        height, width = gray.shape[:2]
        x_offset, y_offset = int(width * 0.15), int(height * 0.04)
        x_limit, y_limit = int(width * 0.95), int(height * 0.98)
        working_gray = gray[y_offset:y_limit, x_offset:x_limit]
        ink = self._ink_without_ruling(working_gray)
        row_counts = np.count_nonzero(ink, axis=1)
        threshold = max(8, int(round(working_gray.shape[1] * 0.05)))
        bands = self._group_rows(row_counts >= threshold)
        regions: list[LineRegion] = []
        for start, end in bands:
            ys, xs = np.where(ink[start:end, :] > 0)
            if len(xs) == 0:
                continue
            x_start, x_end = int(xs.min()) + x_offset, int(xs.max()) + 1 + x_offset
            y_start, y_end = max(0, start - 3) + y_offset, min(working_gray.shape[0], end + 3) + y_offset
            if y_end - y_start < self.minimum_height:
                continue
            regions.append(LineRegion(len(regions) + 1, (x_start, y_start, x_end - x_start, y_end - y_start), image[y_start:y_end, x_start:x_end].copy()))
        return regions

    def _grayscale(self, image: np.ndarray) -> np.ndarray:
        if not isinstance(image, np.ndarray):
            raise TypeError("Image must be a numpy.ndarray")
        if image.size == 0 or image.ndim not in (2, 3):
            raise ValueError("Image must be a non-empty 2D or 3D array")
        if image.ndim == 2:
            return image
        if image.shape[2] == 1:
            return image[:, :, 0]
        if image.shape[2] == 3:
            return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        raise ValueError("Unsupported image channel count")

    def _ink_without_ruling(self, gray: np.ndarray) -> np.ndarray:
        _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        ruling_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, gray.shape[1] // 2), 1))
        ink = cv2.subtract(ink, cv2.morphologyEx(ink, cv2.MORPH_OPEN, ruling_kernel))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            ink, connectivity=8, ltype=cv2.CV_32S
        )
        filtered = np.zeros_like(ink)
        if labels.shape != filtered.shape:
            raise ValueError(
                "Connected-component labels must match the filtered image shape: "
                f"labels={labels.shape}, filtered={filtered.shape}"
            )
        if labels.ndim != 2 or not np.issubdtype(labels.dtype, np.integer):
            raise TypeError(
                "Connected-component labels must be a 2D integer array: "
                f"shape={labels.shape}, dtype={labels.dtype}"
            )
        if filtered.ndim != 2 or filtered.dtype != np.uint8:
            raise TypeError(
                "Filtered ink must be a 2D uint8 array: "
                f"shape={filtered.shape}, dtype={filtered.dtype}"
            )
        for label in range(1, count):
            _, _, width, height, area = stats[label]
            is_ruling_or_border = width > gray.shape[1] * 0.30 and height <= 12
            is_small_noise = area < 8
            if not is_ruling_or_border and not is_small_noise:
                filtered[labels == label] = 255
        ink = filtered
        return cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))

    def _group_rows(self, active_rows: np.ndarray) -> list[tuple[int, int]]:
        bands: list[tuple[int, int]] = []
        start: int | None = None
        last_active: int | None = None
        for index, active in enumerate(active_rows):
            if active and start is None:
                start = index
            if active:
                last_active = index
            elif start is not None and last_active is not None and index - last_active > self.minimum_gap:
                bands.append((start, last_active + 1))
                start = last_active = None
        if start is not None and last_active is not None:
            bands.append((start, last_active + 1))
        return bands
