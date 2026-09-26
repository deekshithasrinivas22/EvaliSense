from __future__ import annotations

from pathlib import Path

from .image_preprocessor import ImagePreprocessor, PreprocessingConfig, ProcessingResult


class HandwrittenAnswerPipeline:
    """Thin convenience wrapper around the preprocessing pipeline."""

    def __init__(self, config: PreprocessingConfig | None = None) -> None:
        self.preprocessor = ImagePreprocessor(config or PreprocessingConfig())

    def process(self, image_path: str | Path, output_path: str | Path | None = None) -> ProcessingResult:
        """Process a handwritten answer image and return intermediate stages."""
        return self.preprocessor.process(image_path, output_path)

    def save_processed(self, result: ProcessingResult, output_path: str | Path) -> Path:
        """Persist the final processed image."""
        return self.preprocessor.save_image(result.final, output_path)


__all__ = [
    "HandwrittenAnswerPipeline",
    "ImagePreprocessor",
    "PreprocessingConfig",
    "ProcessingResult",
]
