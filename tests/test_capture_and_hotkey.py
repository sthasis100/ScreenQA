"""Tests for region_selector.py (dragging a rectangle) and hotkey.py (global shortcut)."""

import ctypes
import subprocess
import sys

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPixmap

from screenqa import hotkey as hk
from screenqa.region_selector import RegionOverlay
from tests.helpers import pump

# An unusual combination, so the tests never clash with a running ScreenQA.
TEST_SHORTCUT = "Ctrl+Alt+Shift+F11"


# ---------- dragging a rectangle ----------

def mouse(widget, kind, x, y, button=Qt.MouseButton.LeftButton):
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
    widget.event(QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, buttons, Qt.KeyboardModifier.NoModifier))


def drag(overlay, start, end):
    mouse(overlay, QEvent.Type.MouseButtonPress, *start)
    mouse(overlay, QEvent.Type.MouseMove, *end)
    mouse(overlay, QEvent.Type.MouseButtonRelease, *end)


@pytest.fixture(params=[1.0, 2.0], ids=["100% scaling", "200% scaling"])
def overlay(qapp, request):
    """An overlay over a FAKE frozen screen with a red box at a known place."""
    screen = qapp.primaryScreen()
    ratio = request.param
    geometry = screen.geometry()
    frozen = QPixmap(round(geometry.width() * ratio), round(geometry.height() * ratio))
    frozen.fill(QColor("white"))
    painter = QPainter(frozen)
    painter.fillRect(round(100 * ratio), round(100 * ratio), round(200 * ratio), round(100 * ratio), QColor("red"))
    painter.end()
    widget = RegionOverlay(screen, frozen)
    widget.results = []
    widget.selected.connect(widget.results.append)
    widget.ratio = ratio
    return widget


def test_selection_is_cut_at_the_right_place_and_size(overlay):
    drag(overlay, (100, 100), (300, 200))
    image = overlay.results[0]
    assert (image.width(), image.height()) == (round(200 * overlay.ratio), round(100 * overlay.ratio))
    corners = [(0, 0), (image.width() - 1, 0), (0, image.height() - 1), (image.width() - 1, image.height() - 1)]
    assert all(image.pixelColor(x, y) == QColor("red") for x, y in corners)


def test_dragging_backwards_gives_the_same_result(overlay):
    drag(overlay, (300, 200), (100, 100))
    assert overlay.results[0].width() == round(200 * overlay.ratio)


def test_a_click_is_not_a_selection(overlay):
    drag(overlay, (500, 500), (503, 502))
    assert overlay.results == []


def test_escape_cancels(overlay):
    cancelled = []
    overlay.cancelled.connect(lambda: cancelled.append(True))
    overlay.event(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert cancelled == [True]


# ---------- the global shortcut ----------

@pytest.mark.parametrize("text, expected", [
    ("Ctrl+Shift+Space", (0x2 | 0x4, 0x20)),
    ("alt+f9", (0x1, 0x78)),
    ("Meta+Shift+2", (0x8 | 0x4, ord("2"))),   # Qt calls the Windows key "Meta"
    ("Ctrl+PgUp", (0x2, 0x21)),
])
def test_parse_shortcut(text, expected):
    assert hk.parse_shortcut(text) == expected


@pytest.mark.parametrize("bad", ["Shift+A", "Ctrl+Banana", "Hyper+X", ""])
def test_bad_shortcuts_are_refused(bad):
    with pytest.raises(hk.ShortcutError):
        hk.parse_shortcut(bad)


@pytest.fixture
def hotkey(qapp):
    key = hk.GlobalHotkey()
    key.presses = []
    key.activated.connect(lambda: key.presses.append(True))
    yield key
    key.unregister()


def test_windows_message_triggers_the_shortcut(qapp, hotkey):
    assert hotkey.register(TEST_SHORTCUT) is None
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.PostThreadMessageW(kernel32.GetCurrentThreadId(), hk.WM_HOTKEY, hk.HOTKEY_ID, 0)
    pump(qapp, 0.3)
    assert hotkey.presses == [True]


def test_real_key_press_triggers_the_shortcut(qapp, hotkey):
    assert hotkey.register(TEST_SHORTCUT) is None
    keys = [0x11, 0x12, 0x10, 0x7A]  # Ctrl, Alt, Shift, F11
    try:
        for key in keys:
            ctypes.windll.user32.keybd_event(key, 0, 0, 0)
    finally:  # always release, so no key stays "held down"
        for key in reversed(keys):
            ctypes.windll.user32.keybd_event(key, 0, 2, 0)
    pump(qapp, 0.5)
    assert hotkey.presses == [True]


def test_shortcut_taken_by_another_program(qapp, hotkey):
    code = ("import ctypes,time; print(ctypes.windll.user32.RegisterHotKey(None,1,0x4007,0x7A), flush=True);"
            "time.sleep(3)")
    other = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert other.stdout.readline().strip() == "1"  # the other program got it first
        assert "already used by another program" in hotkey.register(TEST_SHORTCUT)
    finally:
        other.wait()
    assert hotkey.register(TEST_SHORTCUT) is None  # free again once it closed
