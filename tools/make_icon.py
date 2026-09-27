"""
make_icon.py - draws ScreenQA's icon and saves it as assets\\icon.png and assets\\icon.ico (Step 18).

Run once from the project folder:   python tools\\make_icon.py
The icon: a blue rounded square with white "selection corners" (like dragging
a rectangle on the screen) around a question mark.
"""

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication

SIZE = 256
ASSETS = Path(__file__).resolve().parent.parent / "assets"


def draw_icon() -> QImage:
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)  # smooth edges

    # Background: rounded square with a blue gradient.
    gradient = QLinearGradient(0, 0, SIZE, SIZE)
    gradient.setColorAt(0, QColor("#1e88e5"))
    gradient.setColorAt(1, QColor("#0d47a1"))
    background = QPainterPath()
    background.addRoundedRect(QRectF(8, 8, SIZE - 16, SIZE - 16), 48, 48)
    painter.fillPath(background, gradient)

    # Four white "selection corners".
    painter.setPen(QPen(QColor("white"), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    near, far, arm = 52, SIZE - 52, 40
    for x, y, dx, dy in ((near, near, 1, 1), (far, near, -1, 1), (near, far, 1, -1), (far, far, -1, -1)):
        painter.drawLine(x, y, x + dx * arm, y)
        painter.drawLine(x, y, x, y + dy * arm)

    # A bold question mark in the middle.
    font = QFont("Segoe UI", 1, QFont.Weight.Black)
    font.setPixelSize(120)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(QRectF(0, 0, SIZE, SIZE), Qt.AlignmentFlag.AlignCenter, "?")
    painter.end()
    return image


if __name__ == "__main__":
    app = QApplication(sys.argv)  # needed for fonts
    ASSETS.mkdir(exist_ok=True)
    icon = draw_icon()
    icon.save(str(ASSETS / "icon.png"))
    icon.save(str(ASSETS / "icon.ico"))  # the .exe's icon (Step 19)
    print(f"Saved {ASSETS / 'icon.png'} and {ASSETS / 'icon.ico'}")
