# ScreenQA.spec - instructions for PyInstaller to build ScreenQA.exe (Step 19).
#
# Build (project folder, virtual environment active):
#     python -m PyInstaller ScreenQA.spec --noconfirm
#
# Result: dist\ScreenQA\ScreenQA.exe
# The WHOLE dist\ScreenQA folder belongs together - copy or zip the folder, not just the .exe.
#
# This file is Python code that PyInstaller runs. Analysis/PYZ/EXE/COLLECT are
# PyInstaller's building blocks:
#   Analysis - follows every "import" starting from run.py to find what's needed
#   PYZ      - packs the Python code into one archive
#   EXE      - makes ScreenQA.exe
#   COLLECT  - puts the .exe, Python, Qt and all DLLs together in dist\ScreenQA

from PyInstaller.utils.hooks import collect_submodules

analysis = Analysis(
    ["run.py"],
    # Files that aren't Python code but must travel with the program: (source, folder inside the app)
    datas=[("assets/icon.png", "assets"), ("assets/icon.ico", "assets")],
    # Windows OCR (winrt) is loaded in a way PyInstaller can't fully see, so list it explicitly.
    hiddenimports=collect_submodules("winrt"),
    # Only needed while developing - leaving them out makes the app smaller.
    excludes=["tkinter", "pytest", "_pytest", "PyInstaller"],
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    exclude_binaries=True,  # "one folder" mode: starts faster and upsets antivirus less than one big file
    name="ScreenQA",
    console=False,  # a normal windowed app: no black console window behind it
    icon="assets/icon.ico",
    version="packaging/version_info.txt",  # shown in the .exe's Properties > Details
)

COLLECT(exe, analysis.binaries, analysis.datas, name="ScreenQA")
