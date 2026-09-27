"""
ocr_local.py - reads text from an image with Windows' built-in OCR (Step 9).

OCR = Optical Character Recognition: turning a PICTURE of text into real TEXT.
Everything in this file runs on YOUR computer. Nothing is sent anywhere.

Good at:   normal sentences, multiple-choice questions, light or dark themes.
Weak at:   equations (x², √, fractions), code symbols, tables, handwriting.
           For those, Step 10 adds "Read with AI Vision".

Test this file on its own with any saved picture:
    python -m screenqa.ocr_local C:\\path\\to\\picture.png
"""

import asyncio
import logging
import statistics
import time
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from screenqa.imaging import to_png_bytes

log = logging.getLogger(__name__)

# Small screen text is recognised more reliably when the picture is enlarged
# (measured for this project: 12 px text went from 98% to 100% correct at 2x).
UPSCALE_FACTOR = 2
UPSCALE_IF_SMALLER_THAN = 2500  # px; larger regions already have big enough text
MAX_INDENT = 40  # never add more than 40 spaces of indentation to a line

NO_LANGUAGE_MESSAGE = (
    "Windows OCR is not installed for your Windows display language.\n\n"
    "To fix it: Settings > Time & language > Language & region > click '...' next "
    "to your language > Language options > install 'Optical character recognition'."
)
MISSING_PACKAGES_MESSAGE = (
    "The Windows OCR components are missing.\n\n"
    "In the project folder, with the virtual environment active, run:\n"
    "python -m pip install -r requirements.txt"
)


class OcrError(Exception):
    """An OCR problem we can explain to the user in plain English."""


@dataclass
class OcrLine:
    """One line of text found by the OCR engine, with its position in pixels."""

    text: str
    left: float  # x position of the line's first word
    top: float  # y position of the line's top edge
    height: float
    char_width: float  # average width of one character in this line


@dataclass
class OcrResult:
    """Everything read_text() found."""

    text: str
    line_count: int
    seconds: float
    language: str  # e.g. "en-US"


def read_text(image: QImage) -> OcrResult:
    """Recognise the text in `image`. Safe to call from a background thread."""
    if image.isNull() or image.width() < 4 or image.height() < 4:
        raise OcrError("The selected region is empty or too small to read.")

    started = time.perf_counter()
    winrt = _load_windows_ocr()
    prepared = _prepare(image, winrt["OcrEngine"].max_image_dimension)
    png_bytes = to_png_bytes(prepared)  # lossless, so no letters get blurred

    try:
        # The Windows OCR functions are "async" (they finish later).
        # asyncio.run() starts them and waits here until they are done.
        lines, language = asyncio.run(_recognize(png_bytes, winrt))
    except OcrError:
        raise  # already a friendly message
    except Exception as error:  # any other Windows error: log details, give a short message
        log.exception("Windows OCR failed")
        raise OcrError(f"Windows OCR failed: {error}") from error

    text = lines_to_text(lines)
    seconds = time.perf_counter() - started
    # Log sizes and timing only - never the text itself (it may be private).
    log.info(
        "OCR: %d line(s), %d characters from a %dx%d px image in %.2f s (%s)",
        len(lines), len(text), image.width(), image.height(), seconds, language,
    )
    return OcrResult(text=text, line_count=len(lines), seconds=seconds, language=language)


def _load_windows_ocr() -> dict:
    """Import the Windows OCR classes. Imported here (not at the top of the file)
    so a missing package gives a clear message instead of crashing the app."""
    try:
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    except ImportError as error:
        raise OcrError(MISSING_PACKAGES_MESSAGE) from error
    return {
        "BitmapDecoder": BitmapDecoder,
        "OcrEngine": OcrEngine,
        "DataWriter": DataWriter,
        "InMemoryRandomAccessStream": InMemoryRandomAccessStream,
    }


def _prepare(image: QImage, max_dimension: int) -> QImage:
    """Resize the picture to the size the OCR engine reads best."""
    longest_side = max(image.width(), image.height())
    scale = UPSCALE_FACTOR if longest_side < UPSCALE_IF_SMALLER_THAN else 1
    # Never go above the biggest picture Windows OCR accepts (usually 10000 px).
    # For a gigantic picture this makes scale smaller than 1, i.e. it shrinks it.
    scale = min(scale, max_dimension / longest_side)
    if scale == 1:
        return image
    return image.scaled(
        round(image.width() * scale),
        round(image.height() * scale),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,  # smooth = less jagged letters
    )


async def _recognize(png_bytes: bytes, winrt: dict) -> tuple[list[OcrLine], str]:
    """Hand the picture to Windows OCR and collect the lines it finds."""
    # 1. Put the PNG bytes into a Windows "stream" (an in-memory file).
    stream = winrt["InMemoryRandomAccessStream"]()
    writer = winrt["DataWriter"](stream)
    writer.write_bytes(png_bytes)
    await writer.store_async()
    writer.detach_stream()  # keep the stream usable after the writer is finished
    stream.seek(0)  # rewind to the beginning before reading

    # 2. Decode the PNG into a SoftwareBitmap - the picture type the OCR engine wants.
    decoder = await winrt["BitmapDecoder"].create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    # 3. Create an OCR engine for the language Windows is using, and run it.
    engine = winrt["OcrEngine"].try_create_from_user_profile_languages()
    if engine is None:
        raise OcrError(NO_LANGUAGE_MESSAGE)
    result = await engine.recognize_async(bitmap)

    # 4. Copy what we need into simple Python objects.
    lines = []
    for line in result.lines:
        words = list(line.words)
        if not words:
            continue
        first = words[0].bounding_rect
        letters = sum(len(word.text) for word in words)
        total_width = sum(word.bounding_rect.width for word in words)
        lines.append(
            OcrLine(
                text=line.text,
                left=first.x,
                top=min(word.bounding_rect.y for word in words),
                height=max(word.bounding_rect.height for word in words),
                char_width=total_width / letters if letters else 0.0,
            )
        )
    return lines, engine.recognizer_language.language_tag


def lines_to_text(lines: list[OcrLine]) -> str:
    """Join OCR lines into text, rebuilding indentation and paragraph gaps.

    Windows OCR returns each line WITHOUT its leading spaces, which ruins code.
    We rebuild them: a line that starts 4 character-widths further right than
    the leftmost line gets 4 spaces in front of it.
    """
    if not lines:
        return ""

    base_left = min(line.left for line in lines)
    widths = [line.char_width for line in lines if line.char_width > 0]
    char_width = statistics.median(widths) if widths else 1.0

    # "Pitch" = distance from one line's top to the next line's top.
    # A gap much bigger than usual means a new paragraph, so we add a blank line.
    # "Usual" = the SMALLEST normal pitch. (The median fails for short texts: with
    # only 3 lines, one big gap is half of all the pitches.) Pitches smaller than
    # most of a line's height are ignored - that's OCR splitting one line in two.
    line_height = statistics.median(line.height for line in lines)
    pitches = [b.top - a.top for a, b in zip(lines, lines[1:]) if b.top - a.top >= 0.8 * line_height]
    normal_pitch = min(pitches) if pitches else 0.0

    output = []
    for index, line in enumerate(lines):
        if index > 0 and normal_pitch > 0:
            if line.top - lines[index - 1].top > 1.5 * normal_pitch:
                output.append("")
        indent = round((line.left - base_left) / char_width)
        output.append(" " * min(max(indent, 0), MAX_INDENT) + line.text)
    return "\n".join(output)


# ----------------------------------------------------------------------
# Run this file directly to test OCR on its own (Step 9 / Step 17).
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python -m screenqa.ocr_local C:\\path\\to\\picture.png")
        sys.exit(2)
    picture = QImage(sys.argv[1])
    if picture.isNull():
        print(f"Could not open the picture: {sys.argv[1]}")
        sys.exit(1)
    try:
        found = read_text(picture)
    except OcrError as problem:
        print(f"OCR problem: {problem}")
        sys.exit(1)
    print(found.text)
    print(f"--- {found.line_count} line(s), {found.seconds:.2f} s, language {found.language}")
