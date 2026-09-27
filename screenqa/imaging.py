"""
imaging.py - small picture helpers shared by the OCR and AI code.
"""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

from screenqa.paths import screenshots_dir


BLANK_TOLERANCE = 6  # brightness differences smaller than this count as "the same colour"


def looks_blank(image: QImage) -> bool:
    """True if the picture is (almost) one single colour.

    That usually means an empty area, or a window that blocks screenshots
    (video players and secure exam browsers often show up solid black).

    EVERY pixel is checked - checking only a grid of sample points could miss
    one thin line of small text. It is still fast: Python's built-in min() and
    max() go through a whole row at C speed, and we stop at the first row that
    shows any real difference.
    """
    if image.isNull() or image.width() < 2 or image.height() < 2:
        return True
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)  # 1 byte per pixel: 0 black .. 255 white
    pixels = gray.constBits()  # all the bytes, row after row
    row_bytes, width = gray.bytesPerLine(), gray.width()  # rows can have a few padding bytes at the end
    darkest, brightest = 255, 0
    for y in range(gray.height()):
        row = pixels[y * row_bytes: y * row_bytes + width]
        darkest, brightest = min(darkest, min(row)), max(brightest, max(row))
        if brightest - darkest >= BLANK_TOLERANCE:
            return False  # found something that isn't the background
    return True


def save_screenshot(image: QImage) -> Path:
    """Save a captured region as a PNG file (only called if you enabled it in Settings)."""
    path = screenshots_dir() / f"capture-{datetime.now():%Y%m%d-%H%M%S-%f}.png"
    if not image.save(str(path), "PNG"):
        raise OSError(f"Could not write {path}")
    return path


def to_png_bytes(image: QImage, max_side: int | None = None) -> bytes:
    """Encode a picture as PNG bytes.

    PNG is lossless, so letters stay sharp. If max_side is given, a picture
    whose longest side is bigger than that is shrunk first (keeping its shape),
    which makes uploads smaller and faster.
    """
    if max_side and max(image.width(), image.height()) > max_side:
        image = image.scaled(
            max_side, max_side,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    buffer = QBuffer()  # a "file" that lives in memory
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())
