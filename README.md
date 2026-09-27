# ScreenQA - Screen Question Assistant

A Windows desktop app: press a shortcut, drag a rectangle around a question on
your screen, check the text it reads, and get an AI answer with a clear
explanation. It **only reads the screen and shows text** - it never clicks,
types or submits anything for you.

![icon](assets/icon.png)

## Contents

1. [Use it](#use-it)
2. [Set up on your computer (step by step)](#set-up-on-your-computer-step-by-step)
3. [Everyday commands](#everyday-commands)
4. [AI services](#ai-services) · [Where your data lives](#where-your-data-lives) · [Problems?](#problems) · [Project structure](#project-structure)

## Use it

**Packaged app:** double-click `dist\ScreenQA\ScreenQA.exe`
(add it to the Start menu once with `.\tools\create_shortcut.ps1`).
The `dist` folder isn't stored on GitHub - build it with the steps below.

1. Press **Ctrl+Shift+Space** anywhere (or click **Capture Screen**) and drag around the question.
2. The text is read on your PC (Windows OCR). Fix mistakes with **Edit Question**, or use **Read with AI Vision** for code, maths and tables.
3. Click **Ask AI**. The first time, ScreenQA asks before sending anything; the orange **SENDING** label shows whenever data leaves your PC.
4. Read the answer, badges (type, confidence, warnings) and explanation. **Copy Answer** / **Copy All**.
5. Past questions are in the **History** tab. Change everything in **Settings**.

**First-time setup:** get a free Groq key at https://console.groq.com/keys, then
**Settings > API key > paste > Test connection > Save**.

## Set up on your computer (step by step)

About 10-15 minutes. All commands are for **PowerShell** (Start menu > type
"PowerShell"). Run them one at a time.

### What you need

| Thing | Why | Get it |
|---|---|---|
| Windows 10 or 11 (64-bit) | ScreenQA uses Windows' own OCR and shortcut system | - |
| Python 3.14 from **python.org** (3.13 should also work) | Runs the app | `winget install Python.Python.3.14` or https://www.python.org/downloads/ |
| Git | Downloads this project | `winget install Git.Git` |
| Access to this GitHub repository | It is private | Ask the owner to add you, and sign in when Git asks |
| A free Groq API key | The AI service | https://console.groq.com/keys |

After installing Python or Git, **close and reopen PowerShell** so it finds them.

### 1. Download the project

```powershell
cd $HOME
git clone https://github.com/sthasis100/ScreenQA.git
cd ScreenQA
```

Pick a folder that is **not** synced by OneDrive (OneDrive locks files while
syncing, which breaks installing and building). `C:\Users\<you>` is fine.

### 2. Create a private Python environment ("virtual environment")

```powershell
py -3.14 -m venv .venv
```

Use `py -3.14`, not `python`: on some PCs `python` starts a different Python
(for example MSYS2 or the Microsoft Store one) that can't install PySide6.

### 3. Switch it on

```powershell
.\.venv\Scripts\Activate.ps1
```

Your prompt now starts with `(.venv)`. Do this in every new PowerShell window.
If you see *"running scripts is disabled"*, run this once, then try again:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 4. Install the libraries

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

This installs about 320 MB into `.venv` (a few minutes).

### 5. Check the setup

```powershell
python tools\check_setup.py
```

Every line should say `[ OK ]`, ending with "Everything looks good."

### 6. Start ScreenQA and add your key

```powershell
python run.py
```

Click **Settings** > paste your Groq key into **API key** > **Test connection**
(it should say "Connected!") > **Save**. Keys are stored in
`%APPDATA%\ScreenQA\.env` - never in the project folder.

### 7. Check everything works

```powershell
python run.py --self-test --live
```

Should end with **ALL CHECKS PASSED** (it sends one tiny test question).

### 8. (Optional) Build the Windows app and add it to the Start menu

```powershell
python -m PyInstaller ScreenQA.spec --noconfirm
.\tools\create_shortcut.ps1
```

The app is `dist\ScreenQA\ScreenQA.exe` (the whole `dist\ScreenQA` folder
belongs together). Windows may say "Windows protected your PC" because the app
isn't signed: click **More info > Run anyway**.

### Getting updates later

```powershell
cd $HOME\ScreenQA
.\.venv\Scripts\Activate.ps1
git pull
python -m pip install -r requirements-dev.txt
python -m PyInstaller ScreenQA.spec --noconfirm
```

### Setup problems

| Problem | Fix |
|---|---|
| `py` is not recognised | Install Python from python.org (it includes the `py` launcher), then reopen PowerShell |
| `No matching distribution found for PySide6-Essentials` | The venv was made with the wrong Python. Delete `.venv` and repeat step 2 with `py -3.14` |
| `ModuleNotFoundError` when starting | The venv isn't switched on (step 3), or step 4 didn't finish |
| pip times out | A school/work network may block it - try another network |
| "Windows OCR is not installed for your language" | Settings > Time & language > Language & region > your language > Language options > install *Optical character recognition* |
| Anything else | See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |

## Everyday commands

Run these in the project folder with the venv switched on (step 3):

| Command | What it does |
|---|---|
| `python run.py` | Start ScreenQA from the source code |
| `python run.py --self-test` | Check every part on this PC (add `--live` for one real AI answer) |
| `python -m pytest` | Run the automated tests (126 tests, ~40 s) |
| `python -m PyInstaller ScreenQA.spec --noconfirm` | Build `dist\ScreenQA\ScreenQA.exe` (close ScreenQA first) |
| `python -m screenqa.ocr_local picture.png` | Test OCR on a saved picture |
| `python -m screenqa.ai_client` | Test the AI connection |

## AI services

| Service | Cost | Notes |
|---|---|---|
| **Groq** (default) | Free: 30 requests/min, 1,000/day | Model `qwen/qwen3.8-27b` reads images. Says it doesn't keep requests (except up to 30 days of safety logs) |
| Google Gemini | Free tier | Google may use free-tier data to improve its products. Many new accounts only get "AQ." keys that Google currently rejects |
| Anthropic Claude | Paid | Strongest answers; Anthropic doesn't train on API data by default |

## Where your data lives

Everything personal is in `%APPDATA%\ScreenQA` - never in this project folder.

| File | What it is |
|---|---|
| `settings.json` | Your settings (no secrets) |
| `.env` | Your API keys |
| `history.db` | Question history - text only; **Clear History** overwrites it |
| `screenshots\` | Saved captures - **only** if you switch this on in Settings |
| `logs\` | `screenqa.log` (never contains API keys), `self-test.txt`, `startup-error.log` |

## Problems?

See **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)**. Start with the self-test:
`.\dist\ScreenQA\ScreenQA.exe --self-test`.

## Project structure

```text
run.py                  start here (also --self-test)
ScreenQA.spec           how to build the .exe (PyInstaller)
screenqa\
  app.py                startup: logging, one-copy check, window, shortcut, clean exit
  main_window.py        the window; connects everything below
  region_selector.py    freeze the screen and drag a rectangle
  ocr_local.py          Windows' built-in OCR (offline)
  analyzer.py           question type, AI instructions, reading + checking the answer
  prompts.py            the instructions given to the AI
  ai_client.py          the only file that talks to the internet (Groq / Gemini / Claude)
  providers.py          the AI services and their limits
  render.py             answer display (badges, sections, code, maths)
  history.py            saved questions (SQLite)
  settings.py           settings.json;  settings_dialog.py - the Settings window
  hotkey.py             global shortcut (Windows RegisterHotKey)
  api_keys.py           API keys in .env
  errors.py             friendly error messages and safety nets
  selftest.py           the --self-test checks
  workers.py            background jobs so the window never freezes
  imaging.py, image_preview.py, paths.py, logging_setup.py
tests\                  pytest tests (fake AI server, end-to-end test)
tools\                  check_setup.py, make_icon.py, create_shortcut.ps1
docs\TROUBLESHOOTING.md
```
