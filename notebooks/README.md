# EvaliSense — Jupyter Notebooks

Complete set of research notebooks documenting the EvaliSense development workflow. Run them **in order** — each builds on the previous one.

## Prerequisites

```bash
pip install jupyter matplotlib seaborn
cd notebooks
jupyter notebook
```

> **Note:** Notebooks use `sys.path.insert(0, '..')` to import project modules.
> Always run from the `notebooks/` directory.

## Notebook Index

| # | Notebook | Description | Key Outputs |
|---|----------|-------------|-------------|
| 01 | [Data Exploration](01_data_exploration.ipynb) | Inventory all datasets — IAM images (10K+), rubrics, answers, synthetic data | Dataset stats, distribution plots |
| 02 | [Preprocessing Pipeline](02_preprocessing_pipeline.ipynb) | Step-by-step image preprocessing: grayscale → blur → binarize → clean | Before/after comparisons, binarization comparison |
| 03 | [HTR Recognition](03_htr_recognition.ipynb) | TrOCR handwritten text recognition + CER/WER benchmarking on IAM | Recognition results, per-sample metrics |
| 04 | [Answer Evaluation](04_answer_evaluation.ipynb) | Rubric-based scoring with Sentence-BERT, semantic similarity analysis | Scores vs expected, similarity heatmap |
| 05 | [Feature Engineering](05_feature_engineering.ipynb) | 16-D feature vector extraction, class separation, correlation matrix | Feature importance, correlation heatmap |
| 06 | [Model Training](06_model_training.ipynb) | Train & compare 4 ML classifiers (RF, SVM, LR, GB) with 5-fold CV | ROC curves, confusion matrix, F1 comparison |
| 07 | [Full Pipeline Demo](07_full_pipeline_demo.ipynb) | End-to-end: image → preprocess → HTR → eval → features → risk → review | Pipeline summary visualization |
| 08 | [Hyperparameter Tuning](08_hyperparameter_tuning.ipynb) | GridSearchCV on RF and SVM, parameter effect analysis | Tuned vs baseline comparison |
| 09 | [Error Analysis](09_error_analysis.ipynb) | FP/FN breakdown, feature patterns in misclassifications, impact assessment | Error feature distributions, calibration plot |
| 10 | [Final Evaluation](10_final_evaluation.ipynb) | System summary, model comparison table, limitations & future work | Publication-ready figures, results table |

## Expected Runtime

| Notebook | Approximate Time | Notes |
|----------|-----------------|-------|
| 01 | ~30 seconds | No ML models loaded |
| 02 | ~1 minute | OpenCV preprocessing only |
| 03 | ~5-15 minutes | TrOCR first load: ~330 MB download |
| 04 | ~2-3 minutes | Sentence-BERT first load: ~80 MB |
| 05 | ~1-2 minutes | Uses pre-loaded evaluator |
| 06 | ~2-3 minutes | 4 classifiers × 5-fold CV |
| 07 | ~5-10 minutes | Full pipeline (loads all models) |
| 08 | ~3-5 minutes | GridSearchCV with ~144 combinations |
| 09 | ~1 minute | Uses pre-trained model |
| 10 | ~2-3 minutes | Final model comparison |

## Outputs

All generated plots are saved to `data/results/` for use in reports:

### Notebook 01
- `iam_statistics.png` — IAM transcription length distributions
- `iam_samples.png` — Sample handwriting images
- `rubric_analysis.png` — Rubric comparison
- `synthetic_data_analysis.png` — Synthetic dataset analysis
- `test_images_overview.png` — Generated test images

### Notebook 02
- `preprocessing_comparison.png` — Before/after
- `preprocessing_steps.png` — Step-by-step breakdown
- `iam_preprocessing.png` — IAM images preprocessed
- `binarization_comparison.png` — Otsu vs Adaptive

### Notebook 03
- `htr_recognition_results.png` — Recognition with ground truth
- `htr_metrics.png` — CER/WER/confidence per sample
- `line_segmentation.png` — Detected line regions

### Notebook 04
- `evaluation_results.png` — Score vs expected range
- `similarity_heatmap.png` — Criteria × sentences

### Notebook 05
- `feature_by_quality.png` — Features by answer quality
- `feature_importance_separation.png` — Class separation ranking
- `feature_correlation.png` — Correlation matrix

### Notebook 06
- `cv_comparison.png` — 5-fold CV box plots
- `model_evaluation.png` — Confusion matrix + ROC + PR
- `rf_feature_importance.png` — Gini importance

### Notebook 07
- `pipeline_summary.png` — 6-panel end-to-end summary

### Notebook 08
- `hp_rf_analysis.png` — Hyperparameter effect

### Notebook 09
- `error_analysis_features.png` — FP/FN feature distributions
- `confidence_analysis.png` — Prediction confidence

### Notebook 10
- `final_model_comparison.png` — Publication-ready comparison chart
