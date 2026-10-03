@echo off
REM ============================================================
REM  EvaliSense — Windows Setup Script
REM  Creates virtual environment, installs all dependencies,
REM  and verifies the installation.
REM
REM  Usage:  setup.bat
REM ============================================================

echo.
echo ============================================================
echo   EvaliSense — Automated Setup
echo ============================================================
echo.

REM ─── Check Python ───
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed or not on PATH.
    echo         Download from: https://www.python.org/downloads/
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYTHON_VERSION=%%v
echo [INFO]  Python version: %PYTHON_VERSION%

REM ─── Create Virtual Environment ───
if exist ".venv\Scripts\activate.bat" (
    echo [INFO]  Virtual environment already exists at .venv\
    echo         Skipping creation. Delete .venv\ to recreate.
) else (
    echo [INFO]  Creating virtual environment...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
    echo [OK]    Virtual environment created at .venv\
)

REM ─── Activate Virtual Environment ───
echo [INFO]  Activating virtual environment...
call .venv\Scripts\activate.bat

REM ─── Upgrade pip ───
echo [INFO]  Upgrading pip...
python -m pip install --upgrade pip --quiet

REM ─── Install Dependencies ───
echo [INFO]  Installing dependencies from requirements.txt...
echo         This may take several minutes (PyTorch, transformers, etc.)
echo.
pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Dependency installation failed.
    echo         Check the error messages above.
    exit /b 1
)

echo.
echo [OK]    All dependencies installed.

REM ─── Create Data Directories ───
echo [INFO]  Creating data directories...
if not exist "data\raw" mkdir "data\raw"
if not exist "data\processed" mkdir "data\processed"
if not exist "data\external" mkdir "data\external"
if not exist "data\results" mkdir "data\results"
if not exist "data\annotations" mkdir "data\annotations"
if not exist "trained_models" mkdir "trained_models"
if not exist "experiments" mkdir "experiments"
echo [OK]    Data directories ready.

REM ─── Verify Installation ───
echo.
echo [INFO]  Verifying installation...
echo.

python -c "from config import config; print(f'  [OK] config        — project root: {config.project_root}')"
if %ERRORLEVEL% NEQ 0 echo   [FAIL] config

python -c "from preprocessing import ImagePreprocessor; print('  [OK] preprocessing — ImagePreprocessor loaded')"
if %ERRORLEVEL% NEQ 0 echo   [FAIL] preprocessing

python -c "from htr import HTRPipeline; print('  [OK] htr           — HTRPipeline loaded')"
if %ERRORLEVEL% NEQ 0 echo   [FAIL] htr

python -c "from evaluation import AnswerEvaluator, Rubric; print('  [OK] evaluation    — AnswerEvaluator loaded')"
if %ERRORLEVEL% NEQ 0 echo   [FAIL] evaluation

python -c "from features import extract_features; print('  [OK] features      — extract_features loaded')"
if %ERRORLEVEL% NEQ 0 echo   [FAIL] features

python -c "from models import GradingRiskModel; print('  [OK] models        — GradingRiskModel loaded')"
if %ERRORLEVEL% NEQ 0 echo   [FAIL] models

python -c "import torch; print(f'  [OK] torch         — version {torch.__version__}')"
if %ERRORLEVEL% NEQ 0 echo   [FAIL] torch

python -c "import sklearn; print(f'  [OK] scikit-learn  — version {sklearn.__version__}')"
if %ERRORLEVEL% NEQ 0 echo   [FAIL] scikit-learn

python -c "import cv2; print(f'  [OK] opencv        — version {cv2.__version__}')"
if %ERRORLEVEL% NEQ 0 echo   [FAIL] opencv

python -c "import fastapi; print(f'  [OK] fastapi       — version {fastapi.__version__}')"
if %ERRORLEVEL% NEQ 0 echo   [FAIL] fastapi

REM ─── Check Assets ───
echo.
echo [INFO]  Checking project assets...
echo.
python scripts\download_assets.py --check

REM ─── Done ───
echo.
echo ============================================================
echo   Setup Complete!
echo ============================================================
echo.
echo   To activate the environment in future sessions:
echo.
echo       .venv\Scripts\activate
echo.
echo   Quick start commands:
echo.
echo       python run_demo.py --help              # Run demo
echo       python train_risk_model.py --compare    # Train models
echo       uvicorn api.app:app --reload            # Start API server
echo       cd notebooks ^& jupyter notebook        # Open notebooks
echo.
echo   First-time asset setup (generate test images + download AI models):
echo.
echo       python scripts\download_assets.py
echo.
echo ============================================================
