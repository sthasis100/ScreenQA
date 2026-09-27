"""Tests for errors.py: friendly messages and the two safety nets."""

import ctypes
import errno

from PySide6.QtWidgets import QPushButton

from screenqa import errors
from screenqa.logging_setup import setup_logging
from tests.helpers import pump


def test_friendly_messages():
    assert errors.friendly_message(OSError(errno.ENOSPC, "No space")) == \
        "Your disk is full. Free up some space, then try again."
    assert errors.friendly_message(PermissionError(13, "Access is denied", "history.db")).startswith(
        "Windows refused access to a file (history.db)")
    assert errors.friendly_message(ValueError("bad")) == "Something unexpected went wrong (ValueError: bad)."


def test_a_bug_in_a_button_is_logged_shown_and_survived(qapp, monkeypatch):
    log_file = setup_logging()
    errors.install_crash_handler()
    shown = []
    monkeypatch.setattr(errors, "show_error", lambda parent, title, problem: shown.append(title))
    monkeypatch.setattr(errors, "_last_crash_dialog", 0.0)

    def buggy():
        raise ZeroDivisionError("division by zero")

    button = QPushButton("buggy")
    button.clicked.connect(buggy)
    button.click()
    pump(qapp, 0.2)
    assert shown == ["Something went wrong"]
    assert "ZeroDivisionError: division by zero" in log_file.read_text(encoding="utf-8")


def test_startup_failure_shows_a_windows_message_and_saves_details(isolated_data, monkeypatch):
    boxes = []
    monkeypatch.setattr(ctypes.windll.user32, "MessageBoxW", lambda hwnd, text, title, flags: boxes.append(text))
    try:
        raise RuntimeError("PySide6 is damaged")
    except RuntimeError as problem:
        errors.report_startup_error(problem)
    assert "ScreenQA could not start" in boxes[0]
    assert "RuntimeError: PySide6 is damaged" in (isolated_data / "logs" / "startup-error.log").read_text()


def test_data_folder_falls_back_to_temp(tmp_path, monkeypatch):
    blocker = tmp_path / "a-file.txt"
    blocker.write_text("x")
    monkeypatch.setenv("SCREENQA_DATA_DIR", str(blocker / "sub"))  # a folder inside a FILE: impossible
    from screenqa.paths import data_dir

    folder = data_dir()
    assert folder.name == "ScreenQA" and "Temp" in str(folder)
