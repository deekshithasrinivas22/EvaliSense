"""Generate a synthetic ground-truth dataset for EvaliSense development.

╔══════════════════════════════════════════════════════════════════════╗
║  WARNING: This produces SYNTHETIC data for development and testing  ║
║  purposes ONLY.  It does NOT represent real-world performance.      ║
║  Never present synthetic results as real research data.             ║
╚══════════════════════════════════════════════════════════════════════╝

Usage:
    python generate_synthetic_dataset.py --output data/samples/synthetic_dataset.jsonl --count 200
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

import numpy as np

from features.extractor import FEATURE_NAMES


def _generate_record(rng: np.random.Generator, error_threshold: float) -> dict:
    """Create one synthetic evaluation record with plausible feature values."""

    max_marks = rng.choice([5, 10, 15, 20])
    ocr_confidence = float(np.clip(rng.normal(0.55, 0.18), 0.05, 0.99))

    # Simulate varying answer quality
    quality = float(rng.beta(2.5, 2.5))  # 0..1

    overall_sim = float(np.clip(quality + rng.normal(0, 0.1), 0, 1))
    n_criteria = rng.integers(3, 8)

    # Generate per-criterion similarities
    crit_sims = np.clip(
        rng.normal(quality, 0.15, size=n_criteria), 0, 1
    ).astype(float)

    mean_crit_sim = float(crit_sims.mean())
    min_crit_sim = float(crit_sims.min())
    max_crit_sim = float(crit_sims.max())
    std_crit_sim = float(crit_sims.std())

    rubric_coverage = float(np.mean(crit_sims > 0.3))
    keyword_coverage = float(rng.integers(0, n_criteria * 3))

    answer_length_chars = int(rng.integers(50, 800))
    answer_length_tokens = int(answer_length_chars / rng.uniform(4.0, 6.0))
    num_lines = int(rng.integers(2, 15))

    eval_confidence = float(np.clip(
        (overall_sim + mean_crit_sim + rubric_coverage) / 3.0 + rng.normal(0, 0.05),
        0, 1
    ))

    # AI mark is correlated with quality but noisy
    ai_mark = float(np.clip(
        quality * max_marks + rng.normal(0, max_marks * 0.1),
        0, max_marks
    ))
    ai_mark = round(ai_mark * 2) / 2  # round to 0.5

    normalized_score = ai_mark / max_marks if max_marks > 0 else 0
    mark_deviation = float(abs(normalized_score - mean_crit_sim))

    # Expert mark — sometimes agrees, sometimes disagrees
    expert_noise = rng.normal(0, max_marks * 0.12)
    expert_mark = float(np.clip(ai_mark + expert_noise, 0, max_marks))
    expert_mark = round(expert_mark * 2) / 2  # round to 0.5

    absolute_error = abs(ai_mark - expert_mark)
    is_grading_error = absolute_error >= error_threshold

    features = {
        "ocr_confidence": ocr_confidence,
        "overall_semantic_similarity": overall_sim,
        "mean_criterion_similarity": mean_crit_sim,
        "min_criterion_similarity": min_crit_sim,
        "max_criterion_similarity": max_crit_sim,
        "std_criterion_similarity": std_crit_sim,
        "rubric_coverage": rubric_coverage,
        "keyword_coverage": keyword_coverage,
        "answer_length_chars": answer_length_chars,
        "answer_length_tokens": answer_length_tokens,
        "num_recognized_lines": num_lines,
        "evaluation_confidence": eval_confidence,
        "ai_preliminary_mark": ai_mark,
        "max_marks": max_marks,
        "normalized_score": normalized_score,
        "mark_deviation_from_mean_criterion": mark_deviation,
    }

    return {
        "record_id": str(uuid.uuid4())[:8],
        "question": "Synthetic question (development data)",
        "student_answer": f"Synthetic answer — quality={quality:.2f}",
        "ai_mark": ai_mark,
        "expert_mark": expert_mark,
        "max_marks": max_marks,
        "absolute_error": round(absolute_error, 2),
        "is_grading_error": is_grading_error,
        "features": features,
        "metadata": {
            "source": "synthetic",
            "is_synthetic": True,
            "quality_factor": round(quality, 3),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic ground-truth dataset for EvaliSense (DEVELOPMENT ONLY)."
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/samples/synthetic_dataset.jsonl"),
        help="Output JSONL file path.",
    )
    parser.add_argument("--count", type=int, default=200, help="Number of records.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument(
        "--error-threshold", type=float, default=2.0,
        help="Absolute-error threshold for grading-error label.",
    )
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    records = [_generate_record(rng, args.error_threshold) for _ in range(args.count)]

    with open(args.output, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    n_errors = sum(1 for r in records if r["is_grading_error"])
    print(f"Generated {len(records)} synthetic records → {args.output}")
    print(f"  Grading errors: {n_errors} ({n_errors / len(records):.1%})")
    print(f"  Non-errors:     {len(records) - n_errors}")
    print(f"  Error threshold: {args.error_threshold}")
    print()
    print("⚠️  This is SYNTHETIC data for development/testing only.")
    print("   Do NOT present these results as real research data.")


if __name__ == "__main__":
    main()
