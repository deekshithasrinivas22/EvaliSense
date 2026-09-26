"""Tests for the evaluation module: rubric, semantic similarity, and evaluator."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest


# ──────────────────────────────────────────────────────────────────────
# Rubric tests
# ──────────────────────────────────────────────────────────────────────

from evaluation.rubric import Rubric, RubricCriterion


def _sample_rubric() -> Rubric:
    return Rubric(
        question="Explain photosynthesis",
        max_marks=10,
        reference_answer="Photosynthesis converts light energy into chemical energy.",
        criteria=[
            RubricCriterion(id="c1", description="Explains energy conversion", marks=5,
                            keywords=["light", "energy", "convert"]),
            RubricCriterion(id="c2", description="Mentions chlorophyll", marks=3,
                            keywords=["chlorophyll", "green"]),
            RubricCriterion(id="c3", description="Uses scientific terms", marks=2,
                            keywords=["photosynthesis"]),
        ],
    )


def test_rubric_validation_valid():
    rubric = _sample_rubric()
    warnings = rubric.validate()
    assert warnings == []


def test_rubric_validation_empty_question():
    rubric = _sample_rubric()
    rubric.question = ""
    warnings = rubric.validate()
    assert any("question" in w.lower() for w in warnings)


def test_rubric_validation_marks_mismatch():
    rubric = _sample_rubric()
    rubric.max_marks = 20  # doesn't match criteria sum of 10
    warnings = rubric.validate()
    assert any("mark" in w.lower() for w in warnings)


def test_rubric_serialisation_roundtrip():
    rubric = _sample_rubric()
    data = rubric.to_dict()
    restored = Rubric.from_dict(data)
    assert restored.question == rubric.question
    assert restored.max_marks == rubric.max_marks
    assert len(restored.criteria) == len(rubric.criteria)


def test_rubric_json_roundtrip(tmp_path: Path):
    rubric = _sample_rubric()
    path = tmp_path / "rubric.json"
    rubric.to_json(path)
    loaded = Rubric.from_json(path)
    assert loaded.question == rubric.question
    assert loaded.max_marks == rubric.max_marks


def test_rubric_from_json_missing_file():
    with pytest.raises(FileNotFoundError):
        Rubric.from_json("nonexistent.json")


def test_rubric_duplicate_ids():
    rubric = _sample_rubric()
    rubric.criteria.append(RubricCriterion(id="c1", description="Duplicate", marks=0))
    warnings = rubric.validate()
    assert any("duplicate" in w.lower() for w in warnings)


# ──────────────────────────────────────────────────────────────────────
# Evaluator tests (mock semantic similarity for speed)
# ──────────────────────────────────────────────────────────────────────

from unittest.mock import patch


def _mock_semantic_similarity(text_a: str, text_b: str, model_name: str = "") -> float:
    """Deterministic fake similarity for testing."""
    if not text_a.strip() or not text_b.strip():
        return 0.0
    # Simple overlap heuristic
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    overlap = len(words_a & words_b)
    return min(1.0, overlap / max(len(words_a), len(words_b)))


@patch("evaluation.evaluator.semantic_similarity", side_effect=_mock_semantic_similarity)
@patch("evaluation.evaluator.batch_similarity")
def test_evaluator_scores_nonempty_answer(mock_batch, mock_sim):
    from evaluation.evaluator import AnswerEvaluator

    rubric = _sample_rubric()
    evaluator = AnswerEvaluator()
    result = evaluator.evaluate(
        "Photosynthesis converts light energy into chemical energy using chlorophyll.",
        rubric,
    )
    assert result.total_score >= 0
    assert result.total_score <= rubric.max_marks
    assert result.max_score == rubric.max_marks
    assert len(result.criterion_scores) == len(rubric.criteria)
    assert result.explanation  # should have explanation lines


@patch("evaluation.evaluator.semantic_similarity", side_effect=_mock_semantic_similarity)
@patch("evaluation.evaluator.batch_similarity")
def test_evaluator_empty_answer(mock_batch, mock_sim):
    from evaluation.evaluator import AnswerEvaluator

    rubric = _sample_rubric()
    evaluator = AnswerEvaluator()
    result = evaluator.evaluate("", rubric)
    assert result.total_score == 0.0
    assert result.confidence == 1.0  # certain it's empty


@patch("evaluation.evaluator.semantic_similarity", side_effect=_mock_semantic_similarity)
@patch("evaluation.evaluator.batch_similarity")
def test_evaluator_criterion_keyword_matching(mock_batch, mock_sim):
    from evaluation.evaluator import AnswerEvaluator

    rubric = _sample_rubric()
    evaluator = AnswerEvaluator()
    result = evaluator.evaluate(
        "The light energy is converted using chlorophyll in photosynthesis.",
        rubric,
    )
    # Check that keyword matches are recorded
    for cs in result.criterion_scores:
        if cs.criterion_id == "c3":
            assert "photosynthesis" in cs.keyword_matches


@patch("evaluation.evaluator.semantic_similarity", side_effect=_mock_semantic_similarity)
@patch("evaluation.evaluator.batch_similarity")
def test_evaluator_result_serialisation(mock_batch, mock_sim):
    from evaluation.evaluator import AnswerEvaluator

    rubric = _sample_rubric()
    result = AnswerEvaluator().evaluate("Some answer about light energy.", rubric)
    data = result.to_dict()
    assert isinstance(data, dict)
    assert "total_score" in data
    assert "criterion_scores" in data
    assert isinstance(data["criterion_scores"], list)
