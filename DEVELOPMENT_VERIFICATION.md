# EvaliSense development verification

Date: 2026-10-30

Base: `master` at `d25587c8ffabc32b21370a55ed93de2416af4813`.
Development branch: `development/ocr-exam-rubrics`.
The available saved cloud environment was not runnable. Work used a fresh local
checkout, without relying on a previous laptop path. No live Firebase data was
written, no secrets were committed, and no deployment or merge was performed.

## Changes

- Preserve text baselines when removing page rules; trim thin ruling remnants
  from MCQ crops. Preserve original scan pixels for recognition.
- Keep punctuation available during optical number-field decoding. Compare
  field and whole-line readings and use an independent handwriting reader for
  disputed entries. Do not infer answer numbers from sequence or an answer key.
- Corroborate lower-support prose only when independent readers agree on its
  words, numbers and mathematical operators. Retain genuinely uncertain text
  and image evidence for examiner review.
- Process every uploaded PDF page in order and persist page records. Do not
  skip a large scanned region simply because a page has a selectable header.
- Connect exam-scoped question-paper upload, confirmation, document versions,
  downloads, archiving and restoration to persistent models and services.
- Support DOCX paragraphs and tables for question papers, answer text and
  answer keys. Word answer documents with embedded images request PDF export
  rather than silently dropping those images.
- Make extracted question text editable in the existing teacher preview.
  Save rubric edits atomically; reject duplicate question numbers and invalid
  criterion totals. Preserve teacher-edited reference answers on key replacement.
- Match numbered student answers to individual questions. Missing, ambiguous
  and uncertain answers receive no automatic mark and enter teacher review.
- Prefer examiner-approved results over earlier blank uploads. Prevent rescan
  and re-evaluation from replacing an examiner's final decision.
- Verify Firebase token signatures, issuer, audience, expiry and verified email.
  Reject unsigned claims. Replace the hardcoded local JWT signing secret with
  a generated default and support `EVALISENSE_JWT_SECRET` for persistent sessions.
- Preserve the existing design and stylesheet. Update file pickers and labels
  for the added document formats and invalidate the JavaScript browser cache.

## Verification

Initial baseline: **59 passed, 27 failed, one collection error**. The collection
error came from disconnected document models; missing endpoints accounted for
many failures. An obsolete static-script assertion was updated to accept cache
query strings, and a rescan test now creates its own unreviewed script rather
than assuming script 1 is unreviewed.

Final results: **113 Python tests passed**, **six frontend workflow tests passed**,
and both JavaScript syntax checks and the whitespace check passed. An additional
targeted run passed all 19 document, authentication and academic-edit cases after
the final Word-image and validation changes. Dependency deprecation warnings
remain; they are not recognition-accuracy results.

Commands:

```text
python -m pytest tests/ -q --tb=short --disable-warnings
node --test tests/frontend_workflows.test.cjs
node --check frontend/app.js
node --check frontend/firebase-db.js
git diff --check
```

Tests use an isolated temporary database and upload directory. They cover
selectable, scanned, mixed, multi-page, oversized, corrupt and encrypted PDFs;
image uploads; Word paragraphs/tables; exam isolation; document lifecycle;
rubric persistence; authentication and role boundaries; teacher review; and
final result calculation. Frontend tests exercise browser-storage logic in an
isolated JavaScript context, including rollback when storage is full.

The academic API end-to-end test supplies a deterministic OCR result to test
evaluation, assignment, review and persistence reliably. It uses the actual
semantic evaluator and forces high risk to exercise examiner assignment. This
is a workflow check, not an OCR accuracy benchmark. The separate scan run below
uses the real local recognition models.

## Real scanned answer-sheet check

```text
python scripts/verify_sample_ocr.py --input data/samples/std1.pdf --output data/results/std1-verified
```

The command accepts other PDFs through `--input`; its recognition logic contains
no sample-specific expected answers. Model files are local, and the verification
run used cached TrOCR weights with network model access disabled.

| Page | Detected answer lines | Review lines before | Review lines after |
| --- | ---: | ---: | ---: |
| 1 | 23 | 4 | 4 |
| 2 | 23 | 10 | 9 |
| 3 | 18 | 5 | 4 |
| 4 | 0 | 0 | 0 |

The faint fourth page was deferred with a foreground warning. Four compact MCQ
entries on page 1 still require confirmation. The two fewer prose warnings come
from independent reading agreement, not a blanket reduction in confidence
thresholds. These counts are **not an accuracy percentage**; a fully reviewed
written-answer transcription was not supplied. Generated transcripts and scan
images stay under the ignored results directory.

## Practical limits

Recognition of every possible PDF or handwriting style cannot be guaranteed.
The bundled handwriting model targets English. Faint, crossed-out, rotated,
mathematical or unfamiliar handwriting may require examiner transcription.
Old binary `.doc` files require conversion to DOCX or PDF. Word images should be
exported to PDF for OCR. Upload size, page count and render-pixel limits remain
enforced to prevent an unusable upload from exhausting the application.

Install dependencies from `requirements.txt`, including `pyjwt[crypto]`. Set a
private `EVALISENSE_JWT_SECRET` outside version control if sessions must survive
server restarts. Verified Firebase email is now required for Firebase-backed
API identity; local seeded API login continues to work. Signature behavior was
tested with generated RSA keys; a live Firebase sign-in, production Firestore
rules and a full interactive browser session were not exercised.
