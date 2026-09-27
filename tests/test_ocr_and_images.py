"""Tests for ocr_local.py (Windows' own OCR) and imaging.py."""

import sys

import pytest
from PySide6.QtGui import QColor, QImage

from screenqa import ocr_local
from screenqa.imaging import looks_blank, to_png_bytes
from screenqa.ocr_local import OcrError, OcrLine, lines_to_text, read_text
from tests.helpers import MCQ_LINES, solid_image, text_image


# ---------- OCR ----------

def test_reads_a_multiple_choice_question(qapp):
    result = read_text(text_image(MCQ_LINES))
    assert "LIFO" in result.text and "B. Stack" in result.text
    assert result.line_count == 5


def test_reads_dark_mode_text(qapp):
    assert "B. Stack" in read_text(text_image(MCQ_LINES, dark=True)).text


def test_code_indentation_is_rebuilt(qapp):
    code = ["def total(items):", "    result = 0", "    for x in items:", "        if x > 10:",
            "            result += x", "    return result"]
    lines = read_text(text_image(code, mono=True)).text.splitlines()
    assert [len(line) - len(line.lstrip()) for line in lines] == [0, 4, 4, 8, 12, 4]


def test_blank_picture_gives_no_text(qapp):
    assert read_text(solid_image()).text == ""


def test_tiny_picture_is_refused(qapp):
    with pytest.raises(OcrError, match="too small"):
        read_text(solid_image(width=2, height=2))


def test_huge_picture_is_shrunk_to_fit(qapp):
    big = text_image(MCQ_LINES, px=60).scaled(12000, 1500)  # wider than Windows OCR's 10000 px limit
    assert read_text(big).line_count >= 3


def test_paragraph_gaps():
    lines = [OcrLine("First", 10, 0, 20, 10), OcrLine("Second", 10, 30, 20, 10),
             OcrLine("New paragraph", 10, 90, 20, 10)]
    assert lines_to_text(lines).split("\n") == ["First", "Second", "", "New paragraph"]


def test_missing_ocr_package_message(qapp, monkeypatch):
    monkeypatch.setitem(sys.modules, "winrt.windows.media.ocr", None)  # pretend it isn't installed
    with pytest.raises(OcrError, match="OCR components are missing"):
        read_text(text_image(["x"]))


def test_missing_ocr_language_message(qapp, monkeypatch):
    class NoLanguage:
        max_image_dimension = 10000

        @staticmethod
        def try_create_from_user_profile_languages():
            return None

    real = ocr_local._load_windows_ocr
    monkeypatch.setattr(ocr_local, "_load_windows_ocr", lambda: {**real(), "OcrEngine": NoLanguage})
    with pytest.raises(OcrError, match="not installed for your Windows display language"):
        read_text(text_image(["x"]))


# ---------- blank detection and PNG ----------

@pytest.mark.parametrize("color", ["black", "white", "#fdfdfd"])
def test_single_colour_is_blank(qapp, color):
    assert looks_blank(solid_image(color, 1920, 1200))


def test_one_thin_line_is_not_blank(qapp):
    image = solid_image("white", 400, 150)
    for x in range(50, 350):
        image.setPixelColor(x, 75, QColor("black"))
    assert not looks_blank(image)


def test_one_different_pixel_in_the_corner_is_not_blank(qapp):
    image = solid_image("black", 333, 200)  # odd width: rows have padding bytes
    image.setPixelColor(332, 199, QColor("white"))
    assert not looks_blank(image)


def test_png_is_shrunk_to_the_limit(qapp):
    png = to_png_bytes(solid_image("white", 4000, 1000), max_side=2000)
    decoded = QImage.fromData(png, "PNG")
    assert (decoded.width(), decoded.height()) == (2000, 500)
