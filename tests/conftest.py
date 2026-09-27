"""
conftest.py - shared setup for every test (pytest loads this file automatically).

A "fixture" is something a test asks for by naming it as a parameter, e.g.
    def test_something(qapp, fake_ai): ...
pytest creates it before the test and cleans it up afterwards.

Run all tests (from the project folder):   python -m pytest
Run one file, showing each test's name:     python -m pytest tests\\test_render.py -v
Also run the tests that use your REAL AI key (a few tiny requests):
    $env:SCREENQA_LIVE_TESTS = "1"; python -m pytest -m live -v
"""

import logging
import os
import sys

import pytest
from PySide6.QtWidgets import QApplication

from tests.fake_ai_server import FakeAIServer

API_KEY_VARIABLES = ("GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "SCREENQA_PROVIDER")


@pytest.fixture(scope="session")
def qapp():
    """The one QApplication every Qt test needs (created once for the whole test run)."""
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)  # autouse = used by EVERY test automatically
def isolated_data(tmp_path, monkeypatch):
    """Give each test its own empty data folder, and hide any API keys set in Windows.

    So tests can never read or change your real settings, history or keys.
    monkeypatch undoes every change when the test ends.
    """
    folder = tmp_path / "screenqa-data"
    monkeypatch.setenv("SCREENQA_DATA_DIR", str(folder))
    for name in API_KEY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return folder


@pytest.fixture(autouse=True)
def restore_global_state():
    """Some tests change process-wide things (crash handler, logging); put them back."""
    saved_hook = sys.excepthook
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    yield
    sys.excepthook = saved_hook
    for handler in list(root.handlers):
        if handler not in saved_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(saved_level)


@pytest.fixture
def fake_ai():
    """A pretend AI service on this PC that answers with whatever we tell it to."""
    server = FakeAIServer()
    yield server
    server.close()


def pytest_collection_modifyitems(config, items):
    """Skip tests marked 'live' unless you asked for them (they use your real API key)."""
    if os.environ.get("SCREENQA_LIVE_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="uses your real AI key - set SCREENQA_LIVE_TESTS=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
