"""
OPTIONAL tests that use your REAL API key and send a few tiny requests.

They are skipped unless you ask for them:
    $env:SCREENQA_LIVE_TESTS = "1"; python -m pytest -m live -v
"""

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

from screenqa import analyzer
from screenqa.providers import PROVIDERS
from screenqa.settings import load_settings

pytestmark = pytest.mark.live  # every test in this file is "live"

REAL_DATA = Path(os.environ["APPDATA"]) / "ScreenQA"  # your real folder (tests normally use a temporary one)


@pytest.fixture
def real_service(monkeypatch):
    """Your chosen service and key, read from your real settings (read-only)."""
    monkeypatch.setenv("SCREENQA_DATA_DIR", str(REAL_DATA))
    settings = load_settings()
    key = dotenv_values(REAL_DATA / ".env").get(settings.provider.key_env_var)
    if not key:
        pytest.skip(f"no {settings.provider.label} key saved")
    return settings, key


def test_real_ai_answers_a_calculation(real_service, monkeypatch):
    settings, key = real_service
    from screenqa import ai_client

    real_ask = ai_client.ask
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: real_ask(*a, **{**k, "api_key": key}))
    result = analyzer.analyze("A car travels 150 km in 2.5 hours. What is its average speed in km/h?", None,
                              provider=settings.provider, model=settings.model_name,
                              max_tokens=settings.effective_max_tokens())
    assert "60" in result.final_answer
    assert result.question_type == "calculation" and result.parsed_ok


def test_all_providers_are_known():
    assert {"groq", "gemini", "anthropic"} <= set(PROVIDERS)
