"""Rubric representation and parsing for EvaliSense.

A rubric is a structured marking scheme that describes the criteria an
examiner uses to score a student's answer.  This module defines the
data model and provides loading / validation helpers.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RubricCriterion:
    """A single assessable criterion within a rubric."""

    id: str
    description: str
    marks: float
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Rubric:
    """Structured marking scheme for one examination question."""

    question: str
    max_marks: float
    reference_answer: str = ""
    criteria: list[RubricCriterion] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """Return a list of validation warnings (empty = valid)."""
        warnings: list[str] = []
        if not self.question.strip():
            warnings.append("Rubric question is empty.")
        if self.max_marks <= 0:
            warnings.append("max_marks must be positive.")
        if not self.criteria:
            warnings.append("Rubric has no criteria.")
        criteria_sum = sum(c.marks for c in self.criteria)
        if abs(criteria_sum - self.max_marks) > 0.01:
            warnings.append(
                f"Sum of criterion marks ({criteria_sum}) "
                f"does not equal max_marks ({self.max_marks})."
            )
        ids = [c.id for c in self.criteria]
        if len(ids) != len(set(ids)):
            warnings.append("Duplicate criterion IDs found.")
        return warnings

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "max_marks": self.max_marks,
            "reference_answer": self.reference_answer,
            "criteria": [c.to_dict() for c in self.criteria],
            "metadata": self.metadata,
        }

    def to_json(self, path: str | Path | None = None, indent: int = 2) -> str:
        text = json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return text

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rubric":
        criteria = [
            RubricCriterion(**c) for c in data.get("criteria", [])
        ]
        return cls(
            question=data.get("question", ""),
            max_marks=float(data.get("max_marks", 0)),
            reference_answer=data.get("reference_answer", ""),
            criteria=criteria,
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "Rubric":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Rubric file not found: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls.from_dict(data)
