import pytest

from apartment_data.config import load_settings
from apartment_data.storage.db import DatabaseConfigError, connect


def test_malformed_url_error_does_not_leak_the_password(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:Secret123%@localhost:5432/db")
    with pytest.raises(DatabaseConfigError) as info:
        connect(load_settings())
    assert "Secret123" not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


def test_missing_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(DatabaseConfigError, match="not set"):
        connect(load_settings())
