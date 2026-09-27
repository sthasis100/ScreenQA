"""
logging_setup.py - writes a log file so problems can be diagnosed later.

Log file:  %APPDATA%\\ScreenQA\\logs\\screenqa.log

Rules for everything we log in this project:
  * NEVER log API keys.
  * Log what happened and why it failed, not the private contents of your screen.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from screenqa.paths import logs_dir

# Each log line looks like:
# 2026-09-27 14:03:11,512 | INFO     | screenqa.app | Starting ScreenQA 0.1.0
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# Libraries that are very chatty; we only want their warnings and errors.
NOISY_LIBRARIES = ("httpx", "httpx2", "httpcore", "httpcore2", "anthropic", "openai", "google_genai")


def setup_logging(level: int = logging.INFO) -> Path:
    """Send log messages to a file (and to the console when there is one).

    Returns the path of the log file so the app can show it to the user.
    """
    log_file = logs_dir() / "screenqa.log"

    # The "root" logger is the parent of every other logger in the program.
    root = logging.getLogger()
    root.setLevel(level)

    # If setup_logging() is ever called twice, remove the old handlers first,
    # otherwise every line would be written twice.
    for old_handler in list(root.handlers):
        root.removeHandler(old_handler)
        old_handler.close()

    formatter = logging.Formatter(LOG_FORMAT)

    # RotatingFileHandler: when the file reaches ~1 MB it is renamed to
    # screenqa.log.1 and a fresh file starts. At most 3 old files are kept,
    # so logs can never fill up your disk.
    file_handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # A packaged windowed .exe has no console, and then sys.stderr is None.
    # Only add the console handler when a console actually exists.
    if sys.stderr is not None:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    for name in NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Any crash that nobody catches goes through sys.excepthook.
    # We replace it so crashes are written to the log file instead of vanishing.
    sys.excepthook = _log_uncaught_exception

    return log_file


def _log_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:
    """Write an uncaught exception (with its full traceback) to the log."""
    # Ctrl+C in the console is not a crash; let Python handle it normally.
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.getLogger("screenqa.crash").critical(
        "Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback)
    )
