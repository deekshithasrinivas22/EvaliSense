from pathlib import Path

import cv2
import numpy as np
import pytest

from preprocessing import ImagePreprocessor, PreprocessingConfig, ProcessingResult


@pytest.fixture
def sample_image_path(tmp_path: Path) -> Path:
    image_path = tmp_path / "sample_answer.png"
    canvas = np.full((220, 320, 3), 255, dtype=np.uint8)
    cv2.putText(
        canvas,
        "Sample answer",
        (30, 110),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (30, 30, 30),
        2,
    )
    cv2.imwrite(str(image_path), canvas)
    return image_path


def test_valid_image_loading(sample_image_path: Path):
    preprocessor = ImagePreprocessor(PreprocessingConfig())
    image = preprocessor.load_image(sample_image_path)

    assert isinstance(image, np.ndarray)
    assert image.size > 0
    assert image.ndim in (2, 3)


def test_grayscale_conversion(sample_image_path: Path):
    preprocessor = ImagePreprocessor(PreprocessingConfig())
    color_image = preprocessor.load_image(sample_image_path)
    gray = preprocessor.to_grayscale(color_image)

    assert gray.ndim == 2
    assert gray.dtype == np.uint8
    assert gray.shape[0] > 0 and gray.shape[1] > 0


def test_process_valid_image(sample_image_path: Path):
    preprocessor = ImagePreprocessor(PreprocessingConfig())
    result = preprocessor.process(str(sample_image_path))

    assert isinstance(result, ProcessingResult)
    assert result.final is not None
    assert result.final.size > 0
    assert result.final.shape[0] > 0 and result.final.shape[1] > 0


def test_invalid_missing_image_raises():
    preprocessor = ImagePreprocessor(PreprocessingConfig())

    with pytest.raises((FileNotFoundError, ValueError)):
        preprocessor.process("missing_answer.png")


def test_output_image_valid(sample_image_path: Path):
    preprocessor = ImagePreprocessor(PreprocessingConfig())
    result = preprocessor.process(str(sample_image_path))

    assert result.final.dtype == np.uint8
    assert result.final.ndim in (2, 3)
    assert result.final.shape[0] > 0 and result.final.shape[1] > 0
