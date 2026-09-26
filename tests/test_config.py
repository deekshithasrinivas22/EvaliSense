"""Tests for the project configuration module."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from config import Config


def test_config_defaults():
    cfg = Config()
    assert cfg.project_root.exists()
    assert cfg.htr_model_name == "microsoft/trocr-base-handwritten"
    assert cfg.grading_error_threshold == 2.0
    assert cfg.api_port == 8000


def test_config_derived_paths():
    cfg = Config()
    assert cfg.data_dir == cfg.project_root / "data"
    assert cfg.raw_dir == cfg.data_dir / "raw"
    assert cfg.processed_dir == cfg.data_dir / "processed"


def test_config_env_override(monkeypatch):
    monkeypatch.setenv("EVALISENSE_API_PORT", "9999")
    monkeypatch.setenv("EVALISENSE_LOG_LEVEL", "DEBUG")
    cfg = Config()
    assert cfg.api_port == 9999
    assert cfg.log_level == "DEBUG"


def test_config_ensure_dirs(tmp_path: Path):
    cfg = Config(project_root=tmp_path)
    cfg.data_dir = tmp_path / "data"
    cfg.raw_dir = cfg.data_dir / "raw"
    cfg.processed_dir = cfg.data_dir / "processed"
    cfg.samples_dir = cfg.data_dir / "samples"
    cfg.annotations_dir = cfg.data_dir / "annotations"
    cfg.results_dir = cfg.data_dir / "results"
    cfg.models_dir = tmp_path / "trained_models"
    cfg.experiments_dir = tmp_path / "experiments"

    cfg.ensure_dirs()
    assert cfg.raw_dir.exists()
    assert cfg.processed_dir.exists()
    assert cfg.models_dir.exists()
