"""Feature extraction for grading-error risk prediction.

Extracts a fixed-schema feature vector from the outputs of the HTR and
evaluation pipelines.  These features are used by the ML risk model to
predict whether an AI-generated evaluation is likely to contain a
meaningful grading error.

Feature names and extraction logic used during training **must** be
identical to those used during inference.  This module provides both
a feature-name list and an extraction function so that consistency is
guaranteed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from utils.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Feature schema
# ──────────────────────────────────────────────────────────────────────

FEATURE_NAMES: list[str] = [
    "ocr_confidence",
    "overall_semantic_similarity",
    "mean_criterion_similarity",
    "min_criterion_similarity",
    "max_criterion_similarity",
    "std_criterion_similarity",
    "rubric_coverage",
    "keyword_coverage",
    "answer_length_chars",
    "answer_length_tokens",
    "num_recognized_lines",
    "evaluation_confidence",
    "ai_preliminary_mark",
    "max_marks",
    "normalized_score",
    "mark_deviation_from_mean_criterion",
]


@dataclass
class FeatureVector:
    """Container for extracted features."""

    values: np.ndarray
    names: list[str] = field(default_factory=lambda: list(FEATURE_NAMES))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, float]:
        return {name: float(val) for name, val in zip(self.names, self.values)}


# ──────────────────────────────────────────────────────────────────────
# Extraction
# ──────────────────────────────────────────────────────────────────────

def extract_features(
    htr_result: dict[str, Any] | None,
    eval_result: dict[str, Any] | None,
) -> FeatureVector:
    """Build a feature vector from HTR and evaluation result dicts.

    Both arguments are plain dictionaries (e.g. from ``to_dict()``).
    Missing keys are handled gracefully with safe defaults.
    """
    # --- HTR features ---
    ocr_confidence = _safe_float(htr_result, "average_confidence", 0.0) if htr_result else 0.0
    num_lines = len(htr_result.get("lines", [])) if htr_result else 0
    full_text = (htr_result.get("full_text", "") or "") if htr_result else ""

    answer_length_chars = len(full_text)
    answer_length_tokens = len(full_text.split()) if full_text.strip() else 0

    # --- Evaluation features ---
    overall_sim = _safe_float(eval_result, "overall_similarity", 0.0) if eval_result else 0.0
    eval_confidence = _safe_float(eval_result, "confidence", 0.0) if eval_result else 0.0
    ai_mark = _safe_float(eval_result, "total_score", 0.0) if eval_result else 0.0
    max_marks = _safe_float(eval_result, "max_score", 1.0) if eval_result else 1.0

    criterion_scores = eval_result.get("criterion_scores", []) if eval_result else []

    criterion_sims = [
        _safe_float(cs, "semantic_similarity", 0.0)
        for cs in criterion_scores
    ]
    keyword_coverages = []
    for cs in criterion_scores:
        kw = cs.get("keyword_matches", [])
        # Keyword coverage is tricky without knowing total keywords;
        # use the evidence string parsing or default to similarity.
        keyword_coverages.append(len(kw))

    mean_crit_sim = float(np.mean(criterion_sims)) if criterion_sims else 0.0
    min_crit_sim = float(np.min(criterion_sims)) if criterion_sims else 0.0
    max_crit_sim = float(np.max(criterion_sims)) if criterion_sims else 0.0
    std_crit_sim = float(np.std(criterion_sims)) if criterion_sims else 0.0

    # Rubric coverage: fraction of criteria where awarded > 0
    criteria_awarded = [
        1.0 if _safe_float(cs, "awarded_marks", 0.0) > 0 else 0.0
        for cs in criterion_scores
    ]
    rubric_coverage = float(np.mean(criteria_awarded)) if criteria_awarded else 0.0
    keyword_coverage_total = sum(keyword_coverages)

    normalized_score = ai_mark / max_marks if max_marks > 0 else 0.0

    # Deviation between normalised score and mean criterion similarity
    mark_deviation = abs(normalized_score - mean_crit_sim)

    features = np.array([
        ocr_confidence,
        overall_sim,
        mean_crit_sim,
        min_crit_sim,
        max_crit_sim,
        std_crit_sim,
        rubric_coverage,
        keyword_coverage_total,
        answer_length_chars,
        answer_length_tokens,
        num_lines,
        eval_confidence,
        ai_mark,
        max_marks,
        normalized_score,
        mark_deviation,
    ], dtype=np.float64)

    logger.debug("Extracted %d features", len(features))

    return FeatureVector(
        values=features,
        names=list(FEATURE_NAMES),
        metadata={
            "num_criteria": len(criterion_scores),
            "answer_preview": full_text[:100] if full_text else "",
        },
    )


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _safe_float(d: dict[str, Any] | None, key: str, default: float = 0.0) -> float:
    """Safely extract a float value from a dict."""
    if d is None:
        return default
    val = d.get(key)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default
