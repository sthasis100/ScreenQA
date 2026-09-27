"""
app.py - starts the program: logging first, then Qt, then the main window.
"""

import ctypes
import hashlib
import logging
import os
import sys
from ctypes import wintypes

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from screenqa import __version__, errors
from screenqa.history import HistoryStore
from screenqa.hotkey import GlobalHotkey
from screenqa.logging_setup import setup_logging
from screenqa.main_window import WINDOW_TITLE, MainWindow
from screenqa.paths import data_dir, resource_path
from screenqa.settings import load_settings

log = logging.getLogger(__name__)

SHUTDOWN_WAIT_MS = 2000  # at exit, wait at most 2 seconds for background jobs
ERROR_ALREADY_EXISTS = 183
_instance_lock = None  # kept for the program's whole life (see _another_copy_is_running)


def main() -> int:
    """Start ScreenQA and return its exit code when the window closes."""
    # 1. Logging first, so that even a failure during startup gets recorded.
    log_file = setup_logging()
    log.info("Starting ScreenQA %s (Python %s)", __version__, sys.version.split()[0])
    log.info("Log file: %s", log_file)

    # 2. Only one ScreenQA at a time (Step 18): two copies would fight over the
    #    keyboard shortcut and the history file. A second launch just brings
    #    the first window to the front.
    if _another_copy_is_running():
        log.info("ScreenQA is already running - showing that window instead")
        if not _bring_existing_window_to_front():
            _app = QApplication(sys.argv)  # a message box needs a QApplication
            QMessageBox.information(None, "ScreenQA", "ScreenQA is already running. "
                                    "Look for its window or its button on the taskbar.")
        return 0

    # 3. Every Qt program needs exactly ONE QApplication. It talks to Windows,
    #    receives mouse/keyboard events and delivers them to our widgets.
    _use_own_taskbar_icon()
    app = QApplication(sys.argv)
    app.setApplicationName("ScreenQA")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(str(resource_path("assets/icon.png"))))
    app.setFont(QFont("Segoe UI", 10))  # slightly larger than the Windows default, easier to read
    errors.install_crash_handler()  # Step 16: unexpected bugs -> log + friendly message, keep running

    # 4. Create and show the main window, with your settings (Step 15) and the
    #    saved-questions database (Step 14).
    settings = load_settings()
    window = MainWindow(history=HistoryStore(), settings=settings)
    window.show()

    # 5. The global keyboard shortcut (Step 13). Created once, here, for the
    #    whole program. aboutToQuit fires just before the program closes.
    hotkey = GlobalHotkey(window)
    window.attach_hotkey(hotkey, settings.shortcut)
    app.aboutToQuit.connect(hotkey.unregister)

    # 6. app.exec() starts the "event loop": Qt now waits for clicks and key
    #    presses and calls our code when they happen. This line only returns
    #    after the last window is closed.
    exit_code = app.exec()

    # 7. A background job (e.g. an AI request) may still be running. Give it a
    #    moment to finish, but never keep an invisible ScreenQA alive for minutes.
    if not QThreadPool.globalInstance().waitForDone(SHUTDOWN_WAIT_MS):
        log.warning("A background task was still running at exit; closing anyway")
        log.info("ScreenQA closed (exit code %s)", exit_code)
        logging.shutdown()  # make sure everything is written to the log file first
        os._exit(exit_code)  # end the process right now, without waiting for that task
    log.info("ScreenQA closed (exit code %s)", exit_code)
    return exit_code


def _another_copy_is_running() -> bool:
    """Ask Windows for a named 'mutex' (a lock that only one program can create).

    If it already exists, another ScreenQA made it. The name includes the data
    folder, so copies with separate data (like the automated tests) don't clash.
    Windows removes the lock automatically when ScreenQA closes.
    """
    global _instance_lock
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    folder_id = hashlib.sha1(str(data_dir()).lower().encode()).hexdigest()[:12]
    _instance_lock = kernel32.CreateMutexW(None, False, f"Local\\ScreenQA-{folder_id}")
    return ctypes.get_last_error() == ERROR_ALREADY_EXISTS


def _bring_existing_window_to_front() -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    window = user32.FindWindowW(None, WINDOW_TITLE)  # find it by its title bar text
    if not window:
        return False
    SW_RESTORE = 9  # un-minimise if needed
    user32.ShowWindow(window, SW_RESTORE)
    user32.SetForegroundWindow(window)
    return True


def _use_own_taskbar_icon() -> None:
    """Without this, Windows groups ScreenQA with Python and shows Python's icon."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ScreenQA.ScreenQuestionAssistant")
    except (AttributeError, OSError):
        pass  # purely cosmetic
