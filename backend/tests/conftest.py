import os

os.environ.setdefault("API_ACCESS_TOKEN", "test-api-token")
os.environ.setdefault("SCHEDULER_SECRET", "test-scheduler-token")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:5173")
os.environ.setdefault("TOSS_INVEST_CLIENT_ID", "")
os.environ.setdefault("TOSS_INVEST_CLIENT_SECRET", "")
os.environ.setdefault("TOSS_INVEST_ACCOUNT_ID", "")

import pytest

from app.config import clear_settings_cache


@pytest.fixture(autouse=True)
def test_environment(monkeypatch):
    monkeypatch.setenv("API_ACCESS_TOKEN", "test-api-token")
    monkeypatch.setenv("SCHEDULER_SECRET", "test-scheduler-token")
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:5173")
    monkeypatch.setenv("TOSS_INVEST_CLIENT_ID", "")
    monkeypatch.setenv("TOSS_INVEST_CLIENT_SECRET", "")
    monkeypatch.setenv("TOSS_INVEST_ACCOUNT_ID", "")
    clear_settings_cache()
    yield
    clear_settings_cache()
