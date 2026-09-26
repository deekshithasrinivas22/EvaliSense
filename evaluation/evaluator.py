"""Answer evaluator for EvaliSense.

Combines rubric-based assessment with semantic similarity to produce a
structured, criterion-level evaluation of a student's recognised answer
text.

The evaluator does NOT replace the examiner.  It produces an *AI
preliminary mark* and criterion-level evidence that the examiner can
review, approve, or override.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from utils.logging import get_logger

from .rubric import Rubric, RubricCriterion
from .semantic import batch_similarity, semantic_similarity

logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Result data structures
# ──────────────────────────────────────────────────────────────────────

@dataclass
class CriterionResult:
    """Evaluation outcome for a single rubric criterion."""

    criterion_id: str
    criterion_description: str
    max_marks: float
    awarded_marks: float
    semantic_similarity: float
    keyword_matches: list[str] = field(default_factory=list)
    evidence: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvaluationResult:
    """Full evaluation result for one student answer."""

    question: str
    student_answer: str
    reference_answer: str
    criterion_scores: list[CriterionResult] = field(default_factory=list)
    total_score: float = 0.0
    max_score: float = 0.0
    overall_similarity: float = 0.0
    confidence: float = 0.0
    explanation: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "student_answer": self.student_answer,
            "reference_answer": self.reference_answer,
            "criterion_scores": [c.to_dict() for c in self.criterion_scores],
            "total_score": self.total_score,
            "max_score": self.max_score,
            "overall_similarity": self.overall_similarity,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "metadata": self.metadata,
        }


# ──────────────────────────────────────────────────────────────────────
# Evaluator
# ──────────────────────────────────────────────────────────────────────

class AnswerEvaluator:
    """Rubric-aware, semantically-informed answer evaluator.

    For each rubric criterion the evaluator:

    1.  Computes semantic similarity between the student answer and the
        criterion description (and optional keywords).
    2.  Performs simple keyword / concept matching.
    3.  Awards marks proportionally based on a weighted combination of
        semantic similarity and keyword coverage.
    4.  Generates a human-readable evidence string for each criterion.

    The evaluator does NOT claim to be a definitive grader.  All marks
    are *preliminary* and must be reviewed by a human examiner.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        similarity_threshold: float = 0.55,
        keyword_weight: float = 0.3,
        semantic_weight: float = 0.7,
    ) -> None:
        self.model_name = model_name
        self.similarity_threshold = similarity_threshold
        self.keyword_weight = keyword_weight
        self.semantic_weight = semantic_weight

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def evaluate(
        self,
        student_answer: str,
        rubric: Rubric,
    ) -> EvaluationResult:
        """Evaluate a student answer against a rubric."""
        logger.info("Evaluating answer against rubric: %s", rubric.question[:60])

        if not student_answer.strip():
            return self._empty_result(rubric, student_answer)

        # Validate rubric
        warnings = rubric.validate()
        if warnings:
            logger.warning("Rubric validation warnings: %s", warnings)

        # Overall similarity (answer vs reference)
        overall_sim = 0.0
        if rubric.reference_answer.strip():
            overall_sim = semantic_similarity(
                student_answer, rubric.reference_answer, self.model_name
            )

        # Criterion-level evaluation
        criterion_results: list[CriterionResult] = []
        for criterion in rubric.criteria:
            cr = self._evaluate_criterion(student_answer, criterion, rubric)
            criterion_results.append(cr)

        total_score = sum(cr.awarded_marks for cr in criterion_results)
        max_score = rubric.max_marks

        # Confidence: weighted average of criterion confidences
        if criterion_results:
            weights = [cr.max_marks for cr in criterion_results]
            total_weight = sum(weights)
            if total_weight > 0:
                confidence = sum(
                    cr.confidence * w for cr, w in zip(criterion_results, weights)
                ) / total_weight
            else:
                confidence = 0.0
        else:
            confidence = 0.0

        # Explanations
        explanation = self._build_explanation(
            criterion_results, total_score, max_score, overall_sim, confidence
        )

        result = EvaluationResult(
            question=rubric.question,
            student_answer=student_answer,
            reference_answer=rubric.reference_answer,
            criterion_scores=criterion_results,
            total_score=round(total_score, 2),
            max_score=max_score,
            overall_similarity=round(overall_sim, 4),
            confidence=round(confidence, 4),
            explanation=explanation,
            metadata={
                "model": self.model_name,
                "similarity_threshold": self.similarity_threshold,
                "keyword_weight": self.keyword_weight,
                "semantic_weight": self.semantic_weight,
            },
        )

        logger.info(
            "Evaluation complete: %.1f / %.1f (confidence %.2f)",
            total_score, max_score, confidence,
        )
        return result

    # ──────────────────────────────────────────────────────────────────
    # Criterion evaluation
    # ──────────────────────────────────────────────────────────────────

    def _evaluate_criterion(
        self,
        student_answer: str,
        criterion: RubricCriterion,
        rubric: Rubric,
    ) -> CriterionResult:
        """Score a single criterion."""
        answer_lower = student_answer.lower()

        # 1. Semantic similarity between answer and criterion description
        sem_sim = semantic_similarity(
            student_answer, criterion.description, self.model_name
        )

        # 2. Keyword matching
        matched_keywords: list[str] = []
        keyword_score = 0.0
        if criterion.keywords:
            for kw in criterion.keywords:
                # Match as whole word (case-insensitive)
                pattern = re.compile(r'\b' + re.escape(kw.lower()) + r'\b')
                if pattern.search(answer_lower):
                    matched_keywords.append(kw)
            keyword_score = len(matched_keywords) / len(criterion.keywords)

        # 3. Combined score
        if criterion.keywords:
            combined = (
                self.semantic_weight * sem_sim
                + self.keyword_weight * keyword_score
            )
        else:
            # No keywords defined — rely fully on semantic similarity
            combined = sem_sim

        # 4. Award marks proportionally
        awarded = round(combined * criterion.marks, 2)
        awarded = max(0.0, min(criterion.marks, awarded))

        # 5. Confidence heuristic
        # Higher when semantic similarity and keyword coverage agree
        if criterion.keywords and len(criterion.keywords) > 0:
            agreement = 1.0 - abs(sem_sim - keyword_score)
            confidence = (sem_sim + keyword_score + agreement) / 3.0
        else:
            confidence = sem_sim

        # 6. Evidence
        evidence_parts = [
            f"Semantic similarity: {sem_sim:.3f}",
        ]
        if criterion.keywords:
            evidence_parts.append(
                f"Keyword coverage: {len(matched_keywords)}/{len(criterion.keywords)} "
                f"({keyword_score:.1%})"
            )
            if matched_keywords:
                evidence_parts.append(f"Matched: {', '.join(matched_keywords)}")
        evidence_parts.append(f"Combined score: {combined:.3f}")

        return CriterionResult(
            criterion_id=criterion.id,
            criterion_description=criterion.description,
            max_marks=criterion.marks,
            awarded_marks=awarded,
            semantic_similarity=round(sem_sim, 4),
            keyword_matches=matched_keywords,
            evidence=" | ".join(evidence_parts),
            confidence=round(confidence, 4),
        )

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    def _empty_result(self, rubric: Rubric, student_answer: str) -> EvaluationResult:
        """Return a zero-score result for an empty answer."""
        criterion_scores = [
            CriterionResult(
                criterion_id=c.id,
                criterion_description=c.description,
                max_marks=c.marks,
                awarded_marks=0.0,
                semantic_similarity=0.0,
                evidence="Student answer is empty.",
                confidence=1.0,  # we are certain: no answer = 0 marks
            )
            for c in rubric.criteria
        ]
        return EvaluationResult(
            question=rubric.question,
            student_answer=student_answer,
            reference_answer=rubric.reference_answer,
            criterion_scores=criterion_scores,
            total_score=0.0,
            max_score=rubric.max_marks,
            overall_similarity=0.0,
            confidence=1.0,
            explanation=["Student answer is empty — awarded 0 marks."],
        )

    def _build_explanation(
        self,
        criteria: list[CriterionResult],
        total: float,
        maximum: float,
        overall_sim: float,
        confidence: float,
    ) -> list[str]:
        """Build human-readable explanation lines."""
        lines: list[str] = []
        lines.append(
            f"AI Preliminary Mark: {total:.1f} / {maximum:.1f}"
        )
        lines.append(f"Overall answer similarity: {overall_sim:.3f}")
        lines.append(f"Evaluation confidence: {confidence:.3f}")
        lines.append("")
        for cr in criteria:
            status = "✓" if cr.awarded_marks > 0 else "✗"
            lines.append(
                f"  {status} [{cr.criterion_id}] {cr.criterion_description}: "
                f"{cr.awarded_marks:.1f} / {cr.max_marks:.1f}"
            )
            if cr.keyword_matches:
                lines.append(f"    Keywords matched: {', '.join(cr.keyword_matches)}")
        return lines
