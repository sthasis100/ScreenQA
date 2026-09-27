"""
paths.py - decides WHERE ScreenQA stores its files on your computer.

Everything lives in ONE folder:   %APPDATA%\\ScreenQA
(normally C:\\Users\\<you>\\AppData\\Roaming\\ScreenQA)

Why not inside the project folder? After packaging (Step 19) the program may
live somewhere read-only, and your personal data (history, settings, API key)
should never be mixed with program code.
"""

import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "ScreenQA"


def resource_path(relative: str) -> Path:
    """Where files shipped WITH the program (like assets\\icon.png) are.

    While developing, that's the project folder. Inside the packaged .exe
    (Step 19), PyInstaller unpacks them to a folder it names in sys._MEIPASS.
    """
    base = getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent.parent
    return Path(base) / relative


def data_dir() -> Path:
    """Return the ScreenQA data folder, creating it if it does not exist yet."""
    # Tests (Step 17) set SCREENQA_DATA_DIR so they never touch your real data.
    override = os.environ.get("SCREENQA_DATA_DIR")
    if override:
        folder = Path(override)
    else:
        # APPDATA is a standard Windows variable. The fallback (your home folder)
        # only matters on unusual systems where APPDATA is missing.
        appdata = os.environ.get("APPDATA") or str(Path.home())
        folder = Path(appdata) / APP_NAME

    # parents=True: also create missing parent folders.
    # exist_ok=True: do not complain if the folder already exists.
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Very rare (e.g. a locked-down school PC): fall back to the temporary
        # folder so ScreenQA still starts. Data there may be cleaned up by Windows.
        folder = Path(tempfile.gettempdir()) / APP_NAME
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def logs_dir() -> Path:
    """Return the folder that holds log files."""
    folder = data_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def settings_file() -> Path:
    """Your preferences (Step 15). API keys are NOT in here - they're in .env."""
    return data_dir() / "settings.json"


def screenshots_dir() -> Path:
    """Saved screenshots - only used if you switch on 'Save screenshots' in Settings."""
    folder = data_dir() / "screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    return folder
