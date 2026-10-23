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

    def __init__(self, minimum_gap: int = 2, minimum_height: int = 8) -> None:
        self.minimum_gap = minimum_gap
        self.minimum_height = minimum_height

    def segment(self, image: np.ndarray) -> list[LineRegion]:
        gray = self._grayscale(image)
        scale = min(1.0, 1800 / gray.shape[1])
        if scale < 1:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        height, width = gray.shape[:2]
        x_offset, y_offset = 0, 0
        x_limit, y_limit = width, height
        working_gray = gray[y_offset:y_limit, x_offset:x_limit]
        ink = self._ink_without_ruling(working_gray)
        row_counts = np.count_nonzero(ink, axis=1)
        threshold = max(8, int(round(working_gray.shape[1] * 0.003)))
        bands = self._group_rows(row_counts >= threshold)
        # Separate real line centres rather than recursively cutting tall
        # bands into fragments containing descenders from neighbouring lines.
        from scipy.signal import find_peaks
        _, _, components, _ = cv2.connectedComponentsWithStats(ink)
        heights = components[1:, cv2.CC_STAT_HEIGHT]
        glyphs = heights[(heights > 6) & (heights < 120)]
        typical = float(np.percentile(glyphs,90)) if len(glyphs) else 35.
        joined=[]
        for start,end in bands:
            if joined and start-joined[-1][1] < typical*.3:
                joined[-1]=(joined[-1][0],end)
            else: joined.append((start,end))
        bands=[]
        for start,end in joined:
            profile=np.convolve(row_counts[start:end],np.ones(5)/5,mode='same')
            _,_,local_stats,_=cv2.connectedComponentsWithStats(ink[start:end])
            local_heights=local_stats[1:,cv2.CC_STAT_HEIGHT]
            usable=local_heights[(local_heights>6)&(local_heights<max(20,(end-start)*.85))]
            local_typical=float(np.percentile(usable,90)) if len(usable)>5 else typical
            peaks,_=find_peaks(profile,distance=max(8,int(local_typical*1.15)),
                height=threshold,prominence=max(2,float(profile.max())*.06))
            cuts=[start]
            for left,right in zip(peaks,peaks[1:]):
                cut=start+int(left)+int(np.argmin(profile[left:right+1]))
                if cut>cuts[-1]+5:cuts.append(cut)
            cuts.append(end)
            bands.extend(zip(cuts,cuts[1:]))
        regions: list[LineRegion] = []
        for start, end in bands:
            ys, xs = np.where(ink[start:end, :] > 0)
            if len(xs) == 0:
                continue
            x_start, x_end = int(xs.min()) + x_offset, int(xs.max()) + 1 + x_offset
            y_start, y_end = max(0, start - 3) + y_offset, min(working_gray.shape[0], end + 3) + y_offset
            if y_end - y_start < self.minimum_height:
                continue
            if x_end - x_start < max(12, (y_end-y_start) * 0.7):
                continue
            x_start, y_start = int(x_start / scale), int(y_start / scale)
            x_end, y_end = int(x_end / scale), int(y_end / scale)
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
        # Scanned notebook borders are often tilted; morphology alone misses them
        # and their ink bridges otherwise separate handwriting lines.
        rules = cv2.HoughLinesP(ink, 1, np.pi / 180, threshold=60,
                               minLineLength=max(80, gray.shape[1] // 3), maxLineGap=15)
        if rules is not None:
            for x1, y1, x2, y2 in rules.reshape(-1, 4):
                dx, dy = abs(int(x2-x1)), abs(int(y2-y1))
                if (dx > gray.shape[1] * .65 and dx > 12 * max(1,dy)) or dy > 12 * max(1,dx):
                    cv2.line(ink, (x1,y1), (x2,y2), 0, 11)
        ruling_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, gray.shape[1] // 2), 1))
        ink = cv2.subtract(ink, cv2.morphologyEx(ink, cv2.MORPH_OPEN, ruling_kernel))
        # Page borders otherwise connect many separate answer rows into one crop.
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(80, gray.shape[0] // 4)))
        ink = cv2.subtract(ink, cv2.morphologyEx(ink, cv2.MORPH_OPEN, vertical_kernel))
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
        # Build one component lookup table, then scan the label image once.
        # Repeating labels == label for every component costs pixels * components.
        keep = np.zeros(count, dtype=np.uint8)
        if count > 1:
            component_widths = stats[1:, cv2.CC_STAT_WIDTH]
            component_heights = stats[1:, cv2.CC_STAT_HEIGHT]
            component_areas = stats[1:, cv2.CC_STAT_AREA]
            ruling = (component_widths > gray.shape[1] * 0.30) & (component_heights <= 12)
            border_fragment=(stats[1:,cv2.CC_STAT_LEFT]<gray.shape[1]*.12)&(component_heights>max(60,gray.shape[0]*.025))&(component_heights>component_widths*8)
            keep[1:] = (~ruling & ~border_fragment & (component_areas >= 8)).astype(np.uint8) * 255
        filtered = keep[labels]
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


