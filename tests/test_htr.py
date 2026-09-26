from __future__ import annotations

import cv2
import numpy as np
import pytest

from htr import HTRPipeline, HandwritingLineSegmenter, HTRResult, RecognizedLine


def two_line_image() -> np.ndarray:
    image = np.full((160, 360), 255, dtype=np.uint8)
    cv2.putText(image, "first line", (20, 55), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2)
    cv2.putText(image, "second line", (20, 125), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2)
    return image


def test_segmenter_returns_top_to_bottom_regions() -> None:
    regions = HandwritingLineSegmenter().segment(two_line_image())
    assert len(regions) >= 2
    assert [region.line_number for region in regions] == list(range(1, len(regions) + 1))
    assert all(regions[index].bounding_box[1] <= regions[index + 1].bounding_box[1] for index in range(len(regions) - 1))


def test_segmenter_rejects_invalid_images() -> None:
    with pytest.raises((TypeError, ValueError)):
        HandwritingLineSegmenter().segment(np.array([]))


def test_pipeline_reconstructs_page_text() -> None:
    class StubRecognizer:
        model_name = "stub"

        def recognize(self, image, line_number, bounding_box):
            return RecognizedLine(line_number, f"line {line_number}", 0.8, bounding_box)

    result = HTRPipeline(recognizer=StubRecognizer()).recognize_image(two_line_image())
    assert isinstance(result, HTRResult)
    assert result.full_text == "line 1\nline 2"
    assert result.average_confidence == 0.8
    assert result.metadata["number_of_lines"] == 2
