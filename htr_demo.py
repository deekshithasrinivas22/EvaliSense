from __future__ import annotations

import argparse
from pathlib import Path

from preprocessing import ImagePreprocessor
from htr import HTRPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the baseline line-level HTR pipeline.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--preprocess", action="store_true")
    parser.add_argument("--debug-lines", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("experiments/htr_baseline"))
    args = parser.parse_args()

    image_path = args.input
    if args.preprocess:
        processed_path = args.output / "input_processed.png"
        ImagePreprocessor().process(image_path, processed_path)
        image_path = processed_path
    debug_dir = args.output / "debug" if args.debug_lines else None
    result = HTRPipeline().recognize_path(image_path, debug_dir)
    HTRPipeline.save_result(result, args.output / "line_results.json")
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
    print(f"Device: {HTRPipeline().recognizer.device}")


if __name__ == "__main__":
    main()
