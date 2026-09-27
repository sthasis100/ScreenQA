"""
check_setup.py - Step 6 self-test for your development environment.

Run it (with the virtual environment active) from the project folder:

    python tools\\check_setup.py

It checks that you are using the right Python and that every library imports.
Exit code 0 = all good, 1 = something needs fixing.
"""

import importlib
import platform
import sys
import sysconfig
from importlib.metadata import PackageNotFoundError, version

# (name to import, name on PyPI, what ScreenQA uses it for)
REQUIRED = [
    ("PySide6.QtWidgets", "PySide6-Essentials", "the desktop window (GUI)"),
    ("google.genai", "google-genai", "talking to Google Gemini (free)"),
    ("anthropic", "anthropic", "talking to Claude (optional)"),
    ("openai", "openai", "OpenAI-compatible services (optional)"),
    ("dotenv", "python-dotenv", "reading the API key from a .env file"),
    ("winrt.windows.media.ocr", "winrt-Windows.Media.Ocr", "offline Windows OCR"),
    ("winrt.windows.graphics.imaging", "winrt-Windows.Graphics.Imaging", "images for Windows OCR"),
    ("winrt.windows.storage.streams", "winrt-Windows.Storage.Streams", "images for Windows OCR"),
]
DEV_TOOLS = [
    ("pytest", "pytest", "running tests (Step 17)"),
    ("PyInstaller", "pyinstaller", "building the .exe (Step 19)"),
]


def check_python() -> int:
    """Check the Python interpreter itself. Returns the number of problems."""
    problems = 0
    print(f"Python {sys.version.split()[0]} at {sys.executable}")

    if sys.version_info < (3, 10):
        print("  [FAIL] Python 3.10 or newer is required.")
        problems += 1
    if platform.system() != "Windows":
        print("  [FAIL] ScreenQA is built for Windows.")
        problems += 1
    # MSYS2/MinGW Python reports a platform like "mingw_x86_64_ucrt".
    # It cannot install the normal Windows wheels that PySide6 needs.
    if "mingw" in sysconfig.get_platform():
        print("  [FAIL] This is an MSYS2/MinGW Python. Create the venv with 'py -3.14' instead.")
        problems += 1
    # Inside a venv, sys.prefix points at .venv; outside it equals sys.base_prefix.
    if sys.prefix == sys.base_prefix:
        print("  [FAIL] Not inside the virtual environment. Run: .\\.venv\\Scripts\\Activate.ps1")
        problems += 1
    else:
        print("  [ OK ] Running inside a virtual environment")
    return problems


def check_packages(packages, required: bool) -> int:
    """Try to import each package. Returns the number of problems."""
    problems = 0
    for import_name, pypi_name, purpose in packages:
        try:
            importlib.import_module(import_name)
            print(f"  [ OK ] {pypi_name} {version(pypi_name)}  - {purpose}")
        except (ImportError, PackageNotFoundError) as error:
            label = "FAIL" if required else "WARN"
            print(f"  [{label}] {pypi_name} - {purpose}: {error}")
            if required:
                problems += 1
    return problems


def main() -> int:
    problems = check_python()
    print("\nApp packages (requirements.txt):")
    problems += check_packages(REQUIRED, required=True)
    print("\nDeveloper tools (requirements-dev.txt):")
    check_packages(DEV_TOOLS, required=False)  # missing dev tools are only a warning

    print()
    if problems:
        print(f"{problems} problem(s) found. Fix them before continuing.")
        return 1
    print("Everything looks good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
