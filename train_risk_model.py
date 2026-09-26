"""Train and compare grading-error risk prediction models for EvaliSense.

Usage:
    python train_risk_model.py --dataset data/samples/synthetic_dataset.jsonl
    python train_risk_model.py --dataset data/samples/synthetic_dataset.jsonl --model RandomForest --compare
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from features.dataset import GroundTruthDataset
from models.risk_model import GradingRiskModel
from utils.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the EvaliSense grading-error risk model.")
    parser.add_argument("--dataset", type=Path, required=True, help="Path to JSONL dataset.")
    parser.add_argument("--model", type=str, default="RandomForest",
                        choices=["LogisticRegression", "RandomForest", "SVM", "GradientBoosting"],
                        help="Model to train (ignored when --compare is used).")
    parser.add_argument("--compare", action="store_true",
                        help="Compare all candidate models and select the best.")
    parser.add_argument("--output", type=Path, default=Path("trained_models/risk_model.joblib"),
                        help="Path to save the trained model.")
    parser.add_argument("--error-threshold", type=float, default=2.0,
                        help="Absolute-error threshold for grading-error labelling.")
    parser.add_argument("--test-size", type=float, default=0.25,
                        help="Fraction of data to hold out for testing.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    args = parser.parse_args()

    # Load dataset
    logger.info("Loading dataset from %s", args.dataset)
    dataset = GroundTruthDataset(path=args.dataset, error_threshold=args.error_threshold)

    summary = dataset.summary()
    print("\n=== Dataset Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print()

    if summary["total"] < 10:
        print("⚠️  Dataset is very small — results may not be meaningful.")
    if summary["errors"] == 0 or summary["non_errors"] == 0:
        print("⚠️  Dataset has only one class — model cannot be trained.")
        return

    X, y = dataset.to_arrays()
    logger.info("Feature matrix shape: %s, Label distribution: %s",
                X.shape, {0: int((y == 0).sum()), 1: int((y == 1).sum())})

    risk_model = GradingRiskModel()

    if args.compare:
        print("=== Model Comparison ===")
        results = risk_model.compare_models(X, y, test_size=args.test_size, random_state=args.seed)
        for metrics in results:
            print(f"\n--- {metrics.model_name} ---")
            print(f"  Accuracy:  {metrics.accuracy:.4f}")
            print(f"  Precision: {metrics.precision:.4f}")
            print(f"  Recall:    {metrics.recall:.4f}")
            print(f"  F1-score:  {metrics.f1_score:.4f}")
            print(f"  ROC-AUC:   {metrics.roc_auc:.4f}")
            print(f"  Confusion Matrix: {metrics.confusion_matrix}")
            if metrics.feature_importances:
                sorted_imp = sorted(metrics.feature_importances.items(),
                                    key=lambda x: x[1], reverse=True)[:5]
                print("  Top features:")
                for name, imp in sorted_imp:
                    print(f"    {name}: {imp:.4f}")
        print(f"\n✓ Best model selected: {risk_model.model_name}")
    else:
        print(f"=== Training {args.model} ===")
        metrics = risk_model.train(X, y, model_name=args.model,
                                   test_size=args.test_size, random_state=args.seed)
        print(f"  Accuracy:  {metrics.accuracy:.4f}")
        print(f"  Precision: {metrics.precision:.4f}")
        print(f"  Recall:    {metrics.recall:.4f}")
        print(f"  F1-score:  {metrics.f1_score:.4f}")
        print(f"  ROC-AUC:   {metrics.roc_auc:.4f}")
        print(f"  Confusion Matrix: {metrics.confusion_matrix}")
        print(f"\n{metrics.classification_report}")

    # Save
    risk_model.save(args.output)
    print(f"\n✓ Model saved to {args.output}")

    # Save metrics
    metrics_path = args.output.with_suffix(".metrics.json")
    metrics_data = risk_model.metrics.to_dict() if risk_model.metrics else {}
    metrics_path.write_text(json.dumps(metrics_data, indent=2), encoding="utf-8")
    print(f"✓ Metrics saved to {metrics_path}")


if __name__ == "__main__":
    main()
