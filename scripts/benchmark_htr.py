"""Benchmark the HTR pipeline on real IAM handwriting images.

Runs TrOCR on a subset of IAM line images, compares with ground-truth
transcriptions, and reports Character Error Rate (CER) and Word Error Rate (WER).

Usage:
    python benchmark_htr.py --count 20          # Quick test (20 images)
    python benchmark_htr.py --count 100         # Larger benchmark
    python benchmark_htr.py --count 20 --no-htr # Skip actual TrOCR (test evaluation only)
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Compute CER using Levenshtein distance."""
    ref = reference.strip()
    hyp = hypothesis.strip()
    if not ref:
        return 0.0 if not hyp else 1.0

    d = np.zeros((len(ref) + 1, len(hyp) + 1), dtype=int)
    for i in range(len(ref) + 1):
        d[i, 0] = i
    for j in range(len(hyp) + 1):
        d[0, j] = j

    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + cost)

    return d[len(ref), len(hyp)] / len(ref)


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Compute WER using Levenshtein distance on word sequences."""
    ref_words = reference.strip().split()
    hyp_words = hypothesis.strip().split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0

    d = np.zeros((len(ref_words) + 1, len(hyp_words) + 1), dtype=int)
    for i in range(len(ref_words) + 1):
        d[i, 0] = i
    for j in range(len(hyp_words) + 1):
        d[0, j] = j

    for i in range(1, len(ref_words) + 1):
        for j in range(1, len(hyp_words) + 1):
            cost = 0 if ref_words[i - 1] == hyp_words[j - 1] else 1
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + cost)

    return d[len(ref_words), len(hyp_words)] / len(ref_words)


def load_iam_metadata(metadata_path: Path, count: int, split: str = "test") -> list[dict]:
    """Load IAM metadata records for the specified split."""
    records = []
    with open(metadata_path, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line.strip())
            if rec.get("split") == split and rec.get("transcription", "").strip():
                records.append(rec)
                if len(records) >= count:
                    break

    # If not enough from the requested split, try train
    if len(records) < count and split != "train":
        with open(metadata_path, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line.strip())
                if rec.get("split") == "train" and rec.get("transcription", "").strip():
                    records.append(rec)
                    if len(records) >= count:
                        break

    return records[:count]


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark HTR pipeline on IAM images")
    parser.add_argument("--count", type=int, default=20, help="Number of images to test")
    parser.add_argument("--metadata", type=Path,
                        default=Path("data/external/iam_lines/metadata.jsonl"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("data/results/htr_benchmark.json"))
    parser.add_argument("--split", type=str, default="test", choices=["train", "test", "validation"])
    parser.add_argument("--no-htr", action="store_true", help="Skip actual HTR (dry run)")
    parser.add_argument("--preprocess", action="store_true", help="Run preprocessing first")
    args = parser.parse_args()

    print("=" * 60)
    print("  EvaliSense — HTR Benchmark on IAM Dataset")
    print("=" * 60)

    if not args.metadata.exists():
        print(f"  ✗ Metadata not found: {args.metadata}")
        print("  Run: python download_exam_datasets.py --dataset iam")
        return

    records = load_iam_metadata(args.metadata, args.count, args.split)
    print(f"  Loaded {len(records)} IAM line images")
    print()

    if args.no_htr:
        print("  --no-htr specified, skipping actual TrOCR inference")
        print("  Showing dataset sample instead:")
        for i, rec in enumerate(records[:10]):
            print(f"    [{i}] {rec['image_file']}")
            print(f"        Ground truth: \"{rec['transcription']}\"")
        return

    # Load HTR pipeline
    print("  Loading TrOCR model (first run downloads ~330MB)...")
    from htr import HTRPipeline
    pipeline = HTRPipeline()
    print(f"  Model loaded, device: {pipeline.recognizer.device}")
    print()

    # Optionally load preprocessor
    preprocessor = None
    if args.preprocess:
        from preprocessing import ImagePreprocessor
        preprocessor = ImagePreprocessor()
        print("  Preprocessing enabled")

    results = []
    total_cer = 0.0
    total_wer = 0.0

    for i, rec in enumerate(records):
        image_path = args.data_root / rec["image_file"]
        if not image_path.exists():
            print(f"  [{i+1}/{len(records)}] ✗ Image not found: {image_path}")
            continue

        ground_truth = rec["transcription"]

        # Read image
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            print(f"  [{i+1}/{len(records)}] ✗ Could not read: {image_path}")
            continue

        # Optionally preprocess
        if preprocessor is not None:
            try:
                result = preprocessor.process(str(image_path))
                image = result.final
            except Exception:
                pass  # Use original if preprocessing fails

        # Run HTR on the single line image (no segmentation needed — IAM is pre-segmented)
        t0 = time.time()
        try:
            recognized = pipeline.recognizer.recognize(image, line_number=1)
            elapsed = time.time() - t0
        except Exception as exc:
            print(f"  [{i+1}/{len(records)}] ✗ HTR error: {exc}")
            continue

        predicted = recognized.text
        confidence = recognized.confidence or 0.0
        cer = character_error_rate(ground_truth, predicted)
        wer = word_error_rate(ground_truth, predicted)
        total_cer += cer
        total_wer += wer

        match = "✓" if cer < 0.1 else "~" if cer < 0.3 else "✗"
        print(f"  [{i+1}/{len(records)}] {match} CER={cer:.3f} WER={wer:.3f} conf={confidence:.3f} ({elapsed:.2f}s)")
        print(f"    GT:  \"{ground_truth}\"")
        print(f"    HTR: \"{predicted}\"")

        results.append({
            "index": i,
            "image_file": rec["image_file"],
            "ground_truth": ground_truth,
            "predicted": predicted,
            "confidence": confidence,
            "cer": round(cer, 4),
            "wer": round(wer, 4),
            "elapsed_seconds": round(elapsed, 3),
        })

    if not results:
        print("\n  No results — check that images exist in the expected paths.")
        return

    # Summary
    n = len(results)
    avg_cer = total_cer / n
    avg_wer = total_wer / n
    avg_conf = sum(r["confidence"] for r in results) / n
    avg_time = sum(r["elapsed_seconds"] for r in results) / n
    exact_matches = sum(1 for r in results if r["cer"] == 0)
    good_matches = sum(1 for r in results if r["cer"] < 0.1)

    summary = {
        "total_images": n,
        "average_cer": round(avg_cer, 4),
        "average_wer": round(avg_wer, 4),
        "average_confidence": round(avg_conf, 4),
        "average_time_seconds": round(avg_time, 3),
        "exact_matches": exact_matches,
        "good_matches_cer_lt_10pct": good_matches,
        "accuracy_at_10pct_cer": round(good_matches / n, 4),
        "dataset": "IAM Handwriting Lines",
        "model": "microsoft/trocr-base-handwritten",
        "device": pipeline.recognizer.device,
    }

    print()
    print("=" * 60)
    print("  Benchmark Results")
    print("=" * 60)
    print(f"  Images tested:    {n}")
    print(f"  Average CER:      {avg_cer:.4f} ({avg_cer:.1%})")
    print(f"  Average WER:      {avg_wer:.4f} ({avg_wer:.1%})")
    print(f"  Average conf:     {avg_conf:.4f}")
    print(f"  Avg time/image:   {avg_time:.3f}s")
    print(f"  Exact matches:    {exact_matches}/{n} ({exact_matches/n:.1%})")
    print(f"  Good (<10% CER):  {good_matches}/{n} ({good_matches/n:.1%})")
    print(f"  Model:            microsoft/trocr-base-handwritten")
    print(f"  Device:           {pipeline.recognizer.device}")

    # Save results
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_data = {"summary": summary, "results": results}
    args.output.write_text(json.dumps(output_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  ✓ Results saved to {args.output}")


if __name__ == "__main__":
    main()
