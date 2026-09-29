"""Run the complete EvaliSense evaluation pipeline demonstration.

This script exercises every stage of the pipeline using the sample data:

    1. Load sample answers and rubrics
    2. Run semantic evaluation for each answer
    3. Extract features
    4. Predict grading-error risk (if model exists)
    5. Simulate examiner review
    6. Save ground-truth records

Usage:
    python run_demo.py
    python run_demo.py --train-model   # also train a risk model from results

⚠️  Uses SYNTHETIC typed answers — not real handwritten text.
    Does NOT include HTR (that requires actual images + model download).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from config import config
from utils.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run EvaliSense full pipeline demo.")
    parser.add_argument("--train-model", action="store_true",
                        help="Also train a risk model from the generated ground-truth.")
    parser.add_argument("--output", type=Path, default=config.results_dir / "demo_results.jsonl",
                        help="Output JSONL file for ground-truth records.")
    args = parser.parse_args()

    print("=" * 60)
    print("  EvaliSense — Full Pipeline Demonstration")
    print("=" * 60)
    print()
    print("⚠️  This demo uses TYPED sample answers (not real HTR output).")
    print("   Results are for demonstration/testing purposes only.")
    print()

    # ── Load sample data ──
    samples_dir = config.samples_dir
    answers_path = samples_dir / "sample_answers.json"
    if not answers_path.exists():
        print(f"ERROR: Sample answers not found at {answers_path}")
        print("Run: python create_test_images.py  (or ensure data/samples/ exists)")
        sys.exit(1)

    answers_data = json.loads(answers_path.read_text(encoding="utf-8"))
    answers = answers_data["answers"]

    print(f"Loaded {len(answers)} sample answers")
    print()

    # ── Load evaluator ──
    print("Loading semantic evaluator...")
    try:
        from evaluation import AnswerEvaluator, Rubric
        evaluator = AnswerEvaluator(model_name=config.embedding_model_name)
    except Exception as exc:
        print(f"ERROR loading evaluator: {exc}")
        print("Install sentence-transformers: pip install sentence-transformers")
        sys.exit(1)

    from features import extract_features, FEATURE_NAMES
    from features.dataset import EvaluationRecord, GroundTruthDataset

    # ── Process each answer ──
    dataset = GroundTruthDataset(error_threshold=config.grading_error_threshold)
    all_results = []

    for i, sample in enumerate(answers):
        answer_id = sample["id"]
        answer_text = sample["answer_text"]
        rubric_file = sample["rubric_file"]
        quality = sample["quality"]
        expected_range = sample["expected_score_range"]
        sim_ocr_conf = sample["simulated_ocr_confidence"]

        print(f"─── [{i+1}/{len(answers)}] {answer_id} ({quality}) ───")

        # Load rubric
        rubric_path = samples_dir / rubric_file
        if not rubric_path.exists():
            print(f"  ⚠️  Rubric not found: {rubric_path}, skipping")
            continue

        rubric = Rubric.from_json(rubric_path)
        print(f"  Question: {rubric.question[:60]}...")
        print(f"  Max marks: {rubric.max_marks}")

        # Handle empty answer
        if not answer_text.strip():
            print(f"  Answer: (empty)")
        else:
            print(f"  Answer: {answer_text[:80]}...")

        # ── Step 1: Evaluate ──
        eval_result = evaluator.evaluate(answer_text, rubric)

        print(f"  AI Preliminary Mark: {eval_result.total_score:.1f} / {eval_result.max_score:.1f}")
        print(f"  Overall similarity: {eval_result.overall_similarity:.3f}")
        print(f"  Confidence: {eval_result.confidence:.3f}")

        for cs in eval_result.criterion_scores:
            status = "✓" if cs.awarded_marks > 0 else "✗"
            print(f"    {status} [{cs.criterion_id}] {cs.criterion_description[:50]}: "
                  f"{cs.awarded_marks:.1f}/{cs.max_marks:.1f} "
                  f"(sim={cs.semantic_similarity:.3f})")

        # ── Step 2: Extract features ──
        # Simulate HTR result
        simulated_htr = {
            "full_text": answer_text,
            "average_confidence": sim_ocr_conf,
            "lines": [{"line_number": j+1, "text": line, "confidence": sim_ocr_conf}
                      for j, line in enumerate(answer_text.split(". ")) if line.strip()],
        }

        feature_vec = extract_features(simulated_htr, eval_result.to_dict())
        print(f"  Features extracted: {len(feature_vec.values)} features")

        # ── Step 3: Risk prediction ──
        risk_model = None
        risk_label = "UNKNOWN"
        risk_prob = 0.0
        factors = []

        try:
            from models import GradingRiskModel
            if config.risk_model_path.exists():
                risk_model = GradingRiskModel.load(config.risk_model_path)
                prediction = risk_model.predict(feature_vec.values, feature_vec.names)
                risk_label = prediction.risk_label
                risk_prob = prediction.risk_probability
                factors = prediction.contributing_factors
            else:
                # Heuristic fallback
                feat_dict = feature_vec.to_dict()
                risk_score = 0.0
                if feat_dict.get("ocr_confidence", 1) < 0.5:
                    risk_score += 0.3
                    factors.append("Low OCR confidence")
                if feat_dict.get("evaluation_confidence", 1) < 0.5:
                    risk_score += 0.3
                    factors.append("Low evaluation confidence")
                if feat_dict.get("rubric_coverage", 1) < 0.5:
                    risk_score += 0.2
                    factors.append("Incomplete rubric coverage")
                risk_label = "HIGH" if risk_score > 0.4 else "LOW"
                risk_prob = min(1.0, risk_score)
                factors.append("(heuristic — no trained model)")
        except Exception as exc:
            factors = [f"Risk prediction failed: {exc}"]

        print(f"  Risk: {risk_label} ({risk_prob:.1%})")
        for f in factors:
            print(f"    • {f}")

        # ── Step 4: Simulate examiner review ──
        # Simulate an expert mark within expected range
        rng = np.random.default_rng(42 + i)
        if expected_range[0] == expected_range[1]:
            expert_mark = float(expected_range[0])
        else:
            expert_mark = float(rng.uniform(expected_range[0], expected_range[1]))
            expert_mark = round(expert_mark * 2) / 2  # round to 0.5

        ai_mark = eval_result.total_score
        absolute_error = abs(ai_mark - expert_mark)

        print(f"  Expert mark (simulated): {expert_mark:.1f}")
        print(f"  Absolute error: {absolute_error:.1f}")
        print(f"  Grading error: {'YES' if absolute_error >= config.grading_error_threshold else 'NO'} "
              f"(threshold={config.grading_error_threshold})")

        # ── Step 5: Store ground-truth record ──
        record = EvaluationRecord(
            record_id=answer_id,
            question=rubric.question,
            student_answer=answer_text[:200],
            ai_mark=ai_mark,
            expert_mark=expert_mark,
            max_marks=rubric.max_marks,
            features=feature_vec.to_dict(),
            metadata={
                "source": "demo_simulation",
                "is_synthetic": True,
                "quality": quality,
                "risk_label": risk_label,
                "risk_probability": risk_prob,
            },
        )
        dataset.add_record(record)
        all_results.append({
            "id": answer_id,
            "quality": quality,
            "ai_mark": ai_mark,
            "expert_mark": expert_mark,
            "max_marks": rubric.max_marks,
            "error": round(absolute_error, 2),
            "is_error": absolute_error >= config.grading_error_threshold,
            "risk_label": risk_label,
        })

        print()

    # ── Save results ──
    config.results_dir.mkdir(parents=True, exist_ok=True)
    dataset.save(args.output)
    print(f"✓ Saved {len(dataset.records)} ground-truth records to {args.output}")

    # ── Summary ──
    summary = dataset.summary()
    print()
    print("=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"  Total evaluations: {summary['total']}")
    print(f"  Grading errors:    {summary['errors']} ({summary['error_rate']:.1%})")
    print(f"  Mean abs. error:   {summary.get('mean_absolute_error', 0):.2f}")
    print(f"  Error threshold:   {summary['error_threshold']}")
    print()

    print("  Results table:")
    print(f"  {'ID':<20} {'Quality':<10} {'AI':>6} {'Expert':>8} {'Max':>5} {'Error':>7} {'Risk':<6}")
    print(f"  {'-'*20} {'-'*10} {'-'*6} {'-'*8} {'-'*5} {'-'*7} {'-'*6}")
    for r in all_results:
        flag = "⚠️" if r["is_error"] else "  "
        print(f"  {r['id']:<20} {r['quality']:<10} {r['ai_mark']:>6.1f} {r['expert_mark']:>8.1f} "
              f"{r['max_marks']:>5.0f} {r['error']:>7.2f} {r['risk_label']:<6} {flag}")

    # ── Optional: Train model ──
    if args.train_model:
        print()
        print("=" * 60)
        print("  Training Risk Model from Demo Results")
        print("=" * 60)

        # Also load the synthetic dataset if it exists
        synthetic_path = config.samples_dir / "synthetic_dataset.jsonl"
        combined = GroundTruthDataset(error_threshold=config.grading_error_threshold)

        # Add demo records
        for r in dataset.records:
            combined.add_record(r)

        # Add synthetic records if available
        if synthetic_path.exists():
            synth = GroundTruthDataset(path=synthetic_path,
                                       error_threshold=config.grading_error_threshold)
            for r in synth.records:
                combined.add_record(r)
            print(f"  Combined: {len(dataset.records)} demo + {len(synth.records)} synthetic "
                  f"= {len(combined.records)} total")
        else:
            print(f"  Using {len(combined.records)} demo records only.")
            print(f"  💡 Generate more data with: python generate_synthetic_dataset.py")

        X, y = combined.to_arrays()
        if len(np.unique(y)) < 2:
            print("  ⚠️  Only one class present — cannot train. Need more diverse data.")
        elif X.shape[0] < 10:
            print(f"  ⚠️  Only {X.shape[0]} samples — very small dataset.")
            print(f"  💡 Generate synthetic data first: python generate_synthetic_dataset.py")
        else:
            try:
                from models import GradingRiskModel
                model = GradingRiskModel()
                results = model.compare_models(X, y)

                print(f"\n  Best model: {model.model_name}")
                if model.metrics:
                    print(f"  Accuracy:  {model.metrics.accuracy:.3f}")
                    print(f"  Recall:    {model.metrics.recall:.3f}")
                    print(f"  F1-score:  {model.metrics.f1_score:.3f}")

                config.models_dir.mkdir(parents=True, exist_ok=True)
                model.save(config.risk_model_path)
                print(f"\n  ✓ Model saved to {config.risk_model_path}")
            except Exception as exc:
                print(f"  ERROR training model: {exc}")

    print()
    print("⚠️  All results are from SYNTHETIC/SIMULATED data.")
    print("   Do NOT present as real research performance.")


if __name__ == "__main__":
    main()
