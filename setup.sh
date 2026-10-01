#!/bin/bash
# ============================================================
#  EvaliSense — Linux/macOS Setup Script
#  Creates virtual environment, installs all dependencies,
#  and verifies the installation.
#
#  Usage:  chmod +x setup.sh && ./setup.sh
# ============================================================

set -e

echo ""
echo "============================================================"
echo "  EvaliSense — Automated Setup"
echo "============================================================"
echo ""

# ─── Check Python ───
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 is not installed."
    echo "        Install via: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1)
echo "[INFO]  $PYTHON_VERSION"

# ─── Create Virtual Environment ───
if [ -d ".venv" ]; then
    echo "[INFO]  Virtual environment already exists at .venv/"
    echo "        Skipping creation. Delete .venv/ to recreate."
else
    echo "[INFO]  Creating virtual environment..."
    python3 -m venv .venv
    echo "[OK]    Virtual environment created at .venv/"
fi

# ─── Activate ───
echo "[INFO]  Activating virtual environment..."
source .venv/bin/activate

# ─── Upgrade pip ───
echo "[INFO]  Upgrading pip..."
pip install --upgrade pip --quiet

# ─── Install Dependencies ───
echo "[INFO]  Installing dependencies from requirements.txt..."
echo "        This may take several minutes (PyTorch, transformers, etc.)"
echo ""
pip install -r requirements.txt

echo ""
echo "[OK]    All dependencies installed."

# ─── Create Data Directories ───
echo "[INFO]  Creating data directories..."
mkdir -p data/{raw,processed,external,results,annotations}
mkdir -p trained_models experiments
echo "[OK]    Data directories ready."

# ─── Verify Installation ───
echo ""
echo "[INFO]  Verifying installation..."
echo ""

python3 -c "from config import config; print(f'  [OK] config        — project root: {config.project_root}')" 2>/dev/null || echo "  [FAIL] config"
python3 -c "from preprocessing import ImagePreprocessor; print('  [OK] preprocessing — ImagePreprocessor loaded')" 2>/dev/null || echo "  [FAIL] preprocessing"
python3 -c "from htr import HTRPipeline; print('  [OK] htr           — HTRPipeline loaded')" 2>/dev/null || echo "  [FAIL] htr"
python3 -c "from evaluation import AnswerEvaluator, Rubric; print('  [OK] evaluation    — AnswerEvaluator loaded')" 2>/dev/null || echo "  [FAIL] evaluation"
python3 -c "from features import extract_features; print('  [OK] features      — extract_features loaded')" 2>/dev/null || echo "  [FAIL] features"
python3 -c "from models import GradingRiskModel; print('  [OK] models        — GradingRiskModel loaded')" 2>/dev/null || echo "  [FAIL] models"
python3 -c "import torch; print(f'  [OK] torch         — version {torch.__version__}')" 2>/dev/null || echo "  [FAIL] torch"
python3 -c "import sklearn; print(f'  [OK] scikit-learn  — version {sklearn.__version__}')" 2>/dev/null || echo "  [FAIL] scikit-learn"
python3 -c "import cv2; print(f'  [OK] opencv        — version {cv2.__version__}')" 2>/dev/null || echo "  [FAIL] opencv"
python3 -c "import fastapi; print(f'  [OK] fastapi       — version {fastapi.__version__}')" 2>/dev/null || echo "  [FAIL] fastapi"

# ─── Done ───
echo ""
echo "============================================================"
echo "  Setup Complete!"
echo "============================================================"
echo ""
echo "  To activate the environment in future sessions:"
echo ""
echo "      source .venv/bin/activate"
echo ""
echo "  Quick start commands:"
echo ""
echo "      python run_demo.py --help              # Run demo"
echo "      python train_risk_model.py --compare    # Train models"
echo "      uvicorn api.app:app --reload            # Start API server"
echo "      cd notebooks && jupyter notebook        # Open notebooks"
echo ""
echo "  First-time data setup:"
echo ""
echo "      python scripts/generate_synthetic_dataset.py --count 300"
echo "      python scripts/create_test_images.py"
echo "      python scripts/download_datasets.py --skip-kaggle"
echo ""
echo "============================================================"
