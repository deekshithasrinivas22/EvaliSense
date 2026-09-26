"""Tests for the grading-error risk prediction model."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from features.extractor import FEATURE_NAMES


def _synthetic_data(n: int = 60, seed: int = 42):
    """Create synthetic feature matrix and labels for testing."""
    rng = np.random.default_rng(seed)
    X = rng.uniform(0, 1, size=(n, len(FEATURE_NAMES)))
    # Label: if normalised score (index 14) < 0.3 → error
    y = (X[:, 14] < 0.3).astype(int)
    # Ensure at least both classes exist
    y[0] = 0
    y[1] = 1
    return X, y


def test_risk_model_train_and_predict():
    from models.risk_model import GradingRiskModel

    X, y = _synthetic_data(60)
    model = GradingRiskModel()
    metrics = model.train(X, y, model_name="RandomForest")

    assert metrics.model_name == "RandomForest"
    assert 0 <= metrics.accuracy <= 1
    assert 0 <= metrics.precision <= 1
    assert 0 <= metrics.recall <= 1

    # Predict on a single sample
    prediction = model.predict(X[0])
    assert prediction.risk_label in ("HIGH", "LOW")
    assert 0 <= prediction.risk_probability <= 1
    assert isinstance(prediction.contributing_factors, list)


def test_risk_model_compare():
    from models.risk_model import GradingRiskModel

    X, y = _synthetic_data(80)
    model = GradingRiskModel()
    results = model.compare_models(X, y)

    assert len(results) > 0
    # Should be sorted by recall (descending)
    for i in range(len(results) - 1):
        assert results[i].recall >= results[i + 1].recall or (
            results[i].recall == results[i + 1].recall and
            results[i].f1_score >= results[i + 1].f1_score
        )


def test_risk_model_save_load(tmp_path: Path):
    from models.risk_model import GradingRiskModel

    X, y = _synthetic_data(60)
    model = GradingRiskModel()
    model.train(X, y, model_name="LogisticRegression")

    path = tmp_path / "test_model.joblib"
    model.save(path)
    assert path.exists()

    loaded = GradingRiskModel.load(path)
    pred = loaded.predict(X[0])
    assert pred.risk_label in ("HIGH", "LOW")


def test_risk_model_insufficient_data():
    from models.risk_model import GradingRiskModel

    X = np.random.rand(2, len(FEATURE_NAMES))
    y = np.array([0, 1])
    model = GradingRiskModel()

    with pytest.raises(ValueError, match="Insufficient"):
        model.train(X, y)


def test_risk_model_predict_without_training():
    from models.risk_model import GradingRiskModel

    model = GradingRiskModel()
    with pytest.raises(RuntimeError, match="not trained"):
        model.predict(np.zeros(len(FEATURE_NAMES)))


def test_risk_model_explainability():
    from models.risk_model import GradingRiskModel

    X, y = _synthetic_data(60)
    model = GradingRiskModel()
    model.train(X, y, model_name="RandomForest")

    # Create a low-confidence sample
    low_conf_sample = np.zeros(len(FEATURE_NAMES))  # all zeros = low everything
    pred = model.predict(low_conf_sample)

    # Should mention low OCR confidence or evaluation confidence
    assert any("low" in f.lower() or "incomplete" in f.lower() or "uncertain" in f.lower()
               for f in pred.contributing_factors)
