"""AI Evaluation Pipeline Service for EvaliSense.

Orchestrates the existing:
1. Image preprocessing (ImagePreprocessor)
2. Handwritten text recognition (HTRPipeline / TrOCR)
3. Rubric evaluation (AnswerEvaluator)
4. Feature extraction (extract_features)
5. Grading error risk prediction (GradingRiskModel)
6. Relational database persistence
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from api.database.models import (
    AIEvaluation,
    AnswerAnswer,
    AnswerScript,
    Exam,
    FinalMark,
    ScanIssue,
    User,
)
from api.services.notification_service import create_notification
from config import config
from utils.logging import get_logger

logger = get_logger(__name__)

# Singletons for models to avoid reloading weights repeatedly
_htr_pipeline = None
_evaluator = None
_risk_model = None


def get_htr_pipeline():
    global _htr_pipeline
    if _htr_pipeline is None:
        from htr import HTRPipeline
        _htr_pipeline = HTRPipeline()
    return _htr_pipeline


def get_evaluator():
    global _evaluator
    if _evaluator is None:
        from evaluation import AnswerEvaluator
        _evaluator = AnswerEvaluator(
            model_name=config.embedding_model_name,
            similarity_threshold=config.similarity_threshold,
        )
    return _evaluator


def get_risk_model():
    global _risk_model
    if _risk_model is None:
        if config.risk_model_path.exists():
            from models import GradingRiskModel
            _risk_model = GradingRiskModel.load(config.risk_model_path)
        else:
            logger.warning("Risk model file not found at %s. Using heuristic fallback.", config.risk_model_path)
    return _risk_model


def _heuristic_risk(features: dict[str, float]) -> dict[str, Any]:
    """Heuristic fallback for risk prediction."""
    factors: list[str] = []
    risk_score = 0.0

    ocr = features.get("ocr_confidence", 1.0)
    if ocr < 0.5:
        factors.append(f"OCR confidence is low ({ocr:.2f})")
        risk_score += 0.35

    eval_conf = features.get("evaluation_confidence", 1.0)
    if eval_conf < 0.5:
        factors.append(f"Evaluation confidence is low ({eval_conf:.2f})")
        risk_score += 0.25

    sim = features.get("overall_semantic_similarity", 1.0)
    if sim < 0.4:
        factors.append(f"Semantic similarity is uncertain ({sim:.2f})")
        risk_score += 0.2

    cov = features.get("rubric_coverage", 1.0)
    if cov < 0.5:
        factors.append(f"Rubric coverage is incomplete ({cov:.1%})")
        risk_score += 0.15

    dev = features.get("mark_deviation_from_mean_criterion", 0.0)
    if dev > 0.2:
        factors.append(f"Score deviates from criterion evidence ({dev:.2f})")
        risk_score += 0.1

    risk_score = min(1.0, risk_score)
    label = "HIGH" if risk_score > 0.4 else "LOW"

    if not factors:
        factors.append("No individual risk indicators identified")

    return {
        "risk_label": label,
        "risk_probability": round(risk_score, 4),
        "contributing_factors": factors,
    }


def process_script_evaluation(
    db: Session,
    script_id: int,
    triggering_user: User | None = None,
) -> dict[str, Any]:
    """Execute complete end-to-end evaluation for an answer script."""
    script = db.query(AnswerScript).filter(AnswerScript.id == script_id).first()
    if not script:
        raise ValueError(f"Script #{script_id} not found.")

    original_path = Path(script.original_path)
    if not original_path.exists():
        raise FileNotFoundError(f"Script image file missing at {original_path}")

    exam = db.query(Exam).filter(Exam.id == script.exam_id).first()
    if not exam:
        raise ValueError(f"Exam #{script.exam_id} not found.")

    if not exam.questions:
        raise ValueError(f"Exam '{exam.name}' has no questions configured.")

    script.status = "PROCESSING"
    db.commit()

    try:
        # Step 1: Preprocessing
        from preprocessing import ImagePreprocessor
        preprocessed_path = original_path.parent / f"proc_{original_path.name}"
        preprocessor = ImagePreprocessor()
        preprocessor.process(original_path, preprocessed_path)

        # Step 2: HTR Recognition
        pipeline = get_htr_pipeline()
        debug_dir = original_path.parent / "debug"
        htr_res = pipeline.recognize_path(preprocessed_path, debug_dir)

        full_text = htr_res.full_text or ""
        avg_conf = htr_res.average_confidence or 0.0

        # Quality check: Check if OCR failed or text is empty
        if not full_text.strip() or avg_conf < 0.25:
            issue_type = "BLANK_PAGE" if not full_text.strip() else "LOW_OCR_CONFIDENCE"
            issue_desc = (
                "No handwriting detected on page."
                if not full_text.strip()
                else f"Average OCR confidence too low ({avg_conf:.2f})."
            )

            issue = ScanIssue(
                script_id=script.id,
                reported_by=triggering_user.id if triggering_user else script.uploaded_by,
                issue_type=issue_type,
                description=issue_desc,
                severity="HIGH",
                status="OPEN",
            )
            db.add(issue)
            script.status = "REUPLOAD_REQUIRED"
            db.commit()

            create_notification(
                db=db,
                user_id=script.uploaded_by,
                type="RESCAN_REQUIRED",
                title=f"Scan Issue on Script #{script.id}",
                message=f"Recognition failed for '{script.original_filename}': {issue_desc}",
                reference_type="answer_script",
                reference_id=script.id,
            )
            return {"status": "reupload_required", "reason": issue_desc, "script_id": script.id}

        script.status = "OCR_COMPLETED"
        db.commit()

        # Step 3: Question-by-Question Evaluation
        from evaluation import Rubric
        from features import extract_features

        evaluator = get_evaluator()
        risk_model = get_risk_model()

        any_high_risk = False
        evaluated_answers = []

        for question in exam.questions:
            # Look up or create AnswerAnswer
            answer = db.query(AnswerAnswer).filter(
                AnswerAnswer.script_id == script.id,
                AnswerAnswer.question_id == question.id,
            ).first()

            if not answer:
                answer = AnswerAnswer(
                    script_id=script.id,
                    question_id=question.id,
                    image_path=str(original_path),
                    extracted_text=full_text,
                    ocr_confidence=avg_conf,
                    status="PROCESSING",
                )
                db.add(answer)
                db.flush()
            else:
                answer.extracted_text = full_text
                answer.ocr_confidence = avg_conf

            # Parse rubric
            rubric_dict = json.loads(question.rubric_json) if question.rubric_json else {
                "question": question.question_text,
                "max_marks": question.max_marks,
                "reference_answer": question.reference_answer or "",
                "criteria": [{"id": "c1", "description": "General correctness", "marks": question.max_marks, "keywords": []}],
            }
            rubric = Rubric.from_dict(rubric_dict)

            # Evaluate with Sentence-BERT
            eval_result = evaluator.evaluate(full_text, rubric)

            # Extract 16 features
            features_vec = extract_features(htr_res.to_dict(), eval_result.to_dict())

            # Predict risk
            if risk_model is not None:
                prediction = risk_model.predict(features_vec.values, features_vec.names)
                risk_label = prediction.risk_label
                risk_prob = float(prediction.risk_probability)
                factors = prediction.contributing_factors
                model_name = risk_model.model_name
            else:
                heuristic = _heuristic_risk(features_vec.to_dict())
                risk_label = heuristic["risk_label"]
                risk_prob = float(heuristic["risk_probability"])
                factors = heuristic["contributing_factors"]
                model_name = "HeuristicRisk"

            # Save AIEvaluation record
            ai_eval = db.query(AIEvaluation).filter(AIEvaluation.answer_id == answer.id).first()
            if not ai_eval:
                ai_eval = AIEvaluation(
                    answer_id=answer.id,
                    ai_mark=round(eval_result.total_score, 2),
                    max_marks=question.max_marks,
                    semantic_similarity=round(eval_result.overall_similarity, 4),
                    rubric_coverage=round(features_vec.to_dict().get("rubric_coverage", 0.0), 4),
                    evaluation_confidence=round(eval_result.confidence, 4),
                    risk_label=risk_label,
                    risk_probability=risk_prob,
                    risk_factors=json.dumps(factors),
                    model_name=model_name,
                    evaluated_at=datetime.utcnow(),
                )
                db.add(ai_eval)
            else:
                ai_eval.ai_mark = round(eval_result.total_score, 2)
                ai_eval.max_marks = question.max_marks
                ai_eval.semantic_similarity = round(eval_result.overall_similarity, 4)
                ai_eval.rubric_coverage = round(features_vec.to_dict().get("rubric_coverage", 0.0), 4)
                ai_eval.evaluation_confidence = round(eval_result.confidence, 4)
                ai_eval.risk_label = risk_label
                ai_eval.risk_probability = risk_prob
                ai_eval.risk_factors = json.dumps(factors)
                ai_eval.model_name = model_name
                ai_eval.evaluated_at = datetime.utcnow()

            if risk_label == "HIGH":
                answer.status = "HIGH_RISK"
                any_high_risk = True
            else:
                answer.status = "LOW_RISK"
                # For low-risk answers, auto-accept AI mark as final mark
                existing_final = db.query(FinalMark).filter(FinalMark.answer_id == answer.id).first()
                if not existing_final:
                    admin_user = db.query(User).filter(User.username == "admin").first()
                    teacher_id = admin_user.id if admin_user else script.uploaded_by
                    db.add(FinalMark(
                        answer_id=answer.id,
                        teacher_id=teacher_id,
                        final_mark=round(eval_result.total_score, 2),
                        teacher_notes="Auto-accepted low-risk AI evaluation.",
                        decision="AUTO_ACCEPTED",
                        reviewed_at=datetime.utcnow(),
                    ))

            evaluated_answers.append({
                "answer_id": answer.id,
                "question_number": question.question_number,
                "ai_mark": eval_result.total_score,
                "max_marks": question.max_marks,
                "risk_label": risk_label,
                "risk_probability": risk_prob,
            })

        # Update Script Status
        script.status = "RISK_REVIEW" if any_high_risk else "COMPLETED"
        script.processed_at = datetime.utcnow()
        db.commit()

        # Balance and assign any high-risk answers to eligible teachers
        if any_high_risk:
            from api.services.teacher_service import auto_assign_risky_answers
            assigned_count = auto_assign_risky_answers(db, exam_id=exam.id)
            logger.info("Automatically assigned %d high-risk answers for exam %s", assigned_count, exam.name)

        return {
            "status": "success",
            "script_id": script.id,
            "script_status": script.status,
            "answers": evaluated_answers,
            "extracted_text": full_text,
            "ocr_confidence": avg_conf,
        }

    except Exception as exc:
        db.rollback()
        script.status = "FAILED"
        db.commit()
        logger.error("AI evaluation pipeline failed for script #%d: %s", script_id, exc, exc_info=True)
        raise
