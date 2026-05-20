import os

os.environ.setdefault("API_ACCESS_TOKEN", "test-api-token")
os.environ.setdefault("SCHEDULER_SECRET", "test-scheduler-token")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:5173")

import pytest

from app.config import clear_settings_cache


@pytest.fixture(autouse=True)
def test_environment(monkeypatch):
    monkeypatch.setenv("API_ACCESS_TOKEN", "test-api-token")
    monkeypatch.setenv("SCHEDULER_SECRET", "test-scheduler-token")
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:5173")
    clear_settings_cache()
    yield
    clear_settings_cache()
