"""Project-wide configuration for EvaliSense.

Centralises paths, model names, and tuneable parameters so that no module
needs to hardcode values.  Every setting can be overridden via environment
variables prefixed with ``EVALISENSE_``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _project_root() -> Path:
    """Return the repository root (directory containing this file)."""
    return Path(__file__).resolve().parent


@dataclass
class Config:
    """Top-level application configuration."""

    # ---------- paths ----------
    project_root: Path = field(default_factory=_project_root)
    data_dir: Path = field(default=None)          # type: ignore[assignment]
    raw_dir: Path = field(default=None)            # type: ignore[assignment]
    processed_dir: Path = field(default=None)      # type: ignore[assignment]
    samples_dir: Path = field(default=None)        # type: ignore[assignment]
    annotations_dir: Path = field(default=None)    # type: ignore[assignment]
    results_dir: Path = field(default=None)        # type: ignore[assignment]
    models_dir: Path = field(default=None)         # type: ignore[assignment]
    experiments_dir: Path = field(default=None)     # type: ignore[assignment]
    storage_dir: Path = field(default=None)         # type: ignore[assignment]
    db_path: Path = field(default=None)             # type: ignore[assignment]

    # ---------- authentication & security ----------
    jwt_secret: str = "evalisense_secret_key_change_in_production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # ---------- HTR ----------
    htr_model_name: str = "microsoft/trocr-base-handwritten"
    htr_device: str | None = None  # auto-detect

    # ---------- evaluation ----------
    embedding_model_name: str = "all-MiniLM-L6-v2"
    similarity_threshold: float = 0.55

    # ---------- risk prediction ----------
    grading_error_threshold: float = 2.0  # marks
    risk_model_path: Path = field(default=None)     # type: ignore[assignment]

    # ---------- server ----------
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    debug: bool = False

    # ---------- logging ----------
    log_level: str = "INFO"
    log_file: str | None = None

    def __post_init__(self) -> None:
        root = self.project_root

        # Derive defaults from project root
        if self.data_dir is None:
            self.data_dir = root / "data"
        if self.raw_dir is None:
            self.raw_dir = self.data_dir / "raw"
        if self.processed_dir is None:
            self.processed_dir = self.data_dir / "processed"
        if self.samples_dir is None:
            self.samples_dir = self.data_dir / "samples"
        if self.annotations_dir is None:
            self.annotations_dir = self.data_dir / "annotations"
        if self.results_dir is None:
            self.results_dir = self.data_dir / "results"
        if self.models_dir is None:
            self.models_dir = root / "trained_models"
        if self.experiments_dir is None:
            self.experiments_dir = root / "experiments"
        if self.storage_dir is None:
            self.storage_dir = self.data_dir / "storage"
        if self.db_path is None:
            self.db_path = self.data_dir / "evalisense.db"
        if self.risk_model_path is None:
            self.risk_model_path = self.models_dir / "risk_model.joblib"

        # Apply environment-variable overrides
        self._apply_env()

    def _apply_env(self) -> None:
        """Override fields from ``EVALISENSE_*`` environment variables."""
        prefix = "EVALISENSE_"
        mapping = {
            "HTR_MODEL_NAME": "htr_model_name",
            "HTR_DEVICE": "htr_device",
            "EMBEDDING_MODEL": "embedding_model_name",
            "SIMILARITY_THRESHOLD": "similarity_threshold",
            "ERROR_THRESHOLD": "grading_error_threshold",
            "API_HOST": "api_host",
            "API_PORT": "api_port",
            "DEBUG": "debug",
            "LOG_LEVEL": "log_level",
            "LOG_FILE": "log_file",
            "DB_PATH": "db_path",
            "STORAGE_DIR": "storage_dir",
            "JWT_SECRET": "jwt_secret",
            "JWT_ALGORITHM": "jwt_algorithm",
            "JWT_EXPIRE_MINUTES": "jwt_expire_minutes",
        }
        for env_suffix, attr in mapping.items():
            value = os.environ.get(f"{prefix}{env_suffix}")
            if value is not None:
                current = getattr(self, attr)
                if isinstance(current, bool):
                    setattr(self, attr, value.lower() in ("1", "true", "yes"))
                elif isinstance(current, int):
                    setattr(self, attr, int(value))
                elif isinstance(current, float):
                    setattr(self, attr, float(value))
                elif isinstance(current, Path):
                    setattr(self, attr, Path(value))
                else:
                    setattr(self, attr, value)

    def ensure_dirs(self) -> None:
        """Create all data directories if they do not already exist."""
        for d in (
            self.data_dir,
            self.raw_dir,
            self.processed_dir,
            self.samples_dir,
            self.annotations_dir,
            self.results_dir,
            self.models_dir,
            self.experiments_dir,
            self.storage_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


# Singleton instance — import ``config`` from here.
config = Config()
