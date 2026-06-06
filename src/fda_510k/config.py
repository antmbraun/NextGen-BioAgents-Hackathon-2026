from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_NEBIUS_MODEL = "openai/gpt-oss-120b-fast"
DEFAULT_NEBIUS_BASE_URL = "https://api.tokenfactory.us-central1.nebius.com/v1"

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    nebius_api_key: str = ""
    nebius_model: str = DEFAULT_NEBIUS_MODEL
    nebius_base_url: str = DEFAULT_NEBIUS_BASE_URL

    fda_510k_db_path: Path = PROJECT_ROOT / "storage" / "sqlite" / "510k.db"
    fda_510k_json_path: Path = PROJECT_ROOT / "device-510k-0001-of-0001.json"
    upload_dir: Path = PROJECT_ROOT / "storage" / "uploads"
    output_dir: Path = PROJECT_ROOT / "storage" / "outputs"
    data_dir: Path = PROJECT_ROOT / "data"

    enable_ocr: bool = False
    max_chunks_per_pass: int = 12
    predicate_top_k: int = 5

    draft_watermark: str = "DRAFT — REQUIRES REGULATORY REVIEW"


settings = Settings()


def reload_settings() -> Settings:
    """Re-read settings after Streamlit secrets are injected into the environment."""
    global settings
    settings = Settings()
    return settings


def get_nebius_api_key() -> str:
    return os.environ.get("NEBIUS_API_KEY") or getattr(settings, "nebius_api_key", "")


def get_nebius_model() -> str:
    return os.environ.get("NEBIUS_MODEL") or getattr(settings, "nebius_model", DEFAULT_NEBIUS_MODEL)


def get_nebius_base_url() -> str:
    return os.environ.get("NEBIUS_BASE_URL") or getattr(settings, "nebius_base_url", DEFAULT_NEBIUS_BASE_URL)
