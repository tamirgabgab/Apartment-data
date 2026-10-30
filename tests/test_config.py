from pathlib import Path

from apartment_data.config import REPO_ROOT, load_settings


def test_defaults_point_inside_repo(monkeypatch):
    for key in ("DATABASE_URL", "RAW_DATA_DIR", "WEB_DATA_DIR", "REQUEST_DELAY_SECONDS"):
        monkeypatch.delenv(key, raising=False)

    settings = load_settings()

    assert settings.database_url is None
    assert settings.raw_data_dir == REPO_ROOT / "data" / "raw"
    assert settings.web_data_dir == REPO_ROOT / "web" / "data"
    assert settings.request_delay_seconds == 1.0


def test_environment_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REQUEST_DELAY_SECONDS", "2.5")

    settings = load_settings()

    assert settings.database_url == "postgresql://example"
    assert settings.raw_data_dir == Path(tmp_path)
    assert settings.request_delay_seconds == 2.5
