"""
Download pre-trained assets and generated test data for EvaliSense.

This script is for collaborators who clone the repo and need:
  1. Test images (generated synthetically, ~66MB)
  2. External datasets (IAM, if available)
  3. HuggingFace model cache (TrOCR, Sentence-BERT)

Usage:
    python scripts/download_assets.py           # download everything
    python scripts/download_assets.py --models  # only HuggingFace models
    python scripts/download_assets.py --images  # only generate test images
    python scripts/download_assets.py --check   # just verify what's present
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_assets():
    """Check which assets are present."""
    from config import config

    print("=" * 60)
    print("  EVALISENSE — ASSET STATUS")
    print("=" * 60)

    # Risk model
    model_path = config.risk_model_path
    if model_path.exists():
        size_kb = model_path.stat().st_size / 1024
        print(f"  ✓ Risk model:         {model_path.name} ({size_kb:.0f} KB)")
    else:
        print(f"  ✗ Risk model:         MISSING (run Notebook 06 to train)")

    # Metrics
    metrics_path = model_path.with_suffix(".metrics.json")
    if metrics_path.exists():
        print(f"  ✓ Model metrics:      {metrics_path.name}")
    else:
        print(f"  ✗ Model metrics:      MISSING")

    # Synthetic dataset
    syn_path = config.samples_dir / "synthetic_dataset.jsonl"
    if syn_path.exists():
        count = sum(1 for _ in open(syn_path))
        print(f"  ✓ Synthetic dataset:  {count} records")
    else:
        print(f"  ✗ Synthetic dataset:  MISSING (run: python scripts/generate_synthetic_dataset.py)")

    # Rubrics
    rubrics = list(config.samples_dir.glob("rubric_*.json"))
    print(f"  {'✓' if rubrics else '✗'} Rubrics:             {len(rubrics)} found")

    # Test images
    test_imgs = list(config.raw_dir.glob("answer_*.png"))
    print(f"  {'✓' if test_imgs else '✗'} Test images:         {len(test_imgs)} found")

    # IAM dataset
    iam_dir = config.data_dir / "external" / "iam_lines"
    iam_meta = iam_dir / "metadata.jsonl"
    if iam_meta.exists():
        count = sum(1 for _ in open(iam_meta))
        print(f"  ✓ IAM dataset:        {count} lines")
    else:
        print(f"  ✗ IAM dataset:        NOT downloaded")

    # HuggingFace models
    print(f"\n  HuggingFace Models (cached on first use):")
    print(f"    HTR:  {config.htr_model_name}")
    print(f"    Eval: {config.embedding_model_name}")

    print("=" * 60)


def generate_test_images():
    """Generate synthetic test images using create_test_images.py."""
    script = PROJECT_ROOT / "scripts" / "create_test_images.py"
    if not script.exists():
        print("⚠ scripts/create_test_images.py not found. Skipping.")
        return

    print("\n→ Generating test images...")
    subprocess.run([sys.executable, str(script)], cwd=str(PROJECT_ROOT), check=True)
    print("✓ Test images generated.")


def generate_synthetic_data():
    """Generate synthetic training dataset."""
    from config import config

    syn_path = config.samples_dir / "synthetic_dataset.jsonl"
    if syn_path.exists():
        print("✓ Synthetic dataset already exists. Skipping.")
        return

    script = PROJECT_ROOT / "scripts" / "generate_synthetic_dataset.py"
    if not script.exists():
        print("⚠ scripts/generate_synthetic_dataset.py not found. Skipping.")
        return

    print("\n→ Generating synthetic dataset...")
    subprocess.run([sys.executable, str(script)], cwd=str(PROJECT_ROOT), check=True)
    print("✓ Synthetic dataset generated.")


def download_hf_models():
    """Pre-download HuggingFace models to local cache."""
    from config import config

    print(f"\n→ Downloading HTR model: {config.htr_model_name}")
    print("  (This may take a few minutes on first run...)")
    try:
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        TrOCRProcessor.from_pretrained(config.htr_model_name)
        VisionEncoderDecoderModel.from_pretrained(config.htr_model_name)
        print(f"  ✓ TrOCR cached successfully.")
    except Exception as e:
        print(f"  ⚠ TrOCR download failed: {e}")
        print(f"    It will be downloaded automatically on first notebook run.")

    print(f"\n→ Downloading evaluation model: {config.embedding_model_name}")
    try:
        from sentence_transformers import SentenceTransformer
        SentenceTransformer(config.embedding_model_name)
        print(f"  ✓ Sentence-BERT cached successfully.")
    except Exception as e:
        print(f"  ⚠ Sentence-BERT download failed: {e}")
        print(f"    It will be downloaded automatically on first notebook run.")


def main():
    parser = argparse.ArgumentParser(description="Download EvaliSense assets")
    parser.add_argument("--check", action="store_true", help="Only check asset status")
    parser.add_argument("--models", action="store_true", help="Download HuggingFace models only")
    parser.add_argument("--images", action="store_true", help="Generate test images only")
    parser.add_argument("--data", action="store_true", help="Generate synthetic dataset only")
    args = parser.parse_args()

    print("\n🔬 EvaliSense — Asset Downloader\n")

    if args.check:
        check_assets()
        return

    # If specific flags given, only do those
    if args.models or args.images or args.data:
        if args.models:
            download_hf_models()
        if args.images:
            generate_test_images()
        if args.data:
            generate_synthetic_data()
        print("\n✓ Done.")
        check_assets()
        return

    # Default: do everything
    print("Running full asset setup...\n")

    # 1. Generate test images
    generate_test_images()

    # 2. Generate synthetic data (if not already committed)
    generate_synthetic_data()

    # 3. Download HuggingFace models
    download_hf_models()

    print("\n" + "=" * 60)
    print("  ✓ ALL ASSETS READY")
    print("=" * 60)

    check_assets()


if __name__ == "__main__":
    main()
