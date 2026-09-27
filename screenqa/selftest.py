"""
selftest.py - checks that every part of ScreenQA works on THIS computer (Step 18).

Most useful after building the .exe (Step 19), because the .exe must carry
everything with it - this proves it does.

    python run.py --self-test           checks everything WITHOUT sending anything online
    python run.py --self-test --live    also sends one tiny question to your AI service
    ScreenQA.exe --self-test            the same, for the packaged app

The results are shown, and saved to %APPDATA%\\ScreenQA\\logs\\self-test.txt
"""

import socket
import ssl
import sys
import tempfile
import time
from pathlib import Path


def run_self_test(live: bool = False) -> tuple[bool, str]:
    """Run every check. Returns (all passed?, a readable report)."""
    from PySide6 import __version__ as qt_version
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from screenqa import __version__, api_keys
    from screenqa.paths import data_dir, logs_dir
    from screenqa.settings import load_settings

    app = QApplication.instance() or QApplication(sys.argv)  # needed for fonts, screens and OCR
    results: list[tuple[bool, str, str]] = []

    def check(name: str, test) -> None:
        try:
            results.append((True, name, test() or "ok"))
        except Exception as error:  # a failed check must not stop the others
            results.append((False, name, f"{type(error).__name__}: {error}"))

    settings = load_settings()

    def versions():
        frozen = "packaged .exe" if getattr(sys, "frozen", False) else "running from source"
        return f"ScreenQA {__version__}, Python {sys.version.split()[0]}, PySide6 {qt_version} ({frozen})"

    def data_folder():
        probe = data_dir() / "self-test.tmp"
        probe.write_text("ok")
        probe.unlink()
        return str(data_dir())

    def api_key():
        provider = settings.provider
        source = api_keys.key_source(provider.key_env_var)
        if not source:
            raise RuntimeError(f"no {provider.label} key - add one in Settings")
        return f"{provider.label} key found ({api_keys.mask(api_keys.get_api_key(provider.key_env_var))})"

    def windows_ocr():
        from screenqa.ocr_local import read_text

        image = QImage(600, 80, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        font = QFont("Segoe UI")
        font.setPixelSize(18)
        painter.setFont(font)
        painter.setPen(QColor("black"))
        painter.drawText(10, 45, "Which data structure is LIFO? B. Stack")
        painter.end()
        result = read_text(image)
        if "Stack" not in result.text:
            raise RuntimeError(f"OCR read {result.text!r}")
        return f"read a test question in {result.seconds:.2f} s ({result.language})"

    def screens():
        found = app.screens()
        if not found:
            raise RuntimeError("no screen found")
        pictures = [screen.grabWindow(0) for screen in found]  # nothing is saved or sent
        if any(picture.isNull() for picture in pictures):
            raise RuntimeError("a screen could not be captured")
        return ", ".join(f"{p.width()}x{p.height()} at {s.devicePixelRatio():.0%}" for s, p in zip(found, pictures))

    def history_database():
        from screenqa.analyzer import Analysis
        from screenqa.history import HistoryStore

        with tempfile.TemporaryDirectory() as folder:  # a throw-away database, not your history
            store = HistoryStore(Path(folder) / "test.db")
            store.add("test question", Analysis(final_answer="test"))
            store.clear()
        return "SQLite works"

    def global_shortcut():
        from screenqa.hotkey import GlobalHotkey

        hotkey = GlobalHotkey()
        problem = hotkey.register("Ctrl+Alt+Shift+F12")  # an unusual test combination
        hotkey.unregister()
        if problem:
            raise RuntimeError(problem)
        return f"Windows accepted a test shortcut (yours: {settings.shortcut})"

    def secure_connection():
        import truststore

        host = {"groq": "api.groq.com", "gemini": "generativelanguage.googleapis.com"}.get(
            settings.provider_id, "api.anthropic.com")
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # the same trust setup ScreenQA uses
        with socket.create_connection((host, 443), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname=host):
                pass  # only the secure handshake - no data is sent
        return f"secure connection to {host} works"

    def ai_libraries():
        import anthropic
        import google.genai
        import openai

        return f"openai {openai.__version__}, anthropic {anthropic.__version__}, google-genai {google.genai.__version__}"

    def live_answer():
        from screenqa.analyzer import analyze  # the full pipeline: instructions, JSON answer, checks

        result = analyze("What is 7 x 6?", None, provider=settings.provider, model=settings.model_name,
                         max_tokens=settings.effective_max_tokens())
        if "42" not in result.final_answer or not result.parsed_ok:
            raise RuntimeError(f"unexpected answer {result.final_answer!r} (structured: {result.parsed_ok})")
        return f"{result.model} answered 42 ({result.type_label}, {result.confidence} confidence) in {result.seconds:.1f} s"

    check("Versions", versions)
    check("Data folder can be written", data_folder)
    check("Settings", lambda: f"{settings.provider.label}, model {settings.model_name}, shortcut {settings.shortcut}")
    check("API key", api_key)
    check("Windows OCR", windows_ocr)
    check("Screen capture", screens)
    check("History database", history_database)
    check("Global shortcut", global_shortcut)
    check("AI libraries included", ai_libraries)
    if live:
        check("Secure internet connection", secure_connection)
        check("Live AI answer", live_answer)

    passed = all(ok for ok, _, _ in results)
    lines = [f"ScreenQA self-test - {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    lines += [f"[{' OK ' if ok else 'FAIL'}] {name}: {detail}" for ok, name, detail in results]
    lines += ["", "ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED - see the lines marked FAIL"]
    if not live:
        lines.append("(Add --live to also test the internet connection and one real AI answer.)")
    report = "\n".join(lines)
    try:
        (logs_dir() / "self-test.txt").write_text(report, encoding="utf-8")
    except OSError:
        pass
    return passed, report


def main(arguments: list[str]) -> int:
    """--live: also test the internet and one real answer. --quiet: no window, only the report file."""
    passed, report = run_self_test(live="--live" in arguments)
    if sys.stdout is not None:  # started from a terminal: print the report
        print(report)
    elif "--quiet" not in arguments:  # the windowed .exe has no terminal: show the report in a window
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(None, "ScreenQA self-test", report)
    return 0 if passed else 1
