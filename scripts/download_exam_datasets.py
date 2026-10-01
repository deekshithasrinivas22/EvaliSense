"""Download proper exam paper and answer sheet datasets for EvaliSense.

Datasets downloaded:
  1. Handwritten ASAP-SAS (Zenodo) — Real handwritten exam answers with scores (~98 MB)
  2. JorGPT Student Answers (Kaggle/Zenodo) — 3,041 student answers with human grades
  3. SMHD Messy Handwriting (DOI) — Realistic messy student exam handwriting
  4. IAM Handwriting Lines (HuggingFace) — Standard HTR benchmark

Usage:
    python download_exam_datasets.py
    python download_exam_datasets.py --dataset asap       # Download only ASAP handwritten
    python download_exam_datasets.py --dataset jorgpt     # Download only JorGPT
    python download_exam_datasets.py --dataset all        # Download everything
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from pathlib import Path
from urllib.request import urlopen, urlretrieve, Request
from urllib.error import URLError, HTTPError


DATASETS_DIR = Path("data/external")


def _progress_hook(block_num, block_size, total_size):
    """Print download progress."""
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 // total_size)
        mb = downloaded / (1024 * 1024)
        total_mb = total_size / (1024 * 1024)
        print(f"\r    Downloading: {mb:.1f}/{total_mb:.1f} MB ({pct}%)", end="", flush=True)
    else:
        mb = downloaded / (1024 * 1024)
        print(f"\r    Downloading: {mb:.1f} MB", end="", flush=True)


# ──────────────────────────────────────────────────────────────────────
# 1. Handwritten ASAP-SAS (Zenodo)
# ──────────────────────────────────────────────────────────────────────

def download_asap_handwritten(output_dir: Path) -> int:
    """Download Handwritten ASAP Short Answer Scoring from Zenodo.

    Real handwritten student answers rewritten from the Hewlett Foundation
    ASAP-SAS competition. Contains scanned images + original scores.
    ~98 MB ZIP file.

    Source: https://zenodo.org/records/3929424
    Paper: Gold & Zesch (2020)
    """
    print("\n" + "=" * 60)
    print("  1. Handwritten ASAP-SAS (Zenodo)")
    print("     Real handwritten exam answers with teacher scores")
    print("=" * 60)

    asap_dir = output_dir / "asap_handwritten"
    asap_dir.mkdir(parents=True, exist_ok=True)

    zip_url = "https://zenodo.org/records/3929424/files/Handwritten-ASAP-SAS-V1.0.zip?download=1"
    zip_path = asap_dir / "Handwritten-ASAP-SAS-V1.0.zip"

    if (asap_dir / "Handwritten-ASAP-SAS-V1.0").exists():
        existing = list((asap_dir / "Handwritten-ASAP-SAS-V1.0").rglob("*.png"))
        existing += list((asap_dir / "Handwritten-ASAP-SAS-V1.0").rglob("*.jpg"))
        if existing:
            print(f"  ✓ Already downloaded ({len(existing)} images found)")
            return len(existing)

    try:
        print(f"  Source: zenodo.org/records/3929424")
        print(f"  Size: ~98 MB")
        print()
        urlretrieve(zip_url, str(zip_path), reporthook=_progress_hook)
        print()  # newline after progress

        # Extract
        print("    Extracting ZIP...")
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            zf.extractall(str(asap_dir))

        # Count extracted images
        images = list(asap_dir.rglob("*.png")) + list(asap_dir.rglob("*.jpg"))
        print(f"  ✓ Downloaded and extracted {len(images)} handwritten answer images")

        # Clean up ZIP
        zip_path.unlink(missing_ok=True)

        # Create metadata
        _create_asap_metadata(asap_dir)

        return len(images)

    except (URLError, HTTPError) as exc:
        print(f"  ✗ Download failed: {exc}")
        print("  Manual download: https://zenodo.org/records/3929424")
        print(f"  Place the ZIP in: {asap_dir}")
        return 0
    except zipfile.BadZipFile:
        print("  ✗ Downloaded file is not a valid ZIP")
        zip_path.unlink(missing_ok=True)
        return 0
    except Exception as exc:
        print(f"  ✗ Error: {exc}")
        return 0


def _create_asap_metadata(asap_dir: Path) -> None:
    """Create metadata JSONL for the ASAP handwritten dataset."""
    meta_path = asap_dir / "metadata.jsonl"
    records = []

    for img_path in sorted(asap_dir.rglob("*.png")):
        records.append({
            "image_file": str(img_path.relative_to(asap_dir)),
            "source": "Zenodo/3929424/Handwritten-ASAP-SAS",
            "dataset_type": "real_handwritten_exam_answers",
            "description": "Student handwritten answer from ASAP-SAS rewrite study",
        })

    for img_path in sorted(asap_dir.rglob("*.jpg")):
        records.append({
            "image_file": str(img_path.relative_to(asap_dir)),
            "source": "Zenodo/3929424/Handwritten-ASAP-SAS",
            "dataset_type": "real_handwritten_exam_answers",
        })

    with open(meta_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"  ✓ Metadata: {meta_path} ({len(records)} records)")


# ──────────────────────────────────────────────────────────────────────
# 2. JorGPT Student Answers with Human Grades
# ──────────────────────────────────────────────────────────────────────

def download_jorgpt(output_dir: Path) -> int:
    """Download JorGPT student answers with human grades from Zenodo.

    3,041 real student responses with instructor grades and LLM evaluations.
    CSV format, English + Spanish.

    Source: https://zenodo.org/records/15106505
    """
    print("\n" + "=" * 60)
    print("  2. JorGPT Student Answers & Grades (Zenodo)")
    print("     3,041 real student answers with human grades")
    print("=" * 60)

    jorgpt_dir = output_dir / "jorgpt_grading"
    jorgpt_dir.mkdir(parents=True, exist_ok=True)

    # Check if already downloaded
    csv_files = list(jorgpt_dir.glob("*.csv"))
    if csv_files:
        print(f"  ✓ Already downloaded ({len(csv_files)} CSV files)")
        return len(csv_files)

    # Try Zenodo API to find the download link
    api_url = "https://zenodo.org/api/records/15106505"
    try:
        req = Request(api_url, headers={"User-Agent": "EvaliSense/0.1"})
        resp = urlopen(req, timeout=30)
        record = json.loads(resp.read().decode())

        files = record.get("files", [])
        total_downloaded = 0

        for file_info in files:
            filename = file_info.get("key", "")
            download_url = file_info.get("links", {}).get("self", "")

            if not download_url:
                continue

            # Download each file
            dest = jorgpt_dir / filename
            print(f"    Downloading: {filename}")
            urlretrieve(download_url, str(dest), reporthook=_progress_hook)
            print()
            total_downloaded += 1

            # If ZIP, extract
            if filename.endswith(".zip"):
                try:
                    with zipfile.ZipFile(str(dest), "r") as zf:
                        zf.extractall(str(jorgpt_dir))
                    dest.unlink(missing_ok=True)
                    print(f"    Extracted: {filename}")
                except zipfile.BadZipFile:
                    print(f"    ⚠️ Not a valid ZIP: {filename}")

        # Count CSV files
        csv_count = len(list(jorgpt_dir.rglob("*.csv")))
        print(f"  ✓ Downloaded {total_downloaded} files ({csv_count} CSVs)")
        return csv_count or total_downloaded

    except Exception as exc:
        print(f"  ✗ Zenodo API failed: {exc}")
        print()
        print("  Manual download options:")
        print("  • Zenodo: https://zenodo.org/records/15106505")
        print("  • Kaggle: https://www.kaggle.com/datasets/javiersanchezsoriano/jorgpt-student-answers-and-multi-llm-grading")
        print(f"  Place CSV files in: {jorgpt_dir}")

        readme = jorgpt_dir / "README.md"
        readme.write_text(
            "# JorGPT Student Answers & Multi-LLM Grading Dataset\n\n"
            "3,041 real student answers with human grades and LLM evaluations.\n\n"
            "Download from:\n"
            "- Zenodo: https://zenodo.org/records/15106505\n"
            "- Kaggle: https://www.kaggle.com/datasets/javiersanchezsoriano/"
            "jorgpt-student-answers-and-multi-llm-grading\n\n"
            "Place CSV files in this directory.\n",
            encoding="utf-8",
        )
        return 0


# ──────────────────────────────────────────────────────────────────────
# 3. Kaggle Auto Short Answer Grading (4000+ records)
# ──────────────────────────────────────────────────────────────────────

def download_kaggle_asag(output_dir: Path) -> int:
    """Download Automatic Short Answer Grading dataset from Kaggle.

    4,000+ records: questions, student answers, model answers, teacher marks.

    Source: https://www.kaggle.com/datasets/mubeenfurqanahmed/automatic-short-answer-grading-dataset
    """
    print("\n" + "=" * 60)
    print("  3. Kaggle Short Answer Grading (4,000+ records)")
    print("     Questions, answers, model answers, teacher marks")
    print("=" * 60)

    asag_dir = output_dir / "kaggle_asag"
    asag_dir.mkdir(parents=True, exist_ok=True)

    csv_files = list(asag_dir.glob("*.csv"))
    if csv_files:
        print(f"  ✓ Already downloaded ({len(csv_files)} CSV files)")
        return len(csv_files)

    try:
        import kaggle
        print("  Kaggle API found. Downloading...")
        kaggle.api.dataset_download_files(
            "mubeenfurqanahmed/automatic-short-answer-grading-dataset",
            path=str(asag_dir),
            unzip=True,
        )
        csv_count = len(list(asag_dir.glob("*.csv")))
        print(f"  ✓ Downloaded ({csv_count} CSV files)")
        return csv_count

    except ImportError:
        print("  ⚠️ Kaggle API not installed (pip install kaggle)")
    except Exception as exc:
        print(f"  ⚠️ Kaggle download failed: {exc}")

    print()
    print("  Manual download:")
    print("  1. Go to: https://www.kaggle.com/datasets/mubeenfurqanahmed/automatic-short-answer-grading-dataset")
    print("  2. Click 'Download' (you need a free Kaggle account)")
    print(f"  3. Extract CSV(s) to: {asag_dir}")

    readme = asag_dir / "README.md"
    readme.write_text(
        "# Automatic Short Answer Grading Dataset\n\n"
        "4,000+ student answers with teacher marks.\n\n"
        "Download: https://www.kaggle.com/datasets/mubeenfurqanahmed/"
        "automatic-short-answer-grading-dataset\n\n"
        "Place CSV file(s) in this directory.\n",
        encoding="utf-8",
    )
    return 0


# ──────────────────────────────────────────────────────────────────────
# 4. IAM Lines from HuggingFace (already working)
# ──────────────────────────────────────────────────────────────────────

def download_iam_lines(output_dir: Path) -> int:
    """Download IAM handwriting lines from HuggingFace if not already present."""
    print("\n" + "=" * 60)
    print("  4. IAM Handwriting Lines (HuggingFace)")
    print("     Standard HTR benchmark — English paragraphs")
    print("=" * 60)

    iam_dir = output_dir / "iam_lines"
    existing = list(iam_dir.rglob("*.png")) if iam_dir.exists() else []
    if len(existing) >= 10:
        print(f"  ✓ Already downloaded ({len(existing)} images)")
        return len(existing)

    try:
        from datasets import load_dataset

        print("  Loading from HuggingFace Hub...")
        ds = load_dataset("Teklia/IAM-line", trust_remote_code=True)

        iam_dir.mkdir(parents=True, exist_ok=True)
        total = 0
        metadata_records = []

        for split_name in ds:
            split = ds[split_name]
            split_dir = iam_dir / split_name
            split_dir.mkdir(parents=True, exist_ok=True)

            # Limit to 100 per split to save disk/time
            limit = min(len(split), 100)
            print(f"    Split: {split_name} — saving {limit}/{len(split)} samples")

            for i in range(limit):
                sample = split[i]
                image = None
                for col in ("image", "pixel_values"):
                    if col in sample and sample[col] is not None:
                        image = sample[col]
                        break

                text = ""
                for col in ("text", "ground_truth", "transcription", "sentence"):
                    if col in sample and sample[col]:
                        text = str(sample[col])
                        break

                if image is None:
                    continue

                img_path = split_dir / f"iam_{i:04d}.png"
                if hasattr(image, "save"):
                    image.save(str(img_path))
                    metadata_records.append({
                        "image_file": str(img_path.relative_to(output_dir)),
                        "transcription": text,
                        "source": "HuggingFace/Teklia/IAM-line",
                        "split": split_name,
                        "dataset_type": "real_handwriting",
                    })
                    total += 1

        meta_path = iam_dir / "metadata.jsonl"
        with open(meta_path, "w", encoding="utf-8") as f:
            for rec in metadata_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        print(f"  ✓ Saved {total} IAM handwriting line images")
        return total

    except ImportError:
        print("  ✗ 'datasets' library required: pip install datasets")
        return 0
    except Exception as exc:
        print(f"  ✗ Failed: {exc}")
        return 0


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Download proper exam paper and answer sheet datasets for EvaliSense"
    )
    parser.add_argument(
        "--dataset", type=str, default="all",
        choices=["all", "asap", "jorgpt", "kaggle", "iam"],
        help="Which dataset(s) to download.",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=DATASETS_DIR,
        help="Base output directory for external datasets.",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  EvaliSense — Exam Paper Dataset Downloader")
    print("=" * 60)
    print(f"  Output: {args.data_dir.resolve()}")

    totals = {}

    if args.dataset in ("all", "asap"):
        totals["ASAP Handwritten (Zenodo)"] = download_asap_handwritten(args.data_dir)

    if args.dataset in ("all", "jorgpt"):
        totals["JorGPT Student Grades (Zenodo)"] = download_jorgpt(args.data_dir)

    if args.dataset in ("all", "kaggle"):
        totals["Kaggle Short Answer Grading"] = download_kaggle_asag(args.data_dir)

    if args.dataset in ("all", "iam"):
        totals["IAM Handwriting Lines (HF)"] = download_iam_lines(args.data_dir)

    # Summary
    print("\n" + "=" * 60)
    print("  Download Summary")
    print("=" * 60)
    for name, count in totals.items():
        status = f"✓ {count}" if count > 0 else "✗ 0 — see manual instructions above"
        print(f"  {name}: {status}")

    total = sum(totals.values())
    print(f"\n  Total files downloaded: {total}")

    if total > 0:
        print("\n  Dataset locations:")
        print(f"    {args.data_dir.resolve()}/")
        for name in totals:
            key = name.split("(")[0].strip().lower().replace(" ", "_")
            print(f"      └── {key}/")

    print("\n  Next steps:")
    print("  python run_demo.py --train-model")
    print("  uvicorn api.app:app --port 8000 --reload")
    print()


if __name__ == "__main__":
    main()
