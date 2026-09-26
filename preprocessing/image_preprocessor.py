from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass
class PreprocessingConfig:
    """Configuration for handwritten-answer image preprocessing."""

    grayscale: bool = True
    denoise: bool = True
    denoise_kernel_size: int = 3
    contrast_enhancement: bool = True
    contrast_clip_limit: float = 2.0
    thresholding: bool = True
    threshold_method: str = "adaptive"
    threshold_value: int = 180
    max_threshold_value: int = 255
    deskew: bool = True
    deskew_angle_threshold: float = 1.0
    save_intermediates: bool = False
    output_extension: str = "png"

    def __post_init__(self) -> None:
        if self.denoise_kernel_size % 2 == 0:
            self.denoise_kernel_size += 1
        if self.denoise_kernel_size < 3:
            self.denoise_kernel_size = 3


@dataclass
class ProcessingResult:
    """Container for the processed image and intermediate pipeline stages."""

    original: np.ndarray | None = None
    grayscale: np.ndarray | None = None
    denoised: np.ndarray | None = None
    enhanced: np.ndarray | None = None
    thresholded: np.ndarray | None = None
    deskewed: np.ndarray | None = None
    final: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ImagePreprocessor:
    """Reusable handwritten-answer image preprocessing pipeline."""

    def __init__(self, config: PreprocessingConfig | None = None) -> None:
        self.config = config or PreprocessingConfig()

    def load_image(self, image_path: str | Path) -> np.ndarray:
        """Load an image from disk and validate that it is non-empty."""
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {path}")
        if not path.is_file():
            raise ValueError(f"Provided path is not a file: {path}")

        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError(f"Could not read image data from: {path}")
        if image.size == 0 or image.shape[0] == 0 or image.shape[1] == 0:
            raise ValueError(f"Image is empty or invalid: {path}")

        return image

    def validate_image(self, image: np.ndarray) -> np.ndarray:
        """Check that the provided array represents a valid image."""
        if not isinstance(image, np.ndarray):
            raise TypeError("Image must be a numpy.ndarray")
        if image.size == 0:
            raise ValueError("Image array is empty")
        if image.ndim not in (2, 3):
            raise ValueError(f"Unsupported image dimensions: {image.ndim}")
        return image

    def to_grayscale(self, image: np.ndarray) -> np.ndarray:
        """Convert a BGR/RGB image to grayscale when needed."""
        image = self.validate_image(image)
        if image.ndim == 2:
            return image.copy()

        channel_count = image.shape[2]
        if channel_count == 1:
            return image[:, :, 0].copy()
        if channel_count == 3:
            return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if channel_count == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        raise ValueError(f"Unsupported channel count for grayscale conversion: {channel_count}")

    def denoise(self, image: np.ndarray) -> np.ndarray:
        """Apply light smoothing to reduce sensor noise while preserving strokes."""
        image = self.validate_image(image)
        if not self.config.denoise:
            return image.copy()

        kernel_size = self.config.denoise_kernel_size
        if image.ndim == 2:
            return cv2.GaussianBlur(image, (kernel_size, kernel_size), 0)
        return cv2.GaussianBlur(image, (kernel_size, kernel_size), 0)

    def enhance_contrast(self, image: np.ndarray) -> np.ndarray:
        """Improve legibility by applying adaptive contrast enhancement."""
        image = self.validate_image(image)
        if not self.config.contrast_enhancement:
            return image.copy()

        if image.ndim != 2:
            image = self.to_grayscale(image)

        clahe = cv2.createCLAHE(
            clipLimit=float(self.config.contrast_clip_limit),
            tileGridSize=(8, 8),
        )
        return clahe.apply(image)

    def threshold_image(self, image: np.ndarray) -> np.ndarray:
        """Convert enhanced grayscale to binary when that is useful for later steps."""
        image = self.validate_image(image)
        if not self.config.thresholding:
            return image.copy()

        if image.ndim != 2:
            image = self.to_grayscale(image)

        if self.config.threshold_method.lower() == "adaptive":
            block_size = 31
            if image.shape[0] < 50 or image.shape[1] < 50:
                block_size = 15
            block_size = max(3, block_size)
            if block_size % 2 == 0:
                block_size += 1
            return cv2.adaptiveThreshold(
                image,
                self.config.max_threshold_value,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                block_size,
                10,
            )

        _, thresholded = cv2.threshold(
            image,
            self.config.threshold_value,
            self.config.max_threshold_value,
            cv2.THRESH_BINARY,
        )
        return thresholded

    def deskew(self, image: np.ndarray) -> np.ndarray:
        """Rotate the page slightly to correct skew when an angle is detectable."""
        image = self.validate_image(image)
        if not self.config.deskew:
            return image.copy()

        if image.ndim != 2:
            image = self.to_grayscale(image)

        if image.size == 0:
            return image.copy()

        edges = cv2.Canny(image, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(
            edges,
            1,
            np.pi / 180,
            threshold=80,
            minLineLength=max(20, min(image.shape[:2]) // 4),
            maxLineGap=10,
        )

        if lines is None:
            return image.copy()

        angles: list[float] = []
        for line in lines:
            segments = line if line.ndim == 2 else [line]
            for segment in segments:
                if len(segment) != 4:
                    continue
                x1, y1, x2, y2 = [int(value) for value in segment]
                if abs(x2 - x1) < 1:
                    continue
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                angles.append(angle)

        if not angles:
            return image.copy()

        median_angle = float(np.median(angles))
        if abs(median_angle) < self.config.deskew_angle_threshold:
            return image.copy()

        # Normalize the angle to a small correction around the horizontal axis.
        if abs(median_angle) > 45:
            corrected = 90 - abs(median_angle)
            if median_angle < 0:
                corrected *= -1
        else:
            corrected = median_angle

        (height, width) = image.shape[:2]
        center = (width / 2.0, height / 2.0)
        rotation_matrix = cv2.getRotationMatrix2D(center, corrected, 1.0)
        rotated = cv2.warpAffine(
            image,
            rotation_matrix,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        return rotated

    def save_image(self, image: np.ndarray, output_path: str | Path) -> Path:
        """Persist an image to disk using a sensible default format."""
        image = self.validate_image(image)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        extension = path.suffix.lower().lstrip(".") or self.config.output_extension
        if extension not in {"png", "jpg", "jpeg", "bmp", "tif", "tiff"}:
            path = path.with_suffix(f".{self.config.output_extension}")

        success = cv2.imwrite(str(path), image)
        if not success:
            raise OSError(f"Failed to write processed image to: {path}")
        return path

    def process(
        self,
        image_path: str | Path,
        output_path: str | Path | None = None,
    ) -> ProcessingResult:
        """Run the configurable preprocessing pipeline for a handwritten answer image."""
        original = self.load_image(image_path)
        grayscale = self.to_grayscale(original)
        denoised = self.denoise(grayscale)
        enhanced = self.enhance_contrast(denoised)
        thresholded = self.threshold_image(enhanced)
        deskewed = self.deskew(thresholded)

        final = thresholded if self.config.thresholding else enhanced
        if self.config.deskew and self.config.thresholding:
            final = deskewed
        elif self.config.deskew and not self.config.thresholding:
            final = deskewed

        if output_path is not None:
            self.save_image(final, output_path)

        result = ProcessingResult(
            original=original,
            grayscale=grayscale,
            denoised=denoised,
            enhanced=enhanced,
            thresholded=thresholded,
            deskewed=deskewed,
            final=final,
            metadata={
                "input_path": str(Path(image_path)),
                "output_path": str(output_path) if output_path is not None else None,
                "threshold_method": self.config.threshold_method,
                "deskew_applied": self.config.deskew,
            },
        )

        return result
