"""
End-to-end tests (Step 18): the whole program working together.

  shortcut -> screen frozen -> drag -> real Windows OCR -> Ask AI -> answer -> history

Only two things are pretend: the "screen" (a picture with a question drawn on
it, so your real screen is never captured) and the AI service (the fake server).
"""

import ctypes
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QMouseEvent, QPainter, QPixmap, QScreen

from screenqa import api_keys, hotkey as hk, providers
from screenqa import region_selector
from screenqa.history import HistoryStore
from screenqa.main_window import MainWindow
from screenqa.settings import Settings
from tests.fake_ai_server import reply
from tests.helpers import MCQ_LINES, pump, wait_for_background

PROJECT = Path(__file__).resolve().parent.parent
TEST_SHORTCUT = "Ctrl+Alt+Shift+F10"
ANSWER = {"question_type": "multiple_choice", "working": "LIFO means stack.", "final_answer": "B. Stack",
          "choice_letters": "b", "explanation": "A stack removes the most recently added item first.",
          "other_choices": [{"choice": "A. Queue", "why_wrong": "First In, First Out."}], "steps": [],
          "check": "Compared each option with the LIFO definition.", "assumptions": [],
          "confidence": "high", "confidence_reason": "Standard definition."}


def fake_screen(screen: QScreen) -> QPixmap:
    """A pretend screenshot of the whole monitor, with the question at (100, 100) logical px."""
    ratio = screen.devicePixelRatio()
    picture = QPixmap(round(screen.geometry().width() * ratio), round(screen.geometry().height() * ratio))
    picture.fill(QColor("white"))
    painter = QPainter(picture)
    font = QFont("Segoe UI")
    font.setPixelSize(round(15 * ratio))
    painter.setFont(font)
    painter.setPen(QColor("black"))
    for number, line in enumerate(MCQ_LINES):
        painter.drawText(round(110 * ratio), round((125 + number * 24) * ratio), line)
    painter.end()
    return picture


def test_shortcut_to_answer_to_history(qapp, fake_ai, monkeypatch):
    # The AI service is the fake one; ScreenQA's settings still say "groq".
    monkeypatch.setitem(providers.PROVIDERS, "groq", fake_ai.provider)
    api_keys.save_api_key("GROQ_API_KEY", "gsk_fake_end_to_end")
    fake_ai.respond(reply(json.dumps(ANSWER)))
    # The "screen" is our picture, and overlays aren't really shown full-screen.
    monkeypatch.setattr(QScreen, "grabWindow", lambda screen, window_id=0: fake_screen(screen))
    monkeypatch.setattr(region_selector.RegionOverlay, "showFullScreen", lambda self: None)

    window = MainWindow(history=HistoryStore(), settings=Settings())
    monkeypatch.setattr(window, "_confirm_sending", lambda provider, what: True)
    window.show()
    shortcut = hk.GlobalHotkey()
    window.attach_hotkey(shortcut, TEST_SHORTCUT)
    try:
        # 1. Press the shortcut (the same message Windows sends).
        ctypes.windll.user32.PostThreadMessageW(ctypes.windll.kernel32.GetCurrentThreadId(),
                                                hk.WM_HOTKEY, hk.HOTKEY_ID, 0)
        pump(qapp, 0.6)
        assert not window.isVisible() and window._selector is not None

        # 2. Drag a rectangle around the question on the frozen screen.
        overlay = window._selector._overlays[0]
        for kind, (x, y) in ((QEvent.Type.MouseButtonPress, (100, 100)), (QEvent.Type.MouseMove, (700, 245)),
                             (QEvent.Type.MouseButtonRelease, (700, 245))):
            buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
            overlay.event(QMouseEvent(kind, QPointF(x, y), QPointF(x, y), Qt.MouseButton.LeftButton, buttons,
                                      Qt.KeyboardModifier.NoModifier))
        wait_for_background(qapp)
        assert window.isVisible()
        assert "B. Stack" in window.question_edit.toPlainText()  # real OCR read the fake screen

        # 3. Ask the AI.
        window.ask_button.click()
        wait_for_background(qapp)
        request = fake_ai.requests[0]
        assert request["response_format"] == {"type": "json_object"}  # structured answer requested
        assert request["max_tokens"] == 900  # Groq free-plan limit
        assert "careful tutor" in request["messages"][0]["content"]  # our instructions
        assert request["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png")

        # 4. The answer is shown, the privacy label is back to green, and it's saved.
        assert window.current_analysis.final_answer == "B. Stack"
        assert "Multiple choice" in window.answer_view.toPlainText()
        assert "Local only" in window.privacy_label.text()
        assert window.history.count() == 1
        window.copy_all_button.click()
        assert QGuiApplication.clipboard().text().startswith("Answer: B. Stack")
    finally:
        shortcut.unregister()
        window.close()


# ---------- starting and stopping the real program ----------

LAUNCHER = textwrap.dedent("""
    import sys
    sys.path.insert(0, {project!r})
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    import screenqa.app as app_module
    import screenqa.main_window as mw
    original = mw.MainWindow.__init__
    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        QTimer.singleShot({seconds} * 1000, QApplication.instance().quit)  # close by itself
    mw.MainWindow.__init__ = init
    sys.exit(app_module.main())
""")


def launch(seconds: float, environment: dict) -> subprocess.Popen:
    code = LAUNCHER.format(project=str(PROJECT), seconds=seconds)
    return subprocess.Popen([sys.executable, "-c", code], env=environment)


def test_starts_and_closes_cleanly_and_only_once(isolated_data):
    import os

    environment = {**os.environ, "SCREENQA_DATA_DIR": str(isolated_data)}
    first = launch(6, environment)
    time.sleep(3)  # let the first copy finish starting
    started = time.time()
    second = launch(6, environment)
    assert second.wait(timeout=30) == 0
    assert time.time() - started < 5  # the second copy stepped aside straight away
    assert first.wait(timeout=30) == 0
    log = (isolated_data / "logs" / "screenqa.log").read_text(encoding="utf-8")
    assert "ScreenQA is already running" in log
    assert log.count("Global shortcut active") == 1  # only ONE copy took the shortcut
    assert "Global shortcut released" in log and "ScreenQA closed (exit code 0)" in log
