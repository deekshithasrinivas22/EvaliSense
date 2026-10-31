# EvaliSense development verification

## Answer-retention rollback (2026-10-31)

The user reported that the latest recognition changes were worse and hid too
many answers. Restore the earlier written-answer recognizer, remove experimental
margin cropping, and stop converting low-support or nonstandard MCQ candidates
into number-only/empty strings. Preserve the complete recognized candidate for
examiner correction. Bare numerical answers in the answer area are no longer
classified as footer page counters. Keep the single Re-review button and clean
display without internal placeholder labels.

Validation: 132 backend tests passed, including answer-retention coverage. The
running port-8001 app was changed to v11-preserve-answers and its four uploaded
sessions were restored. Previous cached results require Re-review to regenerate.
This rollback preserves answer content; it does not establish perfect numbering
or handwriting accuracy. Earlier numbering experiments below are historical.

## Latest numbering and page-label fix (2026-10-31)

The actual four-page scan was located in the running app's uploaded sessions.
Recognition now uses the pixel gap between a margin number and its answer,
rather than assuming that an OCR letter such as the `G` in `2G.` starts the
answer. Optical number crops must agree with an independent handwriting reading
before an ambiguous number is replaced. Compact MCQs also receive an independent
whole-entry check, resolving the reproduced 15/16 error without sequence filling.

A large footer gutter separates the last MCQ from the circled page counter.
Standalone Solution headings and page counters are excluded in page-furniture
positions. Clipped or weakly supported MCQ options are left empty while a readable
question number is retained; an option letter is never invented.

Real-scan checks using the same rendered pixels as the running application:

- Page 1: question numbers 1 through 20 were recovered without duplicates.
- The separately cropped written-answer number 26 was confirmed by both optical
  and handwriting number-crop readings; the answer body retained its own crop.
- The Solution heading and page-counter crop were excluded from answer text.
- The final MCQ option is clipped in the source; it still needs examiner input.

Validation: 132 full-suite backend tests passed, followed by 19 focused numbering
and recognition-cache checks after the version update; 10 frontend tests passed.
The live port-8001 server was updated to OCR version v10, with all three existing
sessions restored and the uploaded scan hash/page count unchanged. Use Re-review
once to regenerate an existing cached reading with the updated recognizer.

## Latest UI simplification (2026-10-31)

At the user's request, keep one **Re-review** button and the editable script.
Remove the repeated per-line panels, page-comparison panels and extra controls.
Strip internal `[Unclear page ... line ...]` labels from displayed text and omit
marker-only rows, while retaining readable OCR candidates. Internal diagnostics
remain available, and handwriting still requires examiner confirmation before
whole-script grading. The client also cleans older server responses so the
running copy can show the simplified interface without a server restart.

Validation: 12 focused backend tests and 10 frontend tests passed; syntax and
whitespace checks passed. The running port-8001 page serves exactly one review
button, no old comparison controls or line-panel code, and the new script cache
version. No live server restart was required for these UI changes.

## Follow-up: blank areas and re-review (2026-10-31)

- Empty crops, isolated scan specks and thin ruling are checked before either
  handwriting pipeline invokes a text model. These regions produce no text
  and no `Unclear` marker. A substantive single glyph remains eligible for OCR.
- Blank-only recognition can return an empty reading and clear a stale result;
  it cannot receive an automatic zero mark through the single-answer evaluator.
- Add **Re-review / Rescan text**, **Upload clearer scan**, **Restore previous
  text**, and **Use fresh reading** controls. Fresh rescan bypasses the cache,
  preserves edits made before/during the retry, and offers a comparison instead
  of overwriting examiner corrections. Previous text is held for this browser
  session; it is not a durable backup across browser restarts.
- Each uncertain line has **Re-verify this line** for unrestricted optical and
  handwriting readings of its original crop, plus **Mark as blank — remove
  marker** for examiner-confirmed empty areas. Rechecks do not automatically
  replace text or claim that candidates are verified.
- Fresh recognition invalidates previous scores/risk displays while retaining
  limited recognition/review history. A failed retry leaves the previous result
  and corrections intact. Overlapping recognition requests return a conflict.
- Repeated wide gutters split side-by-side table text into separate crops in
  row order. Repeated readable MCQ numbers and gaps are flagged without filling
  in or renumbering answers.

Validation: **124 backend tests passed**, plus **nine frontend workflow tests**.
An additional final focused run passed all **11 recognition-review tests** after
the last history/cache changes. JavaScript syntax and whitespace checks passed.
The actual `LocalDocumentPipeline` returned `''`, zero lines and zero warnings
for both a white image and a ruled blank image, without loading TrOCR to invent
text. Tests also preserve a real single-letter glyph, reject scan specks, cover
cache bypass, failed retries, line rechecks, table gutters and correction safety.

The PDF underlying the newly pasted transcript was not available in this
workspace. These checks establish blank handling and retry behavior; they do
not establish an accuracy improvement for that particular handwriting sample.

## Original development baseline

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
