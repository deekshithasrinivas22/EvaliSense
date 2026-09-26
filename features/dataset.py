"""Ground-truth dataset management for EvaliSense.

A dataset record pairs an AI evaluation with the expert's final mark
so that the grading-error risk model can be trained.

The dataset is stored as a single JSON-lines file where each line is
an independent record.  This avoids loading entire files into memory
and makes appending new records trivial.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from utils.logging import get_logger
from .extractor import FEATURE_NAMES, FeatureVector, extract_features

logger = get_logger(__name__)


@dataclass
class EvaluationRecord:
    """One labelled evaluation for the ground-truth dataset."""

    record_id: str
    question: str
    student_answer: str
    ai_mark: float
    expert_mark: float
    max_marks: float
    absolute_error: float = 0.0
    is_grading_error: bool = False
    features: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.absolute_error = abs(self.ai_mark - self.expert_mark)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class GroundTruthDataset:
    """Manages loading, appending, and splitting the ground-truth dataset."""

    def __init__(
        self,
        path: str | Path | None = None,
        error_threshold: float = 2.0,
    ) -> None:
        self.path = Path(path) if path else None
        self.error_threshold = error_threshold
        self.records: list[EvaluationRecord] = []
        if self.path and self.path.exists():
            self._load()

    # ──────────────────────────────────────────────────────────────────
    # I/O
    # ──────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load records from the JSONL file."""
        if self.path is None or not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                record = EvaluationRecord.from_dict(data)
                record.is_grading_error = record.absolute_error >= self.error_threshold
                self.records.append(record)
        logger.info("Loaded %d records from %s", len(self.records), self.path)

    def save(self, path: str | Path | None = None) -> Path:
        """Persist all records to a JSONL file."""
        out = Path(path) if path else self.path
        if out is None:
            raise ValueError("No output path specified.")
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            for record in self.records:
                fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        logger.info("Saved %d records to %s", len(self.records), out)
        return out

    def add_record(self, record: EvaluationRecord) -> None:
        """Append a record (label it with the error threshold)."""
        record.is_grading_error = record.absolute_error >= self.error_threshold
        self.records.append(record)

    # ──────────────────────────────────────────────────────────────────
    # ML helpers
    # ──────────────────────────────────────────────────────────────────

    def to_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        """Return (X, y) numpy arrays for model training.

        X shape: (n_samples, n_features)
        y shape: (n_samples,) with 1 = grading error, 0 = no error
        """
        if not self.records:
            return np.empty((0, len(FEATURE_NAMES))), np.empty((0,))

        X_rows: list[np.ndarray] = []
        y: list[int] = []

        for record in self.records:
            if record.features:
                row = np.array(
                    [record.features.get(name, 0.0) for name in FEATURE_NAMES],
                    dtype=np.float64,
                )
            else:
                row = np.zeros(len(FEATURE_NAMES), dtype=np.float64)
            X_rows.append(row)
            y.append(1 if record.is_grading_error else 0)

        return np.array(X_rows), np.array(y)

    def summary(self) -> dict[str, Any]:
        """Return dataset statistics."""
        n = len(self.records)
        if n == 0:
            return {"total": 0, "errors": 0, "non_errors": 0, "error_rate": 0.0}
        errors = sum(1 for r in self.records if r.is_grading_error)
        return {
            "total": n,
            "errors": errors,
            "non_errors": n - errors,
            "error_rate": errors / n,
            "error_threshold": self.error_threshold,
            "mean_absolute_error": float(np.mean([r.absolute_error for r in self.records])),
        }
