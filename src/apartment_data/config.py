"""Runtime settings read from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    raw_data_dir: Path
    web_data_dir: Path
    request_delay_seconds: float


def load_settings() -> Settings:
    """Build settings from the environment, with defaults suited for local runs."""
    return Settings(
        database_url=os.environ.get("DATABASE_URL"),
        raw_data_dir=Path(os.environ.get("RAW_DATA_DIR", REPO_ROOT / "data" / "raw")),
        web_data_dir=Path(os.environ.get("WEB_DATA_DIR", REPO_ROOT / "web" / "data")),
        request_delay_seconds=float(os.environ.get("REQUEST_DELAY_SECONDS", "1.0")),
    )
