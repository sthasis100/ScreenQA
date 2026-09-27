"""helpers.py - small tools shared by the tests."""

import time

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QColor, QFont, QImage, QPainter


def pump(app, seconds: float = 0.2) -> None:
    """Let Qt handle events (signals, timers, repaints) for a short while."""
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_for_background(app, timeout_ms: int = 15000) -> None:
    """Wait for all background jobs (OCR, AI) to finish, then deliver their results."""
    QThreadPool.globalInstance().waitForDone(timeout_ms)
    pump(app, 0.2)


def text_image(lines: list[str], px: int = 15, dark: bool = False, mono: bool = False) -> QImage:
    """Draw some text on a picture, like a question on a web page."""
    font = QFont("Consolas" if mono else "Segoe UI")
    font.setPixelSize(px)
    image = QImage(px * 40, int(px * 1.5 * (len(lines) + 1)), QImage.Format.Format_RGB32)
    image.fill(QColor(32, 32, 32) if dark else QColor("white"))
    painter = QPainter(image)
    painter.setFont(font)
    painter.setPen(QColor(225, 225, 225) if dark else QColor(20, 20, 20))
    for number, line in enumerate(lines, start=1):
        painter.drawText(int(px * 0.6), int(px * 1.5 * number), line)
    painter.end()
    return image


def solid_image(color: str = "white", width: int = 400, height: int = 150) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    return image


MCQ_LINES = [
    "Q3. Which data structure uses LIFO (Last In, First Out) ordering?",
    "A. Queue",
    "B. Stack",
    "C. Linked list",
    "D. Binary tree",
]
