# EvaliSense — Project Summary & Results

## What is EvaliSense?

EvaliSense is a system that helps teachers grade handwritten exam papers using AI. It does **not** replace the teacher — it reads the handwriting, scores it against a rubric, and then tells the teacher "hey, you might want to double-check this one" if the AI thinks its own grading might be wrong.

Think of it as a smart assistant that reads papers, gives a preliminary score, and flags the risky ones for human review.

---

## How Does It Work? (Step by Step)

### Step 1 — Data Exploration (Notebook 01)

**What we did:** Looked at the data we're working with — the IAM Handwriting Dataset, our rubrics, and test answer sheets.

**Key numbers:**
- IAM dataset: thousands of handwriting samples from hundreds of different writers
- 4 rubrics created: Biology (Photosynthesis), Cell Biology, History (Industrial Revolution), Physics (Newton's Laws)
- 6 test images generated: 1 good, 1 partial, 1 poor answer for Photosynthesis + 1 Cell Biology + 1 History + 1 empty sheet
- Each test image is ~11 MB (high resolution scans at ~2400×3200 pixels)

**What it shows:** Handwriting varies a lot across writers — some neat, some messy. This is exactly the kind of variation the system needs to handle.

---

### Step 2 — Preprocessing (Notebook 02)

**What we did:** Before the AI can read handwriting, the image needs to be cleaned up. We convert to grayscale, remove noise, binarize (make it black and white), and segment into individual lines.

**Key numbers:**
- Preprocessing time: **< 0.5 seconds** per image
- Steps: Grayscale → Gaussian blur → Otsu thresholding → Morphological cleaning
- Line segmentation: horizontal projection analysis splits text into individual lines

**What it shows:** The preprocessing pipeline is fast and reliable. Otsu's binarization handles different lighting and contrast levels well.

---

### Step 3 — Handwriting Recognition (Notebook 03)

**What we did:** Used Microsoft's TrOCR model (`microsoft/trocr-base-handwritten`, 334 million parameters) to read the handwritten text and convert it to typed text.

**Key numbers:**
- Model size: **334M parameters**
- Processing time: **1–5 seconds per line** on CPU
- Confidence scores: range from 0.0 to 1.0 (higher = more confident)
- Good handwriting: confidence typically **0.7–0.95**
- Messy handwriting: confidence drops to **0.3–0.6**

**What it shows:** TrOCR reads most handwriting reasonably well on a regular CPU. The confidence score is actually useful — when it's low, it usually means the handwriting was hard to read, and that becomes a signal for the risk model later.

---

### Step 4 — Answer Evaluation (Notebook 04)

**What we did:** Compared the recognized text against the rubric using Sentence-BERT (`all-MiniLM-L6-v2`, 22M parameters). Each criterion in the rubric is checked for semantic similarity.

**Key numbers:**
- Evaluation model: **22M parameters** (lightweight)
- Evaluation time: **< 2 seconds** per answer
- Similarity threshold: **0.55** (above this = criterion met)
- Good answer scores: **~7–10 out of 10** (close to full marks)
- Partial answer scores: **~4–6 out of 10**
- Poor answer scores: **~1–3 out of 10**
- Empty answer: **0 out of 10**

**What it shows:** The AI scoring correctly discriminates between good, partial, and poor answers. The scores land in the expected ranges for all test cases.

---

### Step 5 — Feature Engineering (Notebook 05)

**What we did:** Extracted **16 measurable features** from each evaluation — things like OCR confidence, semantic similarity, score patterns, and keyword coverage.

**The 16 features:**

| # | Feature | What it measures |
|---|---------|-----------------|
| 1 | `ocr_confidence` | How confident the handwriting reader was |
| 2 | `overall_semantic_similarity` | How closely the answer matches the expected answer |
| 3 | `mean_criterion_similarity` | Average similarity across all rubric criteria |
| 4 | `min_criterion_similarity` | Worst-matching criterion (weakest point) |
| 5 | `max_criterion_similarity` | Best-matching criterion (strongest point) |
| 6 | `std_criterion_similarity` | How inconsistent the criterion scores are |
| 7 | `rubric_coverage` | How many rubric criteria the student addressed |
| 8 | `keyword_coverage` | How many expected keywords appeared |
| 9 | `answer_length_chars` | Total characters in the answer |
| 10 | `answer_length_tokens` | Total words/tokens in the answer |
| 11 | `num_recognized_lines` | How many lines of text were found |
| 12 | `evaluation_confidence` | How confident the evaluator is in its scoring |
| 13 | `ai_preliminary_mark` | The AI's raw score |
| 14 | `max_marks` | Maximum possible marks for this question |
| 15 | `normalized_score` | Score as a percentage (0.0 – 1.0) |
| 16 | `mark_deviation_from_mean_criterion` | Does the score seem inconsistent with the evidence? |

**What it shows:** Features show a clear quality gradient — good answers have high similarity, high coverage, and high confidence. Poor answers score low across the board. The features capture meaningful signals.

---

### Step 6 — Model Training (Notebook 06)

**What we did:** Trained **4 different ML classifiers** to predict whether the AI's grading might be wrong. Used **5-fold stratified cross-validation** on **300 synthetic records**.

**Training data stats:**
- Total records: **300**
- Feature dimensions: **16**
- Non-error samples: **234 (78%)**
- Error samples: **66 (22%)**
- Error threshold: **≥ 2.0 marks** disagreement between AI and expert

**Cross-validation results (before tuning):**

| Model | Accuracy | Precision | Recall | F1 Score | ROC-AUC |
|-------|----------|-----------|--------|----------|---------|
| Random Forest | 0.7267 | 0.4117 | 0.5165 | 0.4557 | 0.7474 |
| SVM (RBF) | 0.6633 | 0.3473 | 0.6231 | 0.4440 | 0.7474 |
| Logistic Regression | **0.7033** | **0.4040** | **0.7275** | **0.5159** | **0.7726** |
| Gradient Boosting | 0.7667 | 0.4531 | 0.2736 | 0.3303 | 0.7214 |

**Best model:** Logistic Regression (F1 = **0.5159**, Recall = **0.7275**)

**Why Recall matters most:** If we miss a grading error, a student gets the wrong marks — that's a real problem. If we flag a correct paper for review, the teacher just checks it and moves on — minor inconvenience. So we want high Recall (catching as many errors as possible), even if Precision is lower.

**Why Gradient Boosting has the highest accuracy but worst F1:** It predicts "Non-Error" most of the time (since 78% of papers are non-errors). High accuracy, but terrible at actually catching errors (Recall = 0.27 means it misses 73% of errors).

---

### Step 7 — Full Pipeline Demo (Notebook 07)

**What we did:** Ran the entire pipeline end-to-end — from raw handwritten image to risk prediction.

**Timing breakdown:**
- Preprocessing: **< 0.5s** (~2% of total time)
- HTR Recognition: **30–80s** (~85–90% of total time) — includes model loading
- Answer Evaluation: **1–2s** (~3%)
- Feature Extraction: **< 0.01s** (instant)
- Risk Prediction: **< 0.01s** (instant)
- **Total: ~30–90 seconds per answer sheet** on CPU

**What it shows:** The whole thing works end-to-end. HTR is the bottleneck (transformer model on CPU). Everything else is nearly instant.

---

### Step 8 — Hyperparameter Tuning (Notebook 08)

**What we did:** Ran GridSearchCV to find better model settings.

**Search spaces tested:**
- Random Forest: 4 × 4 × 3 × 3 = **144 combinations** (n_estimators, max_depth, min_samples_split, min_samples_leaf)
- SVM: 5 × 4 × 2 = **40 combinations** (C, gamma, kernel)

**What we found:**
- RF optimal: `n_estimators=200`, `max_depth=10-15`
- SVM optimal: `kernel='rbf'`, `C=1.0-5.0`
- Tuning gives **~2–5% F1 improvement** over defaults
- With only 300 records, aggressive tuning risks overfitting — 5-fold CV guards against this

---

### Step 9 — Error Analysis (Notebook 09)

**What we did:** Analyzed which papers the model gets wrong — false positives (unnecessary reviews) and false negatives (missed errors).

**Saved model metrics (SVM, trained on full data):**
- Accuracy: **62.7%**
- Precision: **0.30** (30% of flagged papers actually have errors)
- Recall: **0.56** (catches 56% of real errors)
- F1 Score: **0.39**
- ROC-AUC: **0.66**
- Confusion matrix: TP=9, TN=38, FP=21, FN=7

**What the confusion matrix means:**
- **38 papers** correctly identified as non-errors ✓
- **9 papers** correctly caught as grading errors ✓
- **21 papers** flagged unnecessarily (teacher checks them, finds they're fine — minor waste)
- **7 papers** with errors that were MISSED ← this is the problem

**Key insight:** The model is more confident when it's right. Misclassified samples cluster near the 0.5 decision boundary — they're borderline cases.

---

### Step 10 — Final Evaluation (Notebook 10)

**Final system specs:**

| Metric | Value |
|--------|-------|
| Pipeline latency | 30–90 seconds per paper |
| Hardware | Intel Core Ultra 9 285H, 32GB RAM |
| GPU required | No (CPU-only) |
| HTR model | TrOCR (334M params) |
| Evaluation model | MiniLM (22M params) |
| Risk model size | **28 KB** |
| Training data | 300 synthetic records |
| Feature count | 16 dimensions |
| Best CV F1 | 0.5159 (Logistic Regression) |
| Error threshold | ≥ 2.0 marks |

---

## Before Tuning vs After Tuning

| Metric | Before Tuning (defaults) | After Tuning (GridSearchCV) | Improvement |
|--------|--------------------------|----------------------------|-------------|
| F1 Score | ~0.44–0.52 | ~0.46–0.54 | +2–5% |
| Recall | ~0.52–0.73 | ~0.55–0.75 | +2–3% |

The improvement is modest because the dataset is small (300 records). With more data, tuning would make a bigger difference.

---

## Current Limitations (Be Honest About These)

1. **Synthetic training data.** The risk model is trained on computer-generated fake records, not real teacher-graded papers. The model has never seen actual teacher disagreements. This is the **biggest limitation**.

2. **Small dataset.** Only 300 synthetic records. Real ML models usually need thousands of examples. With 300 records, the model can learn basic patterns but can't capture subtle edge cases.

3. **Moderate performance.** F1 of ~0.5 means the model is better than random, but far from production-ready. It catches about half of real errors and flags a lot of non-errors. Good enough for a proof-of-concept, not for deployment.

4. **English only.** TrOCR is trained on English handwriting. Won't work for other languages.

5. **Simple line segmentation.** The horizontal projection method may fail on overlapping, diagonal, or very messy handwriting.

6. **No real exam validation.** We haven't tested with actual exam papers graded by actual teachers.

---

## What's Needed for Real-World Use

### Getting Real Training Data

The biggest gap is **real grading data**. Here's how to get it:

1. **Self-handwritten papers:** Write exam answers by hand and have 2–3 people grade them independently. The disagreements between graders become training labels. **But we need many — at least 200–500 papers** with multiple teacher grades to train a meaningful model.

2. **Partner with a school/college:** Get access to actual exam papers with teacher marks. Run the AI on those papers and compare. Every time AI disagrees with the teacher by ≥ 2 marks → that's a training sample.

3. **Active learning:** Deploy the system, let teachers correct the AI's scores, feed corrections back into training. Model improves over time.

### What Stays the Same

- The **16 features** stay the same (computed from the pipeline, not from training data)
- The **preprocessing, HTR, and evaluation** components work regardless of training data
- Only the **risk model** needs retraining — takes seconds on a laptop
- The **architecture** is ready — just needs better data

---

## Conclusion

EvaliSense works end-to-end on a regular laptop. It reads handwriting, scores answers, and flags risky evaluations. The pipeline runs in under 2 minutes on CPU with no GPU needed.

The current model achieves an F1 of ~0.5 on synthetic data — a solid proof-of-concept showing the approach works. With real exam papers and teacher grades, the system has the potential to significantly reduce grading workload while catching grading errors before they reach students.

The risk model is only 28KB. The entire system is practical, interpretable, and deployable on standard hardware. Teachers stay in control — the AI assists, it doesn't replace.
