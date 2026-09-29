# EvaliSense — Jupyter Notebooks

Complete set of notebooks demonstrating the EvaliSense pipeline. Run them **in order** — each builds on the previous one.

## Prerequisites

```bash
pip install jupyter matplotlib
cd notebooks
jupyter notebook
```

> **Note:** Notebooks use `sys.path.insert(0, '..')` to import project modules.
> Always run from the `notebooks/` directory.

## Notebook Index

| # | Notebook | Description | Key Outputs |
|---|----------|-------------|-------------|
| 01 | [Data Exploration](01_data_exploration.ipynb) | Explore all datasets — IAM images, rubrics, synthetic data | Dataset stats, visualizations |
| 02 | [Preprocessing Pipeline](02_preprocessing_pipeline.ipynb) | Image preprocessing: grayscale, binarization, deskewing | Before/after comparisons |
| 03 | [HTR Recognition](03_htr_recognition.ipynb) | TrOCR handwritten text recognition + CER/WER benchmarking | Recognition results, metrics |
| 04 | [Answer Evaluation](04_answer_evaluation.ipynb) | Rubric-based scoring with semantic similarity | Scores, similarity heatmaps |
| 05 | [Feature Engineering](05_feature_engineering.ipynb) | 16-dim feature vector extraction for risk prediction | Feature importance, correlations |
| 06 | [Model Training](06_model_training.ipynb) | Train & compare 4 ML classifiers (RF, SVM, LR, GB) | ROC curves, confusion matrices |
| 07 | [Full Pipeline Demo](07_full_pipeline_demo.ipynb) | End-to-end: image → preprocessing → HTR → eval → risk | Complete pipeline summary |

## Expected Runtime

| Notebook | Approximate Time | Notes |
|----------|-----------------|-------|
| 01 | ~30 seconds | No ML models loaded |
| 02 | ~1 minute | OpenCV preprocessing only |
| 03 | ~5-15 minutes | TrOCR first load: ~330 MB download |
| 04 | ~2-3 minutes | Sentence-BERT first load: ~80 MB |
| 05 | ~1-2 minutes | Uses pre-loaded evaluator |
| 06 | ~2-3 minutes | Trains 4 classifiers with cross-validation |
| 07 | ~5-10 minutes | Full pipeline (loads all models) |

## Outputs

All generated plots are saved to `data/results/` for use in reports:
- `iam_samples_visualization.png`
- `iam_length_distribution.png`
- `preprocessing_comparison.png`
- `preprocessing_steps.png`
- `htr_recognition_results.png`
- `htr_metrics.png`
- `evaluation_results.png`
- `similarity_heatmap.png`
- `feature_comparison.png`
- `feature_importance.png`
- `feature_correlation.png`
- `cv_comparison.png`
- `model_evaluation.png`
- `rf_feature_importance.png`
- `pipeline_summary.png`
