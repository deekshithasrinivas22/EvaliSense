# EvaliSense

## Project Name
**EvaliSense: AI-Powered Handwritten Examination Evaluation with ML-Based Grading Error Prediction**

## Project Purpose
EvaliSense is an **examiner-assistance system** designed to support the evaluation of handwritten examination answers. It does **not** replace teachers or examiners. The system assists with a structured, transparent, and auditable evaluation workflow in which a **human examiner remains responsible for the final mark**.

## Core Research Question
> Can machine learning predict when an AI-based handwritten examination grading system is likely to produce a significant grading error?

## High-Level Pipeline

```
Handwritten Answer Image
        ↓
Image Preprocessing (grayscale, denoise, contrast, deskew)
        ↓
Handwritten Text Recognition (TrOCR)
        ↓
Extracted Text + OCR Confidence
        ↓
Rubric-Based Semantic Evaluation
        ↓
AI Preliminary Mark
        ↓
Evaluation Feature Extraction
        ↓
ML-Based Grading Error Risk Prediction
        ↓
LOW RISK / HIGH RISK
        ↓
Human Examiner Review
        ↓
Final Examiner Mark
```

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.13 |
| HTR Model | `microsoft/trocr-base-handwritten` (TrOCR) |
| Embeddings | `all-MiniLM-L6-v2` (sentence-transformers) |
| ML Models | scikit-learn (Logistic Regression, Random Forest, SVM, Gradient Boosting) |
| Image Processing | OpenCV |
| Backend API | FastAPI + Uvicorn |
| Frontend | HTML / CSS / JavaScript |
| Testing | pytest |

## Repository Structure

```
EvaliSense/
├── config.py                          # Project-wide configuration
├── requirements.txt                   # Python dependencies
├── preprocessing_demo.py              # Preprocessing CLI demo
├── htr_demo.py                        # HTR CLI demo
├── generate_synthetic_dataset.py      # Synthetic dataset generator
├── train_risk_model.py                # Model training script
│
├── preprocessing/                     # Image preprocessing module
│   ├── image_preprocessor.py          # Configurable preprocessing pipeline
│   └── pipeline.py                    # Convenience wrapper
│
├── htr/                               # Handwritten Text Recognition module
│   ├── recognizer.py                  # TrOCR model integration
│   ├── line_segmenter.py              # Page → line segmentation
│   ├── pipeline.py                    # End-to-end HTR pipeline
│   └── result.py                      # Result data structures
│
├── evaluation/                        # Answer evaluation module
│   ├── rubric.py                      # Rubric schema and validation
│   ├── semantic.py                    # Semantic similarity (sentence-transformers)
│   └── evaluator.py                   # Rubric-based answer evaluator
│
├── features/                          # Feature extraction module
│   ├── extractor.py                   # Feature vector extraction
│   └── dataset.py                     # Ground-truth dataset management
│
├── models/                            # ML models module
│   └── risk_model.py                  # Grading-error risk prediction
│
├── api/                               # Backend API
│   └── app.py                         # FastAPI application
│
├── frontend/                          # Web frontend
│   ├── index.html                     # Dashboard and evaluation UI
│   ├── style.css                      # Design system
│   └── app.js                         # Frontend logic
│
├── tests/                             # Test suite
│   ├── test_preprocessing.py
│   ├── test_htr.py
│   ├── test_evaluation.py
│   ├── test_features.py
│   ├── test_risk_model.py
│   └── test_config.py
│
├── data/                              # Data directory
│   ├── raw/                           # Raw handwritten images
│   ├── processed/                     # Preprocessed images
│   ├── samples/                       # Sample rubrics and datasets
│   ├── annotations/                   # Expert annotations
│   └── results/                       # Evaluation results
│
├── experiments/                       # Experiment tracking
├── notebooks/                         # Exploratory notebooks
└── utils/                             # Utility modules
    └── logging.py                     # Structured logging
```

## Installation

### 1. Create Environment
```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Verify Installation
```bash
python -c "from config import config; print(config.project_root)"
python -c "from preprocessing import ImagePreprocessor; print('OK')"
python -c "from evaluation import AnswerEvaluator; print('OK')"
```

## Running the Project

### Start the Backend API
```bash
uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload
```

Then open http://127.0.0.1:8000 in your browser.

### Run Preprocessing Demo
```bash
python preprocessing_demo.py --input path/to/answer.jpg --output data/processed/answer_processed.png
```

### Run HTR Demo
```bash
python htr_demo.py --input data/raw/test_answer.jpg --output experiments/htr_baseline/raw --debug-lines
```

## Model Training

### 1. Generate Synthetic Dataset (Development)
```bash
python generate_synthetic_dataset.py --output data/samples/synthetic_dataset.jsonl --count 200
```

> ⚠️ Synthetic data is for development only. Do not present as real research results.

### 2. Train Risk Model
```bash
# Train a single model
python train_risk_model.py --dataset data/samples/synthetic_dataset.jsonl --model RandomForest

# Compare all models and select the best
python train_risk_model.py --dataset data/samples/synthetic_dataset.jsonl --compare
```

### 3. Train with Custom Threshold
```bash
python train_risk_model.py --dataset data/samples/synthetic_dataset.jsonl --compare --error-threshold 1.5
```

## Running Tests
```bash
# Run all tests
pytest tests/ -v

# Run specific test files
pytest tests/test_preprocessing.py -v
pytest tests/test_evaluation.py -v
pytest tests/test_features.py -v
pytest tests/test_risk_model.py -v

# Run with coverage
pytest tests/ -v --cov=. --cov-report=term-missing
```

## Configuration

All settings can be overridden via environment variables prefixed with `EVALISENSE_`:

| Variable | Default | Description |
|----------|---------|-------------|
| `EVALISENSE_HTR_MODEL_NAME` | `microsoft/trocr-base-handwritten` | HTR model |
| `EVALISENSE_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence embedding model |
| `EVALISENSE_ERROR_THRESHOLD` | `2.0` | Grading error threshold (marks) |
| `EVALISENSE_API_PORT` | `8000` | API server port |
| `EVALISENSE_LOG_LEVEL` | `INFO` | Logging level |

## Dataset Format

### Ground-Truth Records (JSONL)
Each line is a JSON object:
```json
{
  "record_id": "abc123",
  "question": "Explain photosynthesis",
  "student_answer": "...",
  "ai_mark": 7.0,
  "expert_mark": 6.0,
  "max_marks": 10.0,
  "absolute_error": 1.0,
  "is_grading_error": false,
  "features": { "ocr_confidence": 0.72, "..." : "..." },
  "metadata": { "source": "examiner_review" }
}
```

### Rubric Format (JSON)
```json
{
  "question": "Explain photosynthesis",
  "max_marks": 10,
  "reference_answer": "...",
  "criteria": [
    {
      "id": "c1",
      "description": "Explains energy conversion",
      "marks": 2,
      "keywords": ["light energy", "chemical energy"]
    }
  ]
}
```

## API Documentation

When the server is running, interactive API docs are available at:
- **Swagger UI**: http://127.0.0.1:8000/docs
- **ReDoc**: http://127.0.0.1:8000/redoc

### Key Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/upload` | Upload handwritten answer image |
| `POST` | `/api/preprocess/{id}` | Run image preprocessing |
| `POST` | `/api/recognize/{id}` | Run HTR |
| `POST` | `/api/evaluate/{id}` | Evaluate against rubric |
| `POST` | `/api/predict-risk/{id}` | Predict grading error risk |
| `POST` | `/api/submit-review/{id}` | Submit examiner's final mark |
| `GET`  | `/api/session/{id}` | Get session details |
| `GET`  | `/api/model-info` | Risk model information |
| `GET`  | `/api/health` | Health check |

## Architecture

```
                    ┌──────────────┐
                    │   Frontend   │
                    │ (HTML/CSS/JS)│
                    └──────┬───────┘
                           │ HTTP
                    ┌──────▼───────┐
                    │  FastAPI     │
                    │  Backend     │
                    └──────┬───────┘
            ┌──────────────┼──────────────┐
            │              │              │
    ┌───────▼─────┐ ┌──────▼──────┐ ┌─────▼──────┐
    │Preprocessing│ │ HTR Pipeline│ │ Evaluation  │
    │  Module     │ │ (TrOCR)     │ │  Module     │
    └─────────────┘ └─────────────┘ └──────┬──────┘
                                           │
                                    ┌──────▼──────┐
                                    │  Feature    │
                                    │ Extraction  │
                                    └──────┬──────┘
                                           │
                                    ┌──────▼──────┐
                                    │  Risk Model │
                                    │ (sklearn)   │
                                    └──────┬──────┘
                                           │
                                    ┌──────▼──────┐
                                    │  Examiner   │
                                    │  Review     │
                                    └─────────────┘
```

### Future Cloud Architecture
```
Frontend → Backend API → Preprocessing Service → HTR Service
                       → Evaluation Service → Risk Prediction Service
                       → Database / Object Storage
```

## Examiner Authority
**The examiner remains the final authority.** EvaliSense produces preliminary AI marks and risk predictions that serve as decision-support for the human examiner. The examiner can approve, modify, or override any AI-generated evaluation.

## Limitations
- HTR accuracy depends on handwriting quality and image conditions.
- Semantic evaluation uses general-purpose embeddings, not domain-specific ones.
- The risk model requires sufficient ground-truth data for meaningful results.
- Synthetic data is for development only and does not represent real performance.
- CPU-only execution may be slow for large batches.

## Future Improvements
- Domain-specific fine-tuning of the embedding model.
- Active learning for risk model improvement.
- PDF and multi-page document support.
- Batch evaluation mode.
- Database integration for persistent storage.
- User authentication and role-based access.
- Deployment automation (Docker, cloud).

## Important Design Decisions
1. **Modular architecture**: Each component (preprocessing, HTR, evaluation, features, models, API) is independently testable.
2. **Lazy model loading**: Models are loaded on first use and cached to avoid unnecessary startup time.
3. **Heuristic fallback**: When no trained ML model exists, a rule-based heuristic provides risk estimates.
4. **Ground-truth collection**: Every examiner review creates a training record for future model improvement.
5. **Configurable error threshold**: The grading-error threshold is configurable, not hardcoded.
6. **CPU-first design**: All components are optimised for CPU execution.
