"""Tests for history.py: saving, searching, deleting and safely clearing questions."""

from screenqa import history as hist
from screenqa.analyzer import Analysis
from screenqa.paths import screenshots_dir


def answer(text, kind="multiple_choice"):
    return Analysis(question_type=kind, final_answer=text, other_choices=[("a. Queue", "FIFO")],
                    steps=["one", "two"], confidence="high", parsed_ok=True)


def test_save_list_search_get_delete(tmp_path):
    store = hist.HistoryStore(tmp_path / "h.db")
    first = store.add("Which data structure is LIFO?", answer("b. Stack"))
    store.add("What is 150 / 2.5?", answer("60 km/h", "calculation"))
    assert [e.final_answer for e in store.list_entries()] == ["60 km/h", "b. Stack"]  # newest first
    assert [e.final_answer for e in store.list_entries(search="lifo")] == ["b. Stack"]
    entry, analysis = store.get(first)
    assert analysis.other_choices == [("a. Queue", "FIFO")] and analysis.steps == ["one", "two"]
    store.delete(first)
    assert store.count() == 1 and store.get(first) is None


def test_tricky_text_is_stored_exactly(tmp_path):
    store = hist.HistoryStore(tmp_path / "h.db")
    tricky = "it's \"quoted\" <b>html</b> '; DROP TABLE history; -- √ π"
    entry_id = store.add(tricky, answer("fine"))
    assert store.get(entry_id)[0].question == tricky
    assert store.count() == 1  # the table is still there


def test_clear_really_removes_the_text_from_the_file(tmp_path):
    database = tmp_path / "h.db"
    store = hist.HistoryStore(database)
    store.add("SECRET-MARKER-7391", answer("SECRET-MARKER-7391"))
    assert b"SECRET-MARKER-7391" in database.read_bytes()
    assert store.clear() == 1
    assert b"SECRET-MARKER-7391" not in database.read_bytes()


def test_damaged_file_is_set_aside(tmp_path):
    database = tmp_path / "h.db"
    database.write_bytes(b"this is not a database" * 100)
    assert hist.HistoryStore(database).count() == 0
    assert list(tmp_path.glob("history-damaged-*.db"))


def test_deleting_a_question_deletes_its_screenshot(tmp_path):
    store = hist.HistoryStore(tmp_path / "h.db")
    picture = screenshots_dir() / "capture-test.png"
    picture.write_bytes(b"png")
    entry_id = store.add("Q", answer("A"), screenshot_path=str(picture))
    store.delete(entry_id)
    assert not picture.exists()


def test_never_deletes_files_outside_the_screenshots_folder(tmp_path):
    other_file = tmp_path / "my-photo.png"
    other_file.write_bytes(b"precious")
    hist.delete_screenshot_file(str(other_file))
    assert other_file.exists()
