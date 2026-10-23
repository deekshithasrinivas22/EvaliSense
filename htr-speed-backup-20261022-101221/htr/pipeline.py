from __future__ import annotations

import json
import argparse
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .line_segmenter import HandwritingLineSegmenter
from .recognizer import HandwritingRecognizer
from .result import HTRResult


class HTRPipeline:
    def __init__(self, segmenter: HandwritingLineSegmenter | None = None, recognizer: Any | None = None) -> None:
        self.segmenter = segmenter or HandwritingLineSegmenter()
        self.recognizer = recognizer or HandwritingRecognizer()

    def recognize_image(self, image: np.ndarray, debug_dir: str | Path | None = None) -> HTRResult:
        regions = self.segmenter.segment(image)
        if debug_dir is not None:
            self._save_debug(image, regions, debug_dir)
        lines = [self.recognizer.recognize(region.image, region.line_number, region.bounding_box) for region in regions]
        confidences = [line.confidence for line in lines if line.confidence is not None]
        return HTRResult("\n".join(line.text for line in lines), lines, sum(confidences) / len(confidences) if confidences else None, {"model": getattr(self.recognizer, "model_name", None), "number_of_lines": len(lines)})

    def recognize_path(self, image_path: str | Path, debug_dir: str | Path | None = None) -> HTRResult:
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Could not read image data from: {image_path}")
        return self.recognize_image(image, debug_dir)

    def _save_debug(self, image: np.ndarray, regions: list[Any], debug_dir: str | Path) -> None:
        output = Path(debug_dir)
        output.mkdir(parents=True, exist_ok=True)
        overlay = image.copy()
        for region in regions:
            x, y, width, height = region.bounding_box
            cv2.rectangle(overlay, (x, y), (x + width, y + height), (0, 0, 255), 2)
            cv2.imwrite(str(output / f"line_{region.line_number:03d}.png"), region.image)
        cv2.imwrite(str(output / "detected_lines.png"), overlay)

    @staticmethod
    def save_result(result: HTRResult, output_path: str | Path) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the baseline line-level HTR pipeline.")
    parser.add_argument("--input", required=True, type=Path, help="Input page image.")
    parser.add_argument("--output", type=Path, default=Path("experiments/htr_baseline"), help="Output directory.")
    parser.add_argument("--debug-lines", action="store_true", help="Save line crops and a bounding-box overlay.")
    parser.add_argument("--preprocessed", action="store_true", help="Mark the input as already preprocessed.")
    parser.add_argument("--preprocess", action="store_true", help="Run the existing preprocessing stage before HTR.")
    args = parser.parse_args()

    image_path = args.input
    if args.preprocessed and args.preprocess:
        parser.error("--preprocessed and --preprocess cannot be used together")
    if args.preprocess:
        from preprocessing import ImagePreprocessor

        image_path = args.output / "input_processed.png"
        ImagePreprocessor().process(args.input, image_path)

    debug_dir = args.output / "debug" if args.debug_lines else None
    pipeline = HTRPipeline()
    result = pipeline.recognize_path(image_path, debug_dir)
    args.output.mkdir(parents=True, exist_ok=True)
    pipeline.save_result(result, args.output / "line_results.json")
    (args.output / "recognized_text.txt").write_text(result.full_text + "\n", encoding="utf-8")

    print(f"Detected lines: {len(result.lines)}")
    for line in result.lines:
        print(f'Line {line.line_number}: "{line.text}"')
        if line.confidence is not None:
            print(f"Confidence: {line.confidence:.3f}")
    print("\nFull extracted text:\n--------------------")
    print(result.full_text)
    if result.average_confidence is not None:
        print(f"\nAverage recognition confidence: {result.average_confidence:.3f}")
    print(f"Model: {result.metadata.get('model')}")
    print(f"Device: {pipeline.recognizer.device}")


if __name__ == "__main__":
    main()
