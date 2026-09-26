"""Tests for feature extraction and ground-truth dataset management."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from features.extractor import FEATURE_NAMES, FeatureVector, extract_features
from features.dataset import EvaluationRecord, GroundTruthDataset


# ──────────────────────────────────────────────────────────────────────
# Feature extraction tests
# ──────────────────────────────────────────────────────────────────────

def _sample_htr_result() -> dict:
    return {
        "full_text": "This is a test answer about photosynthesis.",
        "average_confidence": 0.72,
        "lines": [
            {"line_number": 1, "text": "This is a test", "confidence": 0.8},
            {"line_number": 2, "text": "about photosynthesis", "confidence": 0.64},
        ],
    }


def _sample_eval_result() -> dict:
    return {
        "total_score": 7.0,
        "max_score": 10.0,
        "overall_similarity": 0.65,
        "confidence": 0.58,
        "criterion_scores": [
            {"criterion_id": "c1", "semantic_similarity": 0.7, "awarded_marks": 4, "keyword_matches": ["energy"]},
            {"criterion_id": "c2", "semantic_similarity": 0.5, "awarded_marks": 2, "keyword_matches": []},
            {"criterion_id": "c3", "semantic_similarity": 0.3, "awarded_marks": 1, "keyword_matches": ["photosynthesis"]},
        ],
    }


def test_extract_features_returns_correct_shape():
    vec = extract_features(_sample_htr_result(), _sample_eval_result())
    assert isinstance(vec, FeatureVector)
    assert len(vec.values) == len(FEATURE_NAMES)
    assert vec.names == FEATURE_NAMES


def test_extract_features_none_inputs():
    vec = extract_features(None, None)
    assert len(vec.values) == len(FEATURE_NAMES)
    assert np.all(np.isfinite(vec.values))


def test_extract_features_values_are_reasonable():
    vec = extract_features(_sample_htr_result(), _sample_eval_result())
    d = vec.to_dict()
    assert 0 <= d["ocr_confidence"] <= 1
    assert d["answer_length_chars"] > 0
    assert d["answer_length_tokens"] > 0
    assert d["num_recognized_lines"] == 2
    assert 0 <= d["normalized_score"] <= 1


# ──────────────────────────────────────────────────────────────────────
# Dataset tests
# ──────────────────────────────────────────────────────────────────────

def test_evaluation_record_calculates_error():
    record = EvaluationRecord(
        record_id="r1", question="Q", student_answer="A",
        ai_mark=7, expert_mark=5, max_marks=10,
    )
    assert record.absolute_error == 2.0


def test_dataset_labelling():
    dataset = GroundTruthDataset(error_threshold=2.0)
    r1 = EvaluationRecord("r1", "Q", "A", ai_mark=7, expert_mark=5, max_marks=10)
    r2 = EvaluationRecord("r2", "Q", "A", ai_mark=7, expert_mark=6, max_marks=10)
    dataset.add_record(r1)
    dataset.add_record(r2)

    assert r1.is_grading_error is True   # error = 2.0 >= threshold
    assert r2.is_grading_error is False  # error = 1.0 < threshold


def test_dataset_save_load(tmp_path: Path):
    path = tmp_path / "test_dataset.jsonl"
    dataset = GroundTruthDataset(error_threshold=2.0)

    for i in range(5):
        r = EvaluationRecord(f"r{i}", "Q", "A", ai_mark=i, expert_mark=i + 1, max_marks=10,
                             features={"ocr_confidence": 0.7, "evaluation_confidence": 0.6})
        dataset.add_record(r)

    dataset.save(path)
    assert path.exists()

    loaded = GroundTruthDataset(path=path, error_threshold=2.0)
    assert len(loaded.records) == 5


def test_dataset_to_arrays():
    dataset = GroundTruthDataset(error_threshold=2.0)
    features = {name: 0.5 for name in FEATURE_NAMES}

    for i in range(10):
        r = EvaluationRecord(f"r{i}", "Q", "A", ai_mark=5, expert_mark=5 + (i % 3),
                             max_marks=10, features=features)
        dataset.add_record(r)

    X, y = dataset.to_arrays()
    assert X.shape == (10, len(FEATURE_NAMES))
    assert y.shape == (10,)
    assert set(y).issubset({0, 1})


def test_dataset_summary():
    dataset = GroundTruthDataset(error_threshold=2.0)
    summary = dataset.summary()
    assert summary["total"] == 0
    assert summary["errors"] == 0
