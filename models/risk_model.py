"""Grading-error risk prediction model for EvaliSense.

This module trains and evaluates a SECONDARY supervised ML model whose
purpose is NOT to grade the student.  Its purpose is to predict:

    "Is the AI-generated evaluation likely to contain a meaningful
     grading error and therefore require human review?"

The module provides:

-   A model-comparison workflow (Logistic Regression, Random Forest,
    SVM, Gradient Boosting).
-   Training, evaluation, persistence, and inference.
-   Feature importance and explainability helpers.

Because the purpose is to identify unsafe AI evaluations, the module
pays particular attention to **recall** for high-risk cases.
"""
from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from utils.logging import get_logger

logger = get_logger(__name__)

# Lazy imports for sklearn so the module can be imported without it.
_SKLEARN_AVAILABLE: bool | None = None


def _check_sklearn() -> None:
    global _SKLEARN_AVAILABLE
    if _SKLEARN_AVAILABLE is None:
        try:
            import sklearn  # noqa: F401
            _SKLEARN_AVAILABLE = True
        except ImportError:
            _SKLEARN_AVAILABLE = False
    if not _SKLEARN_AVAILABLE:
        raise RuntimeError(
            "Risk model requires scikit-learn. "
            "Install it with: pip install scikit-learn"
        )


# ──────────────────────────────────────────────────────────────────────
# Result containers
# ──────────────────────────────────────────────────────────────────────

@dataclass
class ModelMetrics:
    """Evaluation metrics for a single model."""
    model_name: str
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    roc_auc: float = 0.0
    confusion_matrix: list[list[int]] = field(default_factory=list)
    classification_report: str = ""
    feature_importances: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RiskPrediction:
    """Prediction result from the risk model."""
    risk_label: str  # "HIGH" or "LOW"
    risk_probability: float
    contributing_factors: list[str] = field(default_factory=list)
    feature_values: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────
# Risk Model
# ──────────────────────────────────────────────────────────────────────

class GradingRiskModel:
    """Train, evaluate, and use the grading-error risk predictor."""

    def __init__(self, feature_names: list[str] | None = None) -> None:
        _check_sklearn()
        from features.extractor import FEATURE_NAMES
        self.feature_names = feature_names or list(FEATURE_NAMES)
        self.model: Any = None
        self.model_name: str = ""
        self.scaler: Any = None
        self.metrics: ModelMetrics | None = None
        self._is_fitted = False

    # ──────────────────────────────────────────────────────────────────
    # Model zoo
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_candidates() -> dict[str, Any]:
        """Return candidate models for comparison."""
        from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.svm import SVC

        return {
            "LogisticRegression": LogisticRegression(
                max_iter=1000, class_weight="balanced", random_state=42
            ),
            "RandomForest": RandomForestClassifier(
                n_estimators=100, class_weight="balanced", random_state=42
            ),
            "SVM": SVC(
                kernel="rbf", probability=True, class_weight="balanced", random_state=42
            ),
            "GradientBoosting": GradientBoostingClassifier(
                n_estimators=100, random_state=42
            ),
        }

    # ──────────────────────────────────────────────────────────────────
    # Training
    # ──────────────────────────────────────────────────────────────────

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        model_name: str = "RandomForest",
        test_size: float = 0.25,
        random_state: int = 42,
    ) -> ModelMetrics:
        """Train a single model and evaluate it."""
        _check_sklearn()
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import StandardScaler

        if X.shape[0] < 4:
            raise ValueError(
                f"Insufficient data for training: {X.shape[0]} samples. "
                "At least 4 are required for a train/test split."
            )

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=y
        )

        self.scaler = StandardScaler()
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        candidates = self._get_candidates()
        if model_name not in candidates:
            raise ValueError(f"Unknown model: {model_name}. Choose from: {list(candidates.keys())}")

        self.model = candidates[model_name]
        self.model_name = model_name

        logger.info("Training %s on %d samples", model_name, len(X_train))
        self.model.fit(X_train_scaled, y_train)
        self._is_fitted = True

        self.metrics = self._evaluate(X_test_scaled, y_test)
        logger.info(
            "%s — Accuracy: %.3f, F1: %.3f, Recall: %.3f, ROC-AUC: %.3f",
            model_name, self.metrics.accuracy, self.metrics.f1_score,
            self.metrics.recall, self.metrics.roc_auc,
        )
        return self.metrics

    def compare_models(
        self,
        X: np.ndarray,
        y: np.ndarray,
        test_size: float = 0.25,
        random_state: int = 42,
    ) -> list[ModelMetrics]:
        """Train and evaluate all candidate models, return sorted results."""
        _check_sklearn()
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import StandardScaler

        if X.shape[0] < 4:
            raise ValueError(f"Insufficient data: {X.shape[0]} samples.")

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=y
        )

        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        results: list[ModelMetrics] = []
        for name, model in self._get_candidates().items():
            logger.info("Training %s …", name)
            try:
                model.fit(X_train_scaled, y_train)
                # Temporarily set for evaluation
                old_model, old_name, old_scaler = self.model, self.model_name, self.scaler
                self.model, self.model_name, self.scaler = model, name, scaler
                self._is_fitted = True
                metrics = self._evaluate(X_test_scaled, y_test)
                results.append(metrics)
                self.model, self.model_name, self.scaler = old_model, old_name, old_scaler
            except Exception as exc:
                logger.warning("Failed to train %s: %s", name, exc)

        # Sort by recall (most important for risk detection), then F1
        results.sort(key=lambda m: (m.recall, m.f1_score), reverse=True)

        # Select the best model
        if results:
            best = results[0]
            logger.info("Best model by recall: %s (recall=%.3f, F1=%.3f)",
                        best.model_name, best.recall, best.f1_score)
            # Re-train best on the same split
            self.scaler = scaler
            best_model = self._get_candidates()[best.model_name]
            best_model.fit(X_train_scaled, y_train)
            self.model = best_model
            self.model_name = best.model_name
            self._is_fitted = True
            self.metrics = best

        return results

    # ──────────────────────────────────────────────────────────────────
    # Evaluation
    # ──────────────────────────────────────────────────────────────────

    def _evaluate(self, X_test: np.ndarray, y_test: np.ndarray) -> ModelMetrics:
        """Compute classification metrics."""
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            confusion_matrix,
            f1_score,
            precision_score,
            recall_score,
            roc_auc_score,
        )

        y_pred = self.model.predict(X_test)
        y_proba = None
        if hasattr(self.model, "predict_proba"):
            y_proba = self.model.predict_proba(X_test)

        roc = 0.0
        if y_proba is not None and len(np.unique(y_test)) > 1:
            try:
                roc = float(roc_auc_score(y_test, y_proba[:, 1]))
            except (ValueError, IndexError):
                roc = 0.0

        # Feature importances (where available)
        importances: dict[str, float] = {}
        if hasattr(self.model, "feature_importances_"):
            for name, imp in zip(self.feature_names, self.model.feature_importances_):
                importances[name] = float(imp)
        elif hasattr(self.model, "coef_"):
            coefs = self.model.coef_.flatten()
            for name, c in zip(self.feature_names, coefs):
                importances[name] = float(abs(c))

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            metrics = ModelMetrics(
                model_name=self.model_name,
                accuracy=float(accuracy_score(y_test, y_pred)),
                precision=float(precision_score(y_test, y_pred, zero_division=0)),
                recall=float(recall_score(y_test, y_pred, zero_division=0)),
                f1_score=float(f1_score(y_test, y_pred, zero_division=0)),
                roc_auc=roc,
                confusion_matrix=confusion_matrix(y_test, y_pred).tolist(),
                classification_report=classification_report(y_test, y_pred, zero_division=0),
                feature_importances=importances,
            )
        return metrics

    # ──────────────────────────────────────────────────────────────────
    # Prediction
    # ──────────────────────────────────────────────────────────────────

    def predict(self, features: np.ndarray, feature_names: list[str] | None = None) -> RiskPrediction:
        """Predict grading-error risk for a single sample."""
        if not self._is_fitted or self.model is None:
            raise RuntimeError("Model is not trained. Call train() first.")

        names = feature_names or self.feature_names
        X = features.reshape(1, -1)
        X_scaled = self.scaler.transform(X) if self.scaler else X

        label = int(self.model.predict(X_scaled)[0])
        risk_label = "HIGH" if label == 1 else "LOW"

        probability = 0.0
        if hasattr(self.model, "predict_proba"):
            proba = self.model.predict_proba(X_scaled)[0]
            probability = float(proba[1]) if len(proba) > 1 else float(proba[0])

        # Contributing factors
        factors = self._explain(features, names, probability)

        feature_dict = {n: float(v) for n, v in zip(names, features)}

        return RiskPrediction(
            risk_label=risk_label,
            risk_probability=round(probability, 4),
            contributing_factors=factors,
            feature_values=feature_dict,
        )

    def _explain(
        self, features: np.ndarray, names: list[str], probability: float
    ) -> list[str]:
        """Generate human-readable contributing factors."""
        factors: list[str] = []

        feature_dict = {n: float(v) for n, v in zip(names, features)}

        ocr_conf = feature_dict.get("ocr_confidence", 1.0)
        if ocr_conf < 0.5:
            factors.append(f"OCR confidence is low ({ocr_conf:.2f})")

        eval_conf = feature_dict.get("evaluation_confidence", 1.0)
        if eval_conf < 0.5:
            factors.append(f"Evaluation confidence is low ({eval_conf:.2f})")

        overall_sim = feature_dict.get("overall_semantic_similarity", 1.0)
        if overall_sim < 0.4:
            factors.append(f"Semantic similarity is uncertain ({overall_sim:.2f})")

        rubric_cov = feature_dict.get("rubric_coverage", 1.0)
        if rubric_cov < 0.5:
            factors.append(f"Rubric coverage is incomplete ({rubric_cov:.1%})")

        min_crit = feature_dict.get("min_criterion_similarity", 1.0)
        if min_crit < 0.3:
            factors.append(f"Minimum criterion similarity is very low ({min_crit:.2f})")

        std_crit = feature_dict.get("std_criterion_similarity", 0.0)
        if std_crit > 0.2:
            factors.append(f"High variability across criteria (std={std_crit:.2f})")

        mark_dev = feature_dict.get("mark_deviation_from_mean_criterion", 0.0)
        if mark_dev > 0.2:
            factors.append(f"Score deviates from criterion evidence (dev={mark_dev:.2f})")

        # Add feature importance if available
        if self.metrics and self.metrics.feature_importances:
            sorted_imp = sorted(
                self.metrics.feature_importances.items(),
                key=lambda x: x[1], reverse=True
            )[:3]
            top_features = [f"{n} (importance: {v:.3f})" for n, v in sorted_imp]
            factors.append(
                f"Top model features: {', '.join(top_features)}"
            )

        if not factors:
            if probability > 0.5:
                factors.append("Model predicts elevated risk based on combined features")
            else:
                factors.append("No individual risk indicators identified")

        return factors

    # ──────────────────────────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Save the trained model, scaler, and metadata."""
        import joblib

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        state = {
            "model": self.model,
            "scaler": self.scaler,
            "model_name": self.model_name,
            "feature_names": self.feature_names,
            "metrics": self.metrics.to_dict() if self.metrics else None,
        }
        joblib.dump(state, str(p))
        logger.info("Saved risk model to %s", p)

    @classmethod
    def load(cls, path: str | Path) -> "GradingRiskModel":
        """Load a trained model from disk."""
        _check_sklearn()
        import joblib

        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Model file not found: {p}")

        state = joblib.load(str(p))
        instance = cls(feature_names=state.get("feature_names"))
        instance.model = state["model"]
        instance.scaler = state.get("scaler")
        instance.model_name = state.get("model_name", "unknown")
        instance._is_fitted = True

        metrics_data = state.get("metrics")
        if metrics_data:
            instance.metrics = ModelMetrics(**metrics_data)

        logger.info("Loaded risk model from %s (%s)", p, instance.model_name)
        return instance
