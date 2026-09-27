"""
errors.py - one place that turns problems into clear messages (Step 16).

Three safety nets:
  1. show_error():           a friendly dialog with an "Open log folder" button.
  2. install_crash_handler(): if a bug slips through inside a button click,
                              ScreenQA logs it, tells you, and KEEPS RUNNING.
  3. report_startup_error():  if ScreenQA can't even start (e.g. a damaged
                              install), Windows shows a message box. This matters
                              for the .exe (Step 19), which has no console window.

Imports of Qt and of our own modules happen INSIDE the functions, so that even
a broken installation can still show the startup message.
"""

import errno
import logging
import sys
import time
import traceback

log = logging.getLogger(__name__)

CRASH_DIALOG_GAP_SECONDS = 3  # never show more than one crash dialog every 3 seconds
_last_crash_dialog = 0.0


def friendly_message(error: BaseException) -> str:
    """A message a person can act on, for any error."""
    from screenqa.ai_client import AIError
    from screenqa.history import HistoryError
    from screenqa.hotkey import ShortcutError
    from screenqa.ocr_local import OcrError

    if isinstance(error, (AIError, OcrError, HistoryError, ShortcutError)):
        return str(error)  # these were written for people already
    if isinstance(error, OSError):
        if error.errno == errno.ENOSPC:
            return "Your disk is full. Free up some space, then try again."
        if isinstance(error, PermissionError):
            return (f"Windows refused access to a file ({error.filename or error}). "
                    "Close any program that may be using it, then try again.")
        return f"A file or network problem occurred: {error}"
    if isinstance(error, MemoryError):
        return "The computer ran out of memory. Try a smaller screen region."
    return f"Something unexpected went wrong ({type(error).__name__}: {error})."


def show_error(parent, title: str, problem: BaseException | str) -> None:
    """Show a warning dialog with an 'Open log folder' button."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QMessageBox

    from screenqa.paths import logs_dir

    message = problem if isinstance(problem, str) else friendly_message(problem)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(message)
    box.setInformativeText("Technical details are saved in the log file.")
    box.addButton(QMessageBox.StandardButton.Ok)
    open_logs = box.addButton("Open log folder", QMessageBox.ButtonRole.ActionRole)
    box.exec()
    if box.clickedButton() is open_logs:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir())))


def install_crash_handler() -> None:
    """Catch bugs that nobody else caught: log them, tell the user, keep running.

    logging_setup.py already replaced sys.excepthook with a function that writes
    crashes to the log. We wrap THAT function, so logging still happens first.
    """
    write_to_log = sys.excepthook

    def handle(error_type, error, error_traceback) -> None:
        write_to_log(error_type, error, error_traceback)
        if issubclass(error_type, KeyboardInterrupt):
            return
        from PySide6.QtWidgets import QApplication

        global _last_crash_dialog
        app = QApplication.instance()
        # No window system yet, or we just showed one: don't pile up dialogs.
        if app is None or time.monotonic() - _last_crash_dialog < CRASH_DIALOG_GAP_SECONDS:
            return
        _last_crash_dialog = time.monotonic()
        show_error(app.activeWindow(), "Something went wrong",
                   f"{friendly_message(error)}\n\nScreenQA will keep running, but the last action "
                   "may not have finished.")

    sys.excepthook = handle


def report_startup_error(error: BaseException) -> None:
    """ScreenQA failed to start: save the details and show a Windows message box.

    Uses only Python's standard library, because Qt itself may be what's broken.
    """
    details = "".join(traceback.format_exception(error))
    location = "the ScreenQA logs folder"
    try:
        from screenqa.paths import logs_dir

        report = logs_dir() / "startup-error.log"
        report.write_text(details, encoding="utf-8")
        location = str(report)
    except Exception:  # even the log folder may be unavailable - then just show the box
        pass
    try:
        import ctypes

        MB_ICONERROR = 0x10
        ctypes.windll.user32.MessageBoxW(
            None, f"ScreenQA could not start:\n\n{error}\n\nDetails were saved to:\n{location}",
            "ScreenQA", MB_ICONERROR)
    except Exception:
        print(details, file=sys.stderr)  # last resort: print it
