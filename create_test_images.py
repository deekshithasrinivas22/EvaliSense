"""Generate sample handwritten-style test images for EvaliSense development.

These are PROGRAMMATIC images using OpenCV text rendering — they simulate
handwritten answers for pipeline testing.  They are NOT real handwriting
and should NOT be used to evaluate HTR accuracy.

Usage:
    python create_test_images.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def _draw_lined_page(
    width: int = 2480,
    height: int = 3508,
    margin_left: int = 200,
    line_spacing: int = 80,
    line_color: tuple = (200, 200, 200),
) -> np.ndarray:
    """Create a blank lined-paper background."""
    page = np.full((height, width, 3), 255, dtype=np.uint8)
    # Horizontal ruled lines
    y = 300
    while y < height - 100:
        cv2.line(page, (margin_left - 50, y), (width - 100, y), line_color, 1)
        y += line_spacing
    # Left margin line
    cv2.line(page, (margin_left - 60, 50), (margin_left - 60, height - 50), (255, 180, 180), 2)
    return page


def _write_answer(
    page: np.ndarray,
    lines: list[str],
    start_y: int = 320,
    start_x: int = 210,
    line_spacing: int = 80,
    font_scale: float = 1.3,
    color: tuple = (20, 20, 60),
    thickness: int = 2,
) -> np.ndarray:
    """Write text lines on a page image, simulating student handwriting."""
    rng = np.random.default_rng(42)
    font_options = [
        cv2.FONT_HERSHEY_SIMPLEX,
        cv2.FONT_HERSHEY_DUPLEX,
        cv2.FONT_HERSHEY_COMPLEX,
    ]

    y = start_y
    for i, line in enumerate(lines):
        if not line.strip():
            y += line_spacing // 2
            continue

        # Slight randomness to simulate handwriting variation
        x_offset = int(rng.integers(-5, 10))
        y_offset = int(rng.integers(-3, 5))
        scale_var = font_scale + float(rng.normal(0, 0.05))
        font = font_options[i % len(font_options)]

        # Slightly vary the ink color
        c = tuple(int(max(0, min(255, v + rng.integers(-15, 15)))) for v in color)

        cv2.putText(
            page, line,
            (start_x + x_offset, y + y_offset),
            font, scale_var, c, thickness, cv2.LINE_AA,
        )
        y += line_spacing

    return page


def _add_noise(image: np.ndarray, rng: np.random.Generator, level: float = 5.0) -> np.ndarray:
    """Add slight Gaussian noise to simulate scan artifacts."""
    noise = rng.normal(0, level, image.shape).astype(np.float32)
    noisy = np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return noisy


# ──────────────────────────────────────────────────────────────────────
# Sample answers
# ──────────────────────────────────────────────────────────────────────

SAMPLE_ANSWERS = {
    "photosynthesis_good": {
        "filename": "answer_photosynthesis_good.png",
        "description": "Good answer about photosynthesis (expects ~7-8/10)",
        "lines": [
            "Photosynthesis is the process where",
            "plants convert light energy into",
            "chemical energy stored in glucose.",
            "This happens in the chloroplasts",
            "using a green pigment called",
            "chlorophyll to absorb sunlight.",
            "",
            "Water molecules are split during",
            "the light-dependent reactions,",
            "releasing oxygen as a byproduct.",
            "ATP and NADPH are produced.",
            "",
            "In the Calvin cycle, carbon",
            "dioxide is fixed into organic",
            "molecules. Photosynthesis is vital",
            "because it produces oxygen and",
            "forms the base of food chains.",
        ],
    },
    "photosynthesis_partial": {
        "filename": "answer_photosynthesis_partial.png",
        "description": "Partial answer about photosynthesis (expects ~4-5/10)",
        "lines": [
            "Photosynthesis is how plants",
            "make food from sunlight.",
            "Plants use their leaves to",
            "capture light and make glucose.",
            "",
            "It is important because",
            "it gives us oxygen to breathe",
            "and food to eat.",
        ],
    },
    "photosynthesis_poor": {
        "filename": "answer_photosynthesis_poor.png",
        "description": "Poor answer about photosynthesis (expects ~1-2/10)",
        "lines": [
            "Plants need water and sun.",
            "They grow in the ground.",
            "They are green.",
        ],
    },
    "cell_biology_good": {
        "filename": "answer_cell_biology_good.png",
        "description": "Good answer about cell biology (for cell biology rubric)",
        "lines": [
            "The cell is the basic unit of",
            "life. All living organisms are",
            "made up of cells.",
            "",
            "Plant cells have a cell wall,",
            "chloroplasts and a large vacuole.",
            "Animal cells have a cell membrane",
            "but no cell wall.",
            "",
            "The nucleus contains DNA and",
            "controls cell activities.",
            "Mitochondria produce energy",
            "through cellular respiration.",
            "",
            "The endoplasmic reticulum and",
            "Golgi apparatus are involved in",
            "protein synthesis and transport.",
        ],
    },
    "history_good": {
        "filename": "answer_history_good.png",
        "description": "Good answer about Industrial Revolution",
        "lines": [
            "The Industrial Revolution began",
            "in Britain in the late 1700s.",
            "It transformed manufacturing",
            "from hand production to machine",
            "manufacturing.",
            "",
            "Key inventions included the",
            "steam engine by James Watt,",
            "the spinning jenny, and the",
            "power loom.",
            "",
            "Urbanisation increased as people",
            "moved to cities for factory work.",
            "Working conditions were often",
            "harsh with long hours and low pay.",
            "",
            "The revolution led to economic",
            "growth but also social inequality.",
        ],
    },
    "empty_answer": {
        "filename": "answer_empty.png",
        "description": "Nearly empty answer (expects 0/10)",
        "lines": [
            "I dont know",
        ],
    },
}


def create_test_images(output_dir: Path) -> list[dict]:
    """Generate all sample test images and return metadata."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    results = []

    for key, sample in SAMPLE_ANSWERS.items():
        page = _draw_lined_page()
        page = _write_answer(page, sample["lines"])
        page = _add_noise(page, rng, level=3.0)

        path = output_dir / sample["filename"]
        cv2.imwrite(str(path), page)

        results.append({
            "key": key,
            "path": str(path),
            "filename": sample["filename"],
            "description": sample["description"],
            "num_lines": len([l for l in sample["lines"] if l.strip()]),
        })

        print(f"  Created: {path.name} — {sample['description']}")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Create sample test images for EvaliSense.")
    parser.add_argument("--output", type=Path, default=Path("data/raw"),
                        help="Output directory for test images.")
    args = parser.parse_args()

    print("Creating sample test images for EvaliSense...")
    print(f"Output directory: {args.output}")
    print()

    results = create_test_images(args.output)

    print(f"\n✓ Created {len(results)} test images")
    print()
    print("⚠️  These are PROGRAMMATIC images (OpenCV rendered text),")
    print("   NOT real handwriting.  They are for pipeline testing only.")
    print("   Do NOT use them to evaluate HTR accuracy.")
    print()
    print("For real handwriting testing, place scanned answer images in data/raw/")


if __name__ == "__main__":
    main()
