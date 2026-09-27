"""Tests for the main window: the whole flow, with a stand-in AI (no real requests)."""

import errno
import json

import pytest

from screenqa import analyzer, errors
from screenqa import main_window as mw
from screenqa.analyzer import Analysis, parse_analysis
from screenqa.history import HistoryError, HistoryStore
from screenqa.paths import screenshots_dir, settings_file
from screenqa.settings import Settings
from tests.helpers import MCQ_LINES, pump, solid_image, text_image, wait_for_background

REPLY = json.dumps({"question_type": "multiple_choice", "working": "LIFO = stack", "final_answer": "B. Stack",
                    "choice_letters": "b", "explanation": "A stack is Last In, First Out.",
                    "other_choices": [{"choice": "A. Queue", "why_wrong": "FIFO"}], "steps": [],
                    "check": "Definition.", "assumptions": [], "confidence": "high",
                    "confidence_reason": "Textbook fact."})


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    """A main window with its own history, a stand-in AI and captured error dialogs."""
    store = HistoryStore(tmp_path / "history.db")
    win = mw.MainWindow(history=store, settings=Settings())
    win.errors_shown = []
    win.ai_calls = []
    monkeypatch.setattr(errors, "show_error", lambda parent, title, problem: win.errors_shown.append(
        (title, problem if isinstance(problem, str) else errors.friendly_message(problem))))
    monkeypatch.setattr(win, "_confirm_sending", lambda provider, what: True)  # skip the consent dialog

    def fake_analyze(question, image_png, **options):
        win.ai_calls.append({"question": question, "image": image_png is not None, **options})
        result = parse_analysis(REPLY)
        result.provider, result.model = "Groq (free tier)", options["model"]
        return result

    monkeypatch.setattr(analyzer, "analyze", fake_analyze)
    win.show()
    pump(qapp, 0.1)
    yield win
    win.close()


def test_capture_read_ask_show_and_save(qapp, window):
    window.on_region_selected(text_image(MCQ_LINES))  # as if the user dragged over a question
    wait_for_background(qapp)
    assert "B. Stack" in window.question_edit.toPlainText()  # real Windows OCR read it
    assert "Multiple choice (options a-d)" in window.statusBar().currentMessage()

    window.ask_button.click()
    wait_for_background(qapp)
    assert window.current_analysis.final_answer == "B. Stack"
    assert window.ai_calls[0]["image"] is True  # "Send screenshot" is ticked by default
    assert window.ai_calls[0]["max_tokens"] == 900  # Groq's limit from the settings
    assert "Last In, First Out" in window.explanation_view.toPlainText()
    assert window.history.count() == 1  # saved
    assert window.privacy_label.text().strip() == "Local only - nothing is being sent"


def test_untick_screenshot_sends_text_only(qapp, window):
    window.question_edit.setPlainText("What is 7 x 6?")
    window.current_image = solid_image()
    window.attach_image_checkbox.setChecked(False)
    window.ask_button.click()
    wait_for_background(qapp)
    assert window.ai_calls[0]["image"] is False


def test_blank_capture_is_explained(qapp, window):
    jobs_before = window._ocr_job
    window.on_region_selected(solid_image("black"))
    assert window._ocr_job == jobs_before  # no OCR started
    assert "all one colour" in window.question_edit.placeholderText()


def test_ai_failure_shows_a_message_and_unlocks(qapp, window, monkeypatch):
    from screenqa.ai_client import AIError

    monkeypatch.setattr(analyzer, "analyze", lambda *a, **k: (_ for _ in ()).throw(AIError("Could not connect to Groq.")))
    window.question_edit.setPlainText("What is 7 x 6?")
    window.ask_button.click()
    wait_for_background(qapp)
    assert window.errors_shown[-1] == ("AI request failed", "Could not connect to Groq.")
    assert window.ask_button.isEnabled() and window.capture_button.isEnabled()


def test_history_failure_still_shows_the_answer(qapp, window, monkeypatch):
    monkeypatch.setattr(window.history, "add", lambda *a, **k: (_ for _ in ()).throw(HistoryError("disk I/O error")))
    window.question_edit.setPlainText("What is 7 x 6?")
    window.ask_button.click()
    wait_for_background(qapp)
    assert window.current_analysis.final_answer == "B. Stack"
    assert "disk I/O error" in window.statusBar().currentMessage()


def test_copy_buttons(qapp, window):
    from PySide6.QtGui import QGuiApplication

    window._show_analysis(Analysis(question_type="calculation", final_answer="42", explanation="6 x 7.",
                                   confidence="high", parsed_ok=True))
    window.copy_button.click()
    assert QGuiApplication.clipboard().text() == "42"
    window.copy_all_button.click()
    assert QGuiApplication.clipboard().text().startswith("Answer: 42")


def test_history_tab_search_delete_and_clear(qapp, window, monkeypatch):
    for question in ("First question about stacks?", "Second question about queues?"):
        window.question_edit.setPlainText(question)
        window.ask_button.click()
        wait_for_background(qapp)
    window.tabs.setCurrentIndex(1)
    assert window.history_list.count() == 2
    window.history_search.setText("queues")
    assert window.history_list.count() == 1
    window.history_search.clear()
    window.history_list.setCurrentRow(0)
    assert "Last In, First Out" in window.history_detail.toPlainText()
    window.delete_entry_button.click()
    assert window.history.count() == 1
    monkeypatch.setattr(mw.QMessageBox, "question", lambda *a, **k: mw.QMessageBox.StandardButton.Yes)
    window.clear_history_button.click()
    assert window.history.count() == 0


def test_settings_switch_history_and_screenshots(qapp, window):
    window.apply_settings(Settings(save_history=False, save_screenshots=True))
    assert settings_file().exists()
    window.on_region_selected(text_image(MCQ_LINES))
    wait_for_background(qapp)
    assert len(list(screenshots_dir().glob("*.png"))) == 1  # a copy was saved
    window.ask_button.click()
    wait_for_background(qapp)
    assert window.history.count() == 0  # but history is off
    assert window.history_info_label.text().startswith("Saving is OFF")


def test_disk_full_when_saving_screenshot_warns_once(qapp, window, monkeypatch):
    monkeypatch.setattr(mw, "save_screenshot", lambda image: (_ for _ in ()).throw(OSError(errno.ENOSPC, "full")))
    window.settings.save_screenshots = True
    for _ in range(2):
        window.on_region_selected(text_image(MCQ_LINES))
        wait_for_background(qapp)
    titles = [title for title, _ in window.errors_shown]
    assert titles.count("Screenshot copy not saved") == 1


def test_settings_file_cannot_be_written(qapp, window):
    settings_file().mkdir()  # a FOLDER where the file should be
    window.apply_settings(Settings())
    assert window.errors_shown[-1][0] == "Settings not saved"
