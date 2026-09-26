from __future__ import annotations

import argparse
from pathlib import Path

from preprocessing import HandwrittenAnswerPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the EvaliSense handwritten-answer preprocessing pipeline.")
    parser.add_argument("--input", type=str, required=True, help="Path to the source handwritten answer image.")
    parser.add_argument(
        "--output",
        type=str,
        default="data/processed/processed_answer.png",
        help="Path where the final processed image should be saved.",
    )
    parser.add_argument(
        "--no-deskew",
        action="store_true",
        help="Disable deskewing for cases where the image is already aligned.",
    )
    args = parser.parse_args()

    pipeline = HandwrittenAnswerPipeline()
    if args.no_deskew:
        pipeline.preprocessor.config.deskew = False

    result = pipeline.process(args.input, args.output)
    print(f"Processed image saved to: {Path(args.output)}")
    print(f"Image shape: {result.final.shape}")
    print(f"Intermediate stages available: {list(result.__dict__.keys())}")


if __name__ == "__main__":
    main()
