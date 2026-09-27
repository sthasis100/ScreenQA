"""
history.py - saves answered questions in a small database on your PC (Step 14).

The database is ONE file:  %APPDATA%\\ScreenQA\\history.db
It uses SQLite, which is built into Python: a mini database in a single file,
with tables, rows and a query language (SQL).

What is saved:     the question text, the full answer and explanation, which AI
                   answered, and when. Screenshots ONLY if you switch that on in
                   Settings (then the PNG file's location is stored here).
What is NOT saved: API keys.

Privacy details:
  * "secure_delete" makes SQLite overwrite deleted rows with zeros, so deleted
    questions can't be dug back out of the file.
  * After "Clear History" we also VACUUM (rebuild) the file, so it shrinks.
"""

import json
import logging
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

from screenqa.analyzer import Analysis
from screenqa.paths import data_dir, screenshots_dir

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1  # bump this (and add an upgrade step) if the table ever changes

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,  -- a unique number per question
    created_at      TEXT NOT NULL,                      -- e.g. 2026-09-27T16:05:12
    question        TEXT NOT NULL,
    question_type   TEXT,
    final_answer    TEXT,
    confidence      TEXT,
    provider        TEXT,
    model           TEXT,
    analysis_json   TEXT NOT NULL,                      -- the whole answer, to show it again later
    screenshot_path TEXT                                -- only used if you enable saving screenshots
)
"""


class HistoryError(Exception):
    """A history problem we can explain to the user."""


@dataclass
class HistoryEntry:
    """One row of the history list (without the full answer)."""

    id: int
    created_at: str
    question: str
    question_type: str
    final_answer: str
    confidence: str
    screenshot_path: str = ""  # "" = no screenshot was saved

    @property
    def when(self) -> str:
        """A short, friendly time like '27 Sep 16:05'."""
        try:
            return datetime.fromisoformat(self.created_at).strftime("%d %b %H:%M")
        except ValueError:
            return self.created_at


def default_path() -> Path:
    return data_dir() / "history.db"


class HistoryStore:
    """Everything that reads or writes the history database."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else default_path()
        self._prepare()

    # ---------- Opening the database ----------

    def _connect(self) -> sqlite3.Connection:
        """Open a short-lived connection. (Each method opens, uses and closes one.)"""
        connection = sqlite3.connect(self.path, timeout=5)  # wait up to 5 s if the file is busy
        connection.row_factory = sqlite3.Row  # lets us read columns by name: row["question"]
        connection.execute("PRAGMA secure_delete = ON")  # overwrite deleted data with zeros
        return connection

    def _prepare(self) -> None:
        """Create the table the first time; set a damaged file aside instead of crashing."""
        try:
            self._create_table()
        except sqlite3.DatabaseError as error:  # e.g. "file is not a database"
            broken = self.path.with_name(f"history-damaged-{datetime.now():%Y%m%d-%H%M%S}.db")
            log.error("History file is damaged (%s); moving it to %s and starting fresh", error, broken.name)
            self.path.replace(broken)
            self._create_table()

    def _create_table(self) -> None:
        with closing(self._connect()) as connection, connection:  # "connection" = commit at the end
            connection.execute(CREATE_TABLE)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # ---------- Writing ----------

    def add(self, question: str, analysis: Analysis, screenshot_path: str | None = None) -> int:
        """Save one answered question. Returns its id."""
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    # The ?s are placeholders: SQLite fills them in safely. Never paste
                    # values into SQL text yourself - that's how "SQL injection" happens.
                    "INSERT INTO history (created_at, question, question_type, final_answer, confidence,"
                    " provider, model, analysis_json, screenshot_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (datetime.now().isoformat(timespec="seconds"), question, analysis.question_type,
                     analysis.final_answer, analysis.confidence, analysis.provider, analysis.model,
                     _analysis_to_json(analysis), screenshot_path),
                )
                return cursor.lastrowid
        except sqlite3.Error as error:
            log.exception("Could not save to history")
            raise HistoryError(f"Could not save this question to the history: {error}") from error

    def delete(self, entry_id: int) -> None:
        """Permanently delete one saved question (and its screenshot, if one was saved)."""
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT screenshot_path FROM history WHERE id = ?", (entry_id,)).fetchone()
            connection.execute("DELETE FROM history WHERE id = ?", (entry_id,))
        if row and row["screenshot_path"]:
            delete_screenshot_file(row["screenshot_path"])

    def forget_screenshots(self) -> None:
        """Remove the screenshot links from all rows (used after deleting the screenshot files)."""
        with closing(self._connect()) as connection, connection:
            connection.execute("UPDATE history SET screenshot_path = NULL")

    def clear(self) -> int:
        """Permanently delete ALL saved questions and their screenshots. Returns how many."""
        with closing(self._connect()) as connection:
            with connection:
                paths = [row[0] for row in connection.execute(
                    "SELECT screenshot_path FROM history WHERE screenshot_path IS NOT NULL")]
                deleted = connection.execute("DELETE FROM history").rowcount
            # VACUUM rebuilds the file without the deleted rows (it can't run inside
            # a transaction, which is why it comes after the "with connection" block).
            connection.execute("VACUUM")
        for path in paths:
            delete_screenshot_file(path)
        log.info("History cleared (%d question(s), %d screenshot(s) deleted)", deleted, len(paths))
        return deleted

    # ---------- Reading ----------

    def count(self) -> int:
        with closing(self._connect()) as connection:
            return connection.execute("SELECT COUNT(*) FROM history").fetchone()[0]

    def list_entries(self, search: str = "", limit: int = 500) -> list[HistoryEntry]:
        """Newest first. `search` keeps only questions/answers containing that text."""
        sql = ("SELECT id, created_at, question, question_type, final_answer, confidence FROM history")
        parameters: tuple = ()
        if search.strip():
            sql += " WHERE question LIKE ? OR final_answer LIKE ?"
            pattern = f"%{search.strip()}%"  # % means "anything" in SQL LIKE
            parameters = (pattern, pattern)
        sql += " ORDER BY id DESC LIMIT ?"
        with closing(self._connect()) as connection:
            rows = connection.execute(sql, parameters + (limit,)).fetchall()
        return [HistoryEntry(row["id"], row["created_at"], row["question"], row["question_type"] or "",
                             row["final_answer"] or "", row["confidence"] or "") for row in rows]

    def get(self, entry_id: int) -> tuple[HistoryEntry, Analysis] | None:
        """One saved question with its full answer, or None if it no longer exists."""
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM history WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            return None
        entry = HistoryEntry(row["id"], row["created_at"], row["question"], row["question_type"] or "",
                             row["final_answer"] or "", row["confidence"] or "", row["screenshot_path"] or "")
        return entry, _analysis_from_json(row["analysis_json"])


# ---------- Saved screenshot files ----------

def delete_screenshot_file(path: str) -> None:
    """Delete one saved screenshot - but ONLY if it is inside ScreenQA's screenshots folder.

    That check means a damaged or edited database can never make ScreenQA
    delete some other file on your PC.
    """
    try:
        file = Path(path).resolve()
        if file.is_relative_to(screenshots_dir().resolve()) and file.suffix.lower() == ".png":
            file.unlink(missing_ok=True)  # missing_ok: no error if it's already gone
        else:
            log.warning("Refusing to delete a file outside the screenshots folder: %s", path)
    except OSError as error:
        log.warning("Could not delete screenshot %s: %s", path, error)


def delete_all_screenshots() -> int:
    """Delete every saved screenshot file. Returns how many were deleted."""
    files = list(screenshots_dir().glob("*.png"))
    for file in files:
        delete_screenshot_file(str(file))
    log.info("Deleted %d saved screenshot(s)", len(files))
    return len(files)


# ---------- Converting an Analysis to/from JSON text for storage ----------

def _analysis_to_json(analysis: Analysis) -> str:
    return json.dumps(asdict(analysis), ensure_ascii=False)


def _analysis_from_json(text: str) -> Analysis:
    try:
        data = json.loads(text)
    except ValueError:
        return Analysis(explanation="(This saved answer could not be read.)")
    known = {f.name for f in fields(Analysis)}
    data = {key: value for key, value in data.items() if key in known}  # ignore unknown keys
    # JSON has no tuples, so ("a. X", "why") pairs come back as lists - turn them back.
    data["other_choices"] = [tuple(pair) for pair in data.get("other_choices", [])]
    return Analysis(**data)
