# ScreenQA troubleshooting

**First step for any problem:** run the self-test. It checks every part and says
exactly which one fails.

```powershell
.\dist\ScreenQA\ScreenQA.exe --self-test          # checks everything, sends nothing online
.\dist\ScreenQA\ScreenQA.exe --self-test --live   # also tests the internet + one real AI answer
```

(From source: `python run.py --self-test`.) The report is also saved to
`%APPDATA%\ScreenQA\logs\self-test.txt`.

**Second step:** read the log. Every error message has an **Open log folder**
button, or open it directly:

```powershell
notepad $env:APPDATA\ScreenQA\logs\screenqa.log
```

API keys are never written to the log, so it is safe to share when asking for help.

---

## Starting ScreenQA

| Symptom | Likely cause | Fix |
|---|---|---|
| Nothing happens when you start `ScreenQA.exe` | Another copy is already running (it is brought to the front) or antivirus blocked it | Check the taskbar. Check your antivirus quarantine (e.g. Avast) and allow the `dist\ScreenQA` folder |
| "ScreenQA could not start" box | A damaged build or a missing file | Read `%APPDATA%\ScreenQA\logs\startup-error.log`; rebuild with `python -m PyInstaller ScreenQA.spec --noconfirm` |
| "Windows protected your PC" (SmartScreen) | The .exe you built is not digitally signed | Click **More info > Run anyway** (only for your own build) |
| Build fails with "Access is denied" | ScreenQA.exe is still running | Close ScreenQA, then build again |

## Keyboard shortcut

| Symptom | Likely cause | Fix |
|---|---|---|
| Label says **(not available)** | Another program (or another ScreenQA) uses that combination | Hover the label for details; choose another shortcut in **Settings** |
| Pressing the shortcut does nothing | The label isn't "(works in any program)", or ScreenQA isn't running | Check the label; the log shows "Global shortcut pressed" for every press |
| Shortcut closes your browser | You picked a browser shortcut such as Ctrl+Shift+Q | Use the default Ctrl+Shift+Space or another combination |

## Capturing and reading text

| Symptom | Likely cause | Fix |
|---|---|---|
| "The captured area looks blank" | The app blocks screenshots (video players, some secure browsers) or you selected empty space | Select the text itself; if it's protected, type the question with **Edit Question** |
| Captured area is shifted / wrong part | Display scaling or monitors changed while ScreenQA was running | Restart ScreenQA. Select within one monitor at a time |
| Wrong letters or missing symbols | Small text, or code/maths (Windows OCR is weak at symbols) | Zoom the page in (Ctrl +) before capturing, use **Read with AI Vision**, or fix it with **Edit Question** |
| "Windows OCR is not installed for your language" | Your Windows display language has no OCR pack | Settings > Time & language > Language & region > your language > Language options > install *Optical character recognition* |

## The AI

| Message | Cause | Fix |
|---|---|---|
| "No API key found" | No key saved for the chosen service | **Settings** > paste the key > **Test connection** > **Save** |
| "... rejected your API key" | Key copied incompletely, deleted, or (Google) a new **AQ.** key | Paste it again. Many new Google accounts only get "AQ." keys that Google currently rejects - use **Groq** instead |
| "You've reached ...'s free-tier limit" | Groq free plan: 30 requests/minute, 1,000/day | Wait a minute; the daily limit resets the next day |
| "...only handles a limited amount of text per minute" | Groq free plan allows only ~1,000 answer tokens per minute | Wait about a minute; select a smaller region or untick "Send screenshot" |
| "Could not connect to ..." | No internet, VPN, firewall or a school/work proxy | Check the connection; try another network |
| "took too long to answer" | Slow service or network | Try again |
| "The answer was cut off" / "ran out of space" | Answer longer than the limit | Shorter question; for Gemini/Claude raise **Maximum answer length** in Settings |
| Yellow **Check carefully** box | ScreenQA spotted a problem (e.g. the AI contradicted itself) | Read it and check the answer yourself |

**AI answers can be wrong**, even with "high confidence". The free Groq model is
smaller than Gemini or Claude. Always check before you use an answer.

## Your data

| Want to... | Do this |
|---|---|
| See where everything is | `explorer $env:APPDATA\ScreenQA` |
| Delete all questions | **History** tab > **Clear History** (the text is overwritten, not just hidden) |
| Delete saved screenshots | **Settings** > **Delete all saved screenshots** |
| Reset all settings | Close ScreenQA, delete `%APPDATA%\ScreenQA\settings.json` |
| Remove a saved API key | **Settings** > **Remove saved key** |
| Remove ScreenQA completely | Delete the `ScreenQA` project folder, the Start-menu shortcut, and `%APPDATA%\ScreenQA` (this deletes your history and keys) |

## For developers

```powershell
python -m pytest                                   # all automated tests (~40 s)
$env:SCREENQA_LIVE_TESTS = "1"; python -m pytest -m live -v   # + tests using your real key
python -m PyInstaller ScreenQA.spec --noconfirm    # rebuild the .exe
```

Known environment gotchas:

* If `python` on PATH is another Python (MSYS2, Microsoft Store), always create the venv with `py -3.14 -m venv .venv`.
* Antivirus software such as Avast may inspect HTTPS connections; ScreenQA handles this with `truststore` (Windows' certificate list).
* Editing files with PowerShell 5.1 `Get-Content`/`Set-Content` can corrupt special characters (√ π ×) - use a proper editor.
* Don't keep the project in a OneDrive-synced folder: syncing locks files and breaks `pip install` and builds.
