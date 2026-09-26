"""Answer evaluation package for EvaliSense.

Provides rubric representation, semantic similarity, and criterion-level
answer scoring.
"""

from .evaluator import AnswerEvaluator, CriterionResult, EvaluationResult
from .rubric import Rubric, RubricCriterion
from .semantic import batch_similarity, cosine_similarity, semantic_similarity

__all__ = [
    "AnswerEvaluator",
    "CriterionResult",
    "EvaluationResult",
    "Rubric",
    "RubricCriterion",
    "batch_similarity",
    "cosine_similarity",
    "semantic_similarity",
]
