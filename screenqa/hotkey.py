"""
hotkey.py - a keyboard shortcut that works anywhere in Windows (Step 13).

How it works:
  1. RegisterHotKey asks WINDOWS to watch for ONE key combination, e.g.
     Ctrl+Shift+Space - even while another program is in front.
  2. When you press it, Windows sends ScreenQA a message called WM_HOTKEY.
  3. Qt receives every Windows message for our program. A "native event
     filter" lets us look at each message first and spot WM_HOTKEY.
  4. We then emit the Qt signal `activated`, and the window starts a capture.

Why not the popular `keyboard` library? It hooks EVERY key you type (the same
technique keyloggers use), and antivirus programs often flag it.
RegisterHotKey only ever tells us about our one combination.
"""

import ctypes
import logging
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, QTimer, Signal

log = logging.getLogger(__name__)

# Not Ctrl+Shift+Q: in Chrome/Firefox that QUITS the browser if ScreenQA isn't running.
DEFAULT_SHORTCUT = "Ctrl+Shift+Space"

WM_HOTKEY = 0x0312  # the Windows message number for "a hotkey was pressed"
HOTKEY_ID = 0x5153  # our own ID for the hotkey (any number from 0 to 0xBFFF)
ERROR_HOTKEY_ALREADY_REGISTERED = 1409
MOD_NOREPEAT = 0x4000  # holding the keys down triggers only once, not over and over

# Modifier keys and the numbers Windows uses for them (they can be added together).
# Qt calls the Windows key "Meta", so both names are accepted.
MODIFIERS = {"ctrl": 0x0002, "control": 0x0002, "alt": 0x0001, "shift": 0x0004, "win": 0x0008, "meta": 0x0008}
# "Virtual-key codes": Windows' number for each key. Some keys have two names
# because Qt's shortcut box (Settings) writes e.g. "PgUp" and "Del".
NAMED_KEYS = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "insert": 0x2D, "ins": 0x2D,
    "delete": 0x2E, "del": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21,
    "pagedown": 0x22, "pgdown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "pause": 0x13,
}

# Load Windows' user32.dll and describe the two functions we call, so ctypes
# passes the right kinds of values (use_last_error lets us read error codes).
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wintypes.BOOL


class ShortcutError(ValueError):
    """The shortcut text isn't something we can register."""


def parse_shortcut(text: str) -> tuple[int, int]:
    """'Ctrl+Shift+Space' -> (modifier flags, key code) for RegisterHotKey."""
    parts = [part.strip().lower() for part in text.split("+") if part.strip()]
    if not parts:
        raise ShortcutError("The shortcut is empty.")
    *modifier_names, key_name = parts

    modifiers = 0
    for name in modifier_names:
        if name not in MODIFIERS:
            raise ShortcutError(f"'{name}' is not a modifier key. Use Ctrl, Alt, Shift or Win.")
        modifiers |= MODIFIERS[name]  # "|=" adds this flag to the others
    # Shift alone is not enough: Shift+A would stop you typing a capital A anywhere!
    if not modifiers & (MODIFIERS["ctrl"] | MODIFIERS["alt"] | MODIFIERS["win"]):
        raise ShortcutError("A shortcut needs Ctrl, Alt or Win, otherwise it would block normal typing.")
    return modifiers, _key_code(key_name)


def _key_code(name: str) -> int:
    if len(name) == 1 and name.isascii() and name.isalnum():
        return ord(name.upper())  # letters and digits: their code is the character itself
    if name in NAMED_KEYS:
        return NAMED_KEYS[name]
    if name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
        return 0x70 + int(name[1:]) - 1  # F1 = 0x70, F2 = 0x71, ...
    raise ShortcutError(f"'{name}' is not a key ScreenQA understands. Try a letter, a number, F1-F12 or Space.")


class _MessageFilter(QAbstractNativeEventFilter):
    """Sees every Windows message Qt receives, and reacts to our hotkey."""

    def __init__(self, on_hotkey) -> None:
        super().__init__()
        self._on_hotkey = on_hotkey

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            # `message` is the memory address of a Windows MSG structure; read it.
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self._on_hotkey()
                return True, 0  # True = "handled, nobody else needs this message"
        return False, 0  # not ours: let Qt handle it normally


class GlobalHotkey(QObject):
    """One global shortcut. Create exactly one per program (app.py does this)."""

    activated = Signal()  # emitted when the shortcut is pressed

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.shortcut = ""
        self._registered = False
        # singleShot(0, ...) runs the reaction just AFTER Qt finishes handling the
        # Windows message, instead of in the middle of it (safer for Qt).
        self._filter = _MessageFilter(lambda: QTimer.singleShot(0, self.activated.emit))
        QCoreApplication.instance().installNativeEventFilter(self._filter)

    @property
    def is_active(self) -> bool:
        return self._registered

    def register(self, shortcut: str) -> str | None:
        """Start listening for `shortcut`. Returns None if it worked, otherwise a message for the user."""
        try:
            modifiers, key_code = parse_shortcut(shortcut)
        except ShortcutError as error:
            return str(error)
        self.unregister()  # only one shortcut at a time
        # hWnd=None: deliver WM_HOTKEY to this thread (the main thread), not to one
        # window - so it keeps working even if a window is hidden or recreated.
        if not _user32.RegisterHotKey(None, HOTKEY_ID, modifiers | MOD_NOREPEAT, key_code):
            code = ctypes.get_last_error()
            log.warning("Could not register the shortcut %s (Windows error %d)", shortcut, code)
            if code == ERROR_HOTKEY_ALREADY_REGISTERED:
                return (f"{shortcut} is already used by another program (or another copy of ScreenQA). "
                        "Close that program, or choose a different shortcut in Settings.")
            return f"Windows refused the shortcut {shortcut} (error {code})."
        self.shortcut, self._registered = shortcut, True
        log.info("Global shortcut active: %s", shortcut)
        return None

    def unregister(self) -> None:
        """Stop listening (also done automatically when ScreenQA closes)."""
        if self._registered:
            _user32.UnregisterHotKey(None, HOTKEY_ID)
            self._registered = False
            log.info("Global shortcut released: %s", self.shortcut)
