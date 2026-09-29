"""Download and prepare real datasets for EvaliSense.

Downloads:
  1. HuggingFace GCSE Handwriting OCR dataset (78 real exam answer images)
  2. Kaggle ASAP Short Answer Scoring dataset (if kaggle API configured)
  3. Generates synthetic training data

Usage:
    pip install datasets Pillow requests
    python download_datasets.py
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError


def _download_hf_dataset(dataset_id: str, label: str, output_dir: Path,
                          parent_dir: Path) -> int:
    """Download a single HuggingFace dataset, saving images and metadata."""
    hf_dir = output_dir / label
    hf_dir.mkdir(parents=True, exist_ok=True)

    try:
        from datasets import load_dataset

        print(f"  Loading {dataset_id}...")
        ds = load_dataset(dataset_id, trust_remote_code=True)

        total = 0
        metadata_records = []

        for split_name in ds:
            split = ds[split_name]
            print(f"    Split: {split_name} ({len(split)} samples)")

            split_dir = hf_dir / split_name
            split_dir.mkdir(parents=True, exist_ok=True)

            for i, sample in enumerate(split):
                # Try common column names for the image
                image = None
                for col in ("image", "image_path", "pixel_values"):
                    if col in sample and sample[col] is not None:
                        image = sample[col]
                        break

                # Try common column names for the text
                text = ""
                for col in ("text", "answer_text", "ground_truth", "label",
                             "transcription", "sentence"):
                    if col in sample and sample[col]:
                        text = str(sample[col])
                        break

                if image is None:
                    continue

                img_path = split_dir / f"sample_{i:04d}.png"
                saved = False
                if hasattr(image, "save"):
                    image.save(str(img_path))
                    saved = True
                elif isinstance(image, bytes):
                    try:
                        from PIL import Image as PILImage
                        img = PILImage.open(io.BytesIO(image))
                        img.save(str(img_path))
                        saved = True
                    except Exception:
                        pass
                elif isinstance(image, str) and os.path.exists(image):
                    shutil.copy2(image, str(img_path))
                    saved = True

                if saved and img_path.exists():
                    metadata_records.append({
                        "split": split_name,
                        "index": i,
                        "image_file": str(img_path.relative_to(parent_dir)),
                        "transcription": text,
                        "source": f"HuggingFace/{dataset_id}",
                        "dataset_type": "real_handwriting",
                    })
                    total += 1

        # Save metadata
        meta_path = hf_dir / "metadata.jsonl"
        with open(meta_path, "w", encoding="utf-8") as f:
            for rec in metadata_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        print(f"    ✓ Saved {total} images to {hf_dir.name}/")
        return total

    except Exception as exc:
        print(f"    ✗ Failed: {exc}")
        return 0


def download_huggingface_datasets(output_dir: Path) -> int:
    """Download handwriting datasets from HuggingFace.

    Tries multiple datasets in order of relevance. Uses non-gated
    (open access) datasets as primary sources.
    """
    print("\n" + "=" * 60)
    print("  Downloading HuggingFace Handwriting Datasets")
    print("=" * 60)

    try:
        from datasets import load_dataset  # noqa: F401
    except ImportError:
        print("  ✗ 'datasets' library not installed.")
        print("    Install with: pip install datasets")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    total = 0

    # List of datasets to try, in priority order.
    # Non-gated datasets are tried first.
    candidates = [
        ("Teklia/IAM-line", "iam_lines",
         "IAM Handwriting Lines — standard HTR benchmark, English handwritten paragraphs"),
        ("HumynLabs/Handwritten-Computer-Science-Notes-Dataset", "cs_notes",
         "Handwritten CS notes — diagrams, algorithms, code snippets"),
        ("JunaidMB/handwriting-ocr-images-dataset", "gcse_exams",
         "GCSE exam answers (gated — requires HF login)"),
    ]

    for dataset_id, label, description in candidates:
        print(f"\n  [{label}] {description}")
        count = _download_hf_dataset(dataset_id, label, output_dir, output_dir.parent)
        total += count
        if total >= 50:
            # We have enough images for demonstration
            break

    if total == 0:
        print("\n  ⚠️  No datasets could be downloaded.")
        print("  Check your internet connection and try again.")
        print("  Or set HF_TOKEN for gated datasets: https://huggingface.co/settings/tokens")

    return total


def download_asap_sas(output_dir: Path) -> int:
    """Download ASAP Short Answer Scoring dataset metadata.

    This dataset has typed student answers with grades (not handwritten),
    but useful for evaluation model training.
    """
    print("\n" + "=" * 60)
    print("  Preparing ASAP Short Answer Scoring Dataset Info")
    print("=" * 60)

    asap_dir = output_dir / "asap_sas"
    asap_dir.mkdir(parents=True, exist_ok=True)

    # Check if kaggle is configured
    try:
        import kaggle
        print("  Kaggle API found. Downloading dataset...")
        kaggle.api.dataset_download_files(
            "mubeenfurqanahmed/automatic-short-answer-grading-dataset",
            path=str(asap_dir),
            unzip=True,
        )
        # Count records
        csv_files = list(asap_dir.glob("*.csv"))
        total = 0
        for csv_file in csv_files:
            with open(csv_file, encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                total += sum(1 for _ in reader) - 1  # minus header
        print(f"  ✓ Downloaded {total} answer-scoring records")
        return total

    except (ImportError, Exception) as exc:
        print(f"  ⚠️  Kaggle API not available: {exc}")
        print()
        print("  To download Kaggle datasets manually:")
        print("  1. Go to: https://www.kaggle.com/datasets/mubeenfurqanahmed/automatic-short-answer-grading-dataset")
        print("  2. Download the CSV file")
        print(f"  3. Place it in: {asap_dir}")
        print()
        print("  Or install kaggle API:")
        print("  pip install kaggle")
        print("  Then place your kaggle.json in ~/.kaggle/")

        # Create a readme with instructions
        readme = asap_dir / "README.md"
        readme.write_text(
            "# ASAP Short Answer Scoring Dataset\n\n"
            "Download from: https://www.kaggle.com/datasets/mubeenfurqanahmed/automatic-short-answer-grading-dataset\n\n"
            "Contains 4000+ student answers with teacher marks.\n"
            "Place the CSV file(s) in this directory.\n",
            encoding="utf-8",
        )
        return 0


def download_iam_sample(output_dir: Path) -> int:
    """Download IAM handwriting dataset sample from Kaggle (top-50 subset)."""
    print("\n" + "=" * 60)
    print("  Preparing IAM Handwriting Dataset")
    print("=" * 60)

    iam_dir = output_dir / "iam_handwriting"
    iam_dir.mkdir(parents=True, exist_ok=True)

    try:
        import kaggle
        print("  Kaggle API found. Downloading IAM top-50 subset...")
        kaggle.api.dataset_download_files(
            "spscientist/iam-handwriting-top50",
            path=str(iam_dir),
            unzip=True,
        )
        images = list(iam_dir.rglob("*.png")) + list(iam_dir.rglob("*.jpg"))
        print(f"  ✓ Downloaded {len(images)} IAM handwriting images")
        return len(images)

    except (ImportError, Exception) as exc:
        print(f"  ⚠️  Kaggle API not available: {exc}")
        print()
        print("  To download IAM dataset:")
        print("  Option A (Kaggle): https://www.kaggle.com/datasets/spscientist/iam-handwriting-top50")
        print("  Option B (Official): https://fki.tic.heia-fr.ch/databases/download-the-iam-handwriting-database")
        print(f"  Place downloaded files in: {iam_dir}")

        readme = iam_dir / "README.md"
        readme.write_text(
            "# IAM Handwriting Dataset\n\n"
            "Download from:\n"
            "- Kaggle (subset): https://www.kaggle.com/datasets/spscientist/iam-handwriting-top50\n"
            "- Official (full): https://fki.tic.heia-fr.ch/databases/download-the-iam-handwriting-database\n\n"
            "Standard benchmark for handwritten text recognition.\n"
            "Place downloaded image files in this directory.\n",
            encoding="utf-8",
        )
        return 0


def generate_synthetic(output_dir: Path, count: int = 300) -> int:
    """Generate synthetic training dataset."""
    print("\n" + "=" * 60)
    print("  Generating Synthetic Training Dataset")
    print("=" * 60)

    output_file = output_dir / "synthetic_dataset.jsonl"

    # Import and run the generator
    sys.path.insert(0, str(Path(__file__).parent))
    from generate_synthetic_dataset import _generate_record

    import numpy as np
    rng = np.random.default_rng(42)

    records = [_generate_record(rng, error_threshold=2.0) for _ in range(count)]

    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    n_errors = sum(1 for r in records if r["is_grading_error"])
    print(f"  ✓ Generated {len(records)} synthetic records")
    print(f"    Grading errors: {n_errors} ({n_errors/len(records):.1%})")
    print(f"    Saved to: {output_file}")
    return len(records)


def create_test_images(output_dir: Path) -> int:
    """Create programmatic test images."""
    print("\n" + "=" * 60)
    print("  Creating Test Images")
    print("=" * 60)

    sys.path.insert(0, str(Path(__file__).parent))
    from create_test_images import create_test_images as _create
    results = _create(output_dir)
    print(f"  ✓ Created {len(results)} test images")
    return len(results)


def main():
    parser = argparse.ArgumentParser(description="Download and prepare datasets for EvaliSense")
    parser.add_argument("--data-dir", type=Path, default=Path("data"),
                        help="Base data directory")
    parser.add_argument("--skip-hf", action="store_true", help="Skip HuggingFace download")
    parser.add_argument("--skip-kaggle", action="store_true", help="Skip Kaggle downloads")
    parser.add_argument("--skip-synthetic", action="store_true", help="Skip synthetic generation")
    parser.add_argument("--skip-images", action="store_true", help="Skip test image creation")
    parser.add_argument("--synthetic-count", type=int, default=300, help="Number of synthetic records")
    args = parser.parse_args()

    print("=" * 60)
    print("  EvaliSense — Dataset Download & Preparation")
    print("=" * 60)
    print(f"  Data directory: {args.data_dir.resolve()}")

    totals = {}

    # 1. HuggingFace datasets (real handwritten text — non-gated first)
    if not args.skip_hf:
        totals["HuggingFace Handwriting"] = download_huggingface_datasets(
            args.data_dir / "external"
        )

    # 2. Kaggle datasets
    if not args.skip_kaggle:
        totals["ASAP Short Answer Scoring"] = download_asap_sas(args.data_dir / "external")
        totals["IAM Handwriting"] = download_iam_sample(args.data_dir / "external")

    # 3. Synthetic training data
    if not args.skip_synthetic:
        totals["Synthetic training data"] = generate_synthetic(
            args.data_dir / "samples", count=args.synthetic_count
        )

    # 4. Test images
    if not args.skip_images:
        totals["Test images"] = create_test_images(args.data_dir / "raw")

    # Summary
    print("\n" + "=" * 60)
    print("  Download Summary")
    print("=" * 60)
    for name, count in totals.items():
        status = "✓" if count > 0 else "⚠️ 0 (see instructions above)"
        print(f"  {name}: {count if count > 0 else status}")

    print()
    print("  Next steps:")
    print("  1. python run_demo.py --train-model")
    print("  2. uvicorn api.app:app --port 8000 --reload")
    print()


if __name__ == "__main__":
    main()
