"""
main_window.py - the main ScreenQA window.

This file builds everything you see and reacts to your clicks. The real work
happens in other files, which it calls:
  region_selector.py (capture)   ocr_local.py (read text)   analyzer.py (AI answer)
  render.py (display)            history.py (saved questions)   hotkey.py (shortcut)
Slow jobs run in the background through workers.py, so the window never freezes.

Qt vocabulary used below:
  widget  = anything visible (button, label, text box, the window itself)
  layout  = an invisible helper that positions widgets in a row or column
  signal  = "something happened" (e.g. a button's `clicked`)
  slot    = the method we connect to a signal, so it runs when that happens
"""

import html
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QFont, QGuiApplication, QImage
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from screenqa import ai_client, analyzer, prompts
from screenqa import errors
from screenqa.ai_client import AIResponse
from screenqa.analyzer import QUESTION_TYPES, Analysis
from screenqa.history import HistoryError, HistoryStore
from screenqa.hotkey import GlobalHotkey
from screenqa.image_preview import ImagePreview
from screenqa.imaging import looks_blank, save_screenshot, to_png_bytes
from screenqa.ocr_local import OcrResult, read_text
from screenqa.providers import Provider
from screenqa.region_selector import RegionSelector
from screenqa.render import answer_html, explanation_html, to_plain_text
from screenqa.settings import Settings, save_settings
from screenqa.settings_dialog import SettingsDialog
from screenqa.workers import run_in_background

log = logging.getLogger(__name__)

# How long to wait after hiding our window before freezing the screen.
# Windows needs a moment to finish its fade-out animation; without this pause
# a faint "ghost" of the ScreenQA window can end up in the screenshot.
CAPTURE_DELAY_MS = 250

WINDOW_TITLE = "ScreenQA - Screen Question Assistant"  # app.py finds a running copy by this title

QUESTION_PLACEHOLDER = "The text found in your screenshot will appear here."

# Screenshots bigger than this (longest side, in pixels) are shrunk before
# being sent to the AI: smaller uploads are faster and the AI reads them fine.
AI_IMAGE_MAX_SIDE = 2000


class MainWindow(QMainWindow):
    """The one window the user interacts with."""

    def __init__(self, history: HistoryStore | None = None, settings: Settings | None = None) -> None:
        """history: where answered questions are saved (None = don't save any).
        settings: your preferences (None = the defaults)."""
        super().__init__()  # let QMainWindow set itself up first
        self.settings = settings or Settings()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1000, 680)  # starting size in pixels (width, height)
        self.setMinimumSize(720, 480)  # the user cannot shrink it smaller than this

        # The most recent captured region. It lives ONLY in memory (RAM).
        self.current_image: QImage | None = None
        # The active region selector while a capture is in progress, else None.
        self._selector: RegionSelector | None = None
        # Number of the newest OCR job; older results that arrive late are ignored.
        self._ocr_job = 0
        # Same idea for AI requests, plus a flag while one is running.
        self._ai_job = 0
        self._ai_busy = False
        # Providers the user has agreed to send data to during this session.
        self._consent_given: set[str] = set()
        # The most recent answer (Step 12: used by the Copy buttons).
        self.current_analysis: Analysis | None = None
        # The global keyboard shortcut (Step 13); app.py attaches it.
        self.hotkey: GlobalHotkey | None = None
        # Saved questions (Step 14), and the question text of the request in progress.
        self.history = history
        self._question_being_answered = ""
        # Where the current capture was saved, if "Save screenshots" is on (Step 15).
        self._current_screenshot_path: str | None = None
        self._screenshot_save_warned = False  # Step 16: warn about a failed save only once

        # A QMainWindow shows ONE "central widget". We make a plain container
        # widget and stack the toolbar row and the tabs inside it vertically.
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(self._build_toolbar())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_current_tab(), "Current question")
        self.tabs.addTab(self._build_history_tab(), "History")
        layout.addWidget(self.tabs)

        self.setCentralWidget(central)
        self._build_status_bar()
        self._connect_signals()
        self.refresh_history()
        log.info("Main window created")

    # ------------------------------------------------------------------
    # Building the layout
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> QHBoxLayout:
        """Top row: Capture button, shortcut indicator, always-on-top, Settings."""
        self.capture_button = QPushButton("Capture Screen")
        self.capture_button.setToolTip("Select a rectangle of the screen that contains the question")
        self.capture_button.setMinimumHeight(36)  # a bigger, easy-to-hit button

        # QLabel understands simple HTML, so <b> makes the shortcut bold.
        self.shortcut_label = QLabel("Shortcut: <span style='color: gray;'>not set up</span>")

        self.always_on_top_checkbox = QCheckBox("Keep window on top")
        self.always_on_top_checkbox.setToolTip("Keep this window visible above other windows")

        self.settings_button = QPushButton("Settings")

        row = QHBoxLayout()
        row.addWidget(self.capture_button)
        row.addWidget(self.shortcut_label)
        row.addStretch()  # empty stretchy space: pushes the next widgets to the right edge
        row.addWidget(self.always_on_top_checkbox)
        row.addWidget(self.settings_button)
        return row

    def _build_current_tab(self) -> QWidget:
        """The main tab: screenshot + question on the left, answer on the right."""
        # ---------- 1. Screenshot preview ----------
        preview_box = QGroupBox("1. Screenshot preview")
        self.preview = ImagePreview("No screenshot yet.\nClick 'Capture Screen' to select a region.")
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.addWidget(self.preview)

        # ---------- 2. Extracted question ----------
        question_box = QGroupBox("2. Extracted question (check it before asking)")
        self.question_edit = QPlainTextEdit()
        self.question_edit.setReadOnly(True)  # locked until the user clicks "Edit Question"
        self.question_edit.setPlaceholderText(QUESTION_PLACEHOLDER)
        # Consolas is a monospace font: every character has the same width,
        # so code indentation and aligned tables stay readable.
        self.question_edit.setFont(QFont("Consolas", 10))

        self.edit_button = QPushButton("Edit Question")
        self.edit_button.setCheckable(True)  # the button stays "pressed" while editing

        self.vision_button = QPushButton("Read with AI Vision")
        self.vision_button.setToolTip(
            "Send the screenshot region to the online AI to read the text. Much better than "
            "Windows OCR for code, equations and tables - but the picture leaves your PC."
        )

        # Privacy control: the user decides whether the image goes to the AI
        # or only the text they can see and edit.
        self.attach_image_checkbox = QCheckBox("Send screenshot with question")
        self.attach_image_checkbox.setChecked(True)
        self.attach_image_checkbox.setToolTip(
            "When ticked, the selected screen region (not your whole screen) is sent "
            "to the AI together with the text. Helps with diagrams, tables and equations."
        )

        self.ask_button = QPushButton("Ask AI")
        self.ask_button.setMinimumHeight(32)

        # Two rows of controls under the question box.
        edit_row = QHBoxLayout()
        edit_row.addWidget(self.edit_button)
        edit_row.addWidget(self.vision_button)
        edit_row.addStretch()
        ask_row = QHBoxLayout()
        ask_row.addWidget(self.attach_image_checkbox)
        ask_row.addStretch()
        ask_row.addWidget(self.ask_button)

        question_layout = QVBoxLayout(question_box)
        question_layout.addWidget(self.question_edit)
        question_layout.addLayout(edit_row)
        question_layout.addLayout(ask_row)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)  # no extra padding around the column
        left_layout.addWidget(preview_box, stretch=1)  # stretch=1 / 1: both boxes share
        left_layout.addWidget(question_box, stretch=1)  # the height equally

        # ---------- 3. Answer ----------
        answer_box = QGroupBox("3. Answer")
        self.answer_view = QTextBrowser()  # read-only box that can show formatted text
        self.answer_view.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))  # big and bold = easy to read
        self.answer_view.setPlaceholderText("The final answer will appear here.")
        self.answer_view.setMinimumHeight(90)  # room for the answer and its badges
        self.copy_button = QPushButton("Copy Answer")
        self.copy_button.setToolTip("Copy only the final answer")
        self.copy_all_button = QPushButton("Copy All")
        self.copy_all_button.setToolTip("Copy the answer, explanation, wrong options and steps as text")
        copy_row = QHBoxLayout()
        copy_row.addStretch()
        copy_row.addWidget(self.copy_button)
        copy_row.addWidget(self.copy_all_button)
        answer_layout = QVBoxLayout(answer_box)
        answer_layout.addWidget(self.answer_view)
        answer_layout.addLayout(copy_row)

        # ---------- 4. Explanation ----------
        explanation_box = QGroupBox("4. Explanation")
        self.explanation_view = QTextBrowser()
        self.explanation_view.setPlaceholderText(
            "The explanation, assumptions and confidence level will appear here."
        )
        # A- / A+ make the explanation text smaller / bigger (Ctrl + mouse wheel works too).
        self.smaller_text_button = QPushButton("A-")
        self.bigger_text_button = QPushButton("A+")
        for button, tip in ((self.smaller_text_button, "Smaller text"), (self.bigger_text_button, "Bigger text")):
            button.setFixedWidth(36)
            button.setToolTip(tip)
        zoom_row = QHBoxLayout()
        zoom_row.addStretch()
        zoom_row.addWidget(self.smaller_text_button)
        zoom_row.addWidget(self.bigger_text_button)
        explanation_layout = QVBoxLayout(explanation_box)
        explanation_layout.addWidget(self.explanation_view)
        explanation_layout.addLayout(zoom_row)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(answer_box, stretch=1)  # answer gets 1 part of the height,
        right_layout.addWidget(explanation_box, stretch=3)  # explanation gets 3 parts

        # A QSplitter puts a draggable divider between the left and right columns.
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([450, 550])  # starting widths in pixels
        return splitter

    def _build_history_tab(self) -> QWidget:
        """The History tab: search + list of past questions on the left, details on the right."""
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search questions and answers...")
        self.history_search.setClearButtonEnabled(True)  # a little "x" to empty the box

        self.history_list = QListWidget()
        self.history_list.setAlternatingRowColors(True)  # stripes make rows easier to tell apart
        self.history_list.setSpacing(2)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.history_search)
        left_layout.addWidget(self.history_list)

        self.history_detail = QTextBrowser()
        self.history_detail.setPlaceholderText("Select a question on the left to see its answer.")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.history_detail)
        splitter.setSizes([380, 620])

        # Where the history lives and how much there is (filled in by refresh_history).
        self.history_info_label = QLabel()
        self.history_info_label.setStyleSheet("color: gray;")
        self.delete_entry_button = QPushButton("Delete Selected")
        self.delete_entry_button.setEnabled(False)  # enabled once something is selected
        self.clear_history_button = QPushButton("Clear History")
        self.clear_history_button.setToolTip("Permanently delete every saved question and answer")

        buttons = QHBoxLayout()
        buttons.addWidget(self.history_info_label)
        buttons.addStretch()
        buttons.addWidget(self.delete_entry_button)
        buttons.addWidget(self.clear_history_button)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(splitter)
        layout.addLayout(buttons)
        return tab

    def _build_status_bar(self) -> None:
        """Bottom bar: temporary messages on the left, privacy indicator on the right."""
        self.privacy_label = QLabel()
        # A moving "busy" bar shown while the AI is working. Range (0, 0) means
        # "we don't know how long it will take", so Qt animates it back and forth.
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setMaximumWidth(120)
        self.busy_bar.hide()
        # "Permanent" widgets stay visible; normal status messages appear beside them.
        self.statusBar().addPermanentWidget(self.busy_bar)
        self.statusBar().addPermanentWidget(self.privacy_label)
        self.set_privacy_state(sending=False)
        self.statusBar().showMessage("Ready.")

    def set_privacy_state(self, sending: bool, destination: str = "") -> None:
        """Show clearly whether anything is being sent to an external AI service right now.

        Step 10 calls this with sending=True while a request is in progress.
        """
        if sending:
            self.privacy_label.setText(f"  SENDING to {destination}  ")
            self.privacy_label.setStyleSheet(
                "background: #f0ad4e; color: black; font-weight: bold; border-radius: 3px;"
            )
        else:
            self.privacy_label.setText("  Local only - nothing is being sent  ")
            self.privacy_label.setStyleSheet(
                "background: #3c8d3c; color: white; font-weight: bold; border-radius: 3px;"
            )

    # ------------------------------------------------------------------
    # Signals -> slots
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Tell Qt which method to run when each button is used."""
        # Note: we pass the method itself (no brackets). Qt calls it later.
        self.capture_button.clicked.connect(self.on_capture_clicked)
        self.edit_button.toggled.connect(self.on_edit_toggled)
        self.ask_button.clicked.connect(self.on_ask_clicked)
        self.vision_button.clicked.connect(self.on_vision_clicked)
        self.copy_button.clicked.connect(self.on_copy_clicked)
        self.copy_all_button.clicked.connect(self.on_copy_all_clicked)
        # zoomIn/zoomOut are built into QTextBrowser; the number is how many steps.
        self.bigger_text_button.clicked.connect(lambda: self.explanation_view.zoomIn(1))
        self.smaller_text_button.clicked.connect(lambda: self.explanation_view.zoomOut(1))
        self.clear_history_button.clicked.connect(self.on_clear_history_clicked)
        self.delete_entry_button.clicked.connect(self.on_delete_entry_clicked)
        self.history_search.textChanged.connect(lambda _text: self.refresh_history())  # filter as you type
        # currentItemChanged fires when the selected row changes (mouse or arrow keys).
        self.history_list.currentItemChanged.connect(self.on_history_item_selected)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.settings_button.clicked.connect(self.on_settings_clicked)
        self.always_on_top_checkbox.toggled.connect(self.on_always_on_top_toggled)

    # ---------- Working now ----------

    def on_edit_toggled(self, editing: bool) -> None:
        """Unlock the question box for editing, or lock it again."""
        self.question_edit.setReadOnly(not editing)
        self.edit_button.setText("Done Editing" if editing else "Edit Question")
        if editing:
            self.question_edit.setFocus()  # put the typing cursor in the box
            self.statusBar().showMessage("Editing: fix any OCR mistakes, then click 'Done Editing'.")
        else:
            self.statusBar().showMessage("Question updated.", 3000)  # 3000 ms = 3 seconds

    def on_copy_clicked(self) -> None:
        """Copy only the final answer to the Windows clipboard."""
        if self.current_analysis is None or not self.current_analysis.final_answer:
            self.statusBar().showMessage("Nothing to copy yet.", 3000)
            return
        QGuiApplication.clipboard().setText(self.current_analysis.final_answer)
        self.statusBar().showMessage("Answer copied to clipboard.", 3000)

    def on_copy_all_clicked(self) -> None:
        """Copy the answer AND its explanation, wrong options, steps... as plain text."""
        if self.current_analysis is None:
            self.statusBar().showMessage("Nothing to copy yet.", 3000)
            return
        QGuiApplication.clipboard().setText(to_plain_text(self.current_analysis))
        self.statusBar().showMessage("Answer and explanation copied to clipboard.", 3000)

    def on_always_on_top_toggled(self, on_top: bool) -> None:
        """Keep the window above all other windows (handy while reading the answer)."""
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on_top)
        self.show()  # changing window flags hides the window, so show it again

    # ---------- Screen capture (Step 8) ----------

    def on_capture_clicked(self) -> None:
        self.start_capture()

    def start_capture(self) -> None:
        """Hide this window, then let the user drag a rectangle on the screen."""
        if self._selector is not None:  # a capture is already running: ignore
            return
        if self._ai_busy:  # don't swap the question while the AI is answering it
            self.statusBar().showMessage("Please wait for the AI to finish first.", 3000)
            return
        log.info("Capture started")
        self.hide()  # so the ScreenQA window is not in the screenshot
        # Wait a moment, then open the selector. singleShot runs the method
        # ONCE after the delay, without freezing the program while it waits.
        QTimer.singleShot(CAPTURE_DELAY_MS, self._open_region_selector)

    def _open_region_selector(self) -> None:
        self._selector = RegionSelector(self)
        self._selector.region_selected.connect(self.on_region_selected)
        self._selector.cancelled.connect(self.on_capture_cancelled)
        self._selector.failed.connect(self.on_capture_failed)
        self._selector.start()

    def on_region_selected(self, image: QImage) -> None:
        """The user finished dragging: show the region and start a fresh question."""
        self._end_capture()
        self.current_image = image
        self.preview.set_image(image)

        # A new capture means a new question: clear the old text and answer.
        if self.edit_button.isChecked():
            self.edit_button.setChecked(False)
        self.question_edit.clear()
        self.answer_view.clear()
        self.explanation_view.clear()
        self.current_analysis = None

        # Step 15: keep a copy on disk ONLY if you switched that on in Settings.
        self._current_screenshot_path = None
        if self.settings.save_screenshots:
            try:
                self._current_screenshot_path = str(save_screenshot(image))
            except OSError as error:
                log.error("Could not save the screenshot: %s", error)
                if not self._screenshot_save_warned:  # tell the user once, not on every capture
                    self._screenshot_save_warned = True
                    errors.show_error(self, "Screenshot copy not saved",
                                      f"{errors.friendly_message(error)}\n\nThe question will still be read "
                                      "and answered; only the saved copy is missing.")

        # Step 16: a region that is all one colour has nothing to read. That's
        # usually an empty area, or a window that blocks screenshots.
        if looks_blank(image):
            log.info("Captured region is blank (%dx%d px)", image.width(), image.height())
            self.question_edit.setPlaceholderText(
                "The selected area is all one colour, so there is nothing to read.\n\n"
                "Some programs (video players, secure exam browsers) block screenshots and show up "
                "blank. You can type the question yourself with 'Edit Question'.")
            self.statusBar().showMessage("The captured area looks blank - nothing to read.")
            return

        self._start_ocr(image)  # Step 9: read the text automatically

    def on_capture_cancelled(self) -> None:
        self._end_capture()
        self.statusBar().showMessage("Capture cancelled.", 3000)

    def on_capture_failed(self, message: str) -> None:
        log.error("Capture failed: %s", message)
        self._end_capture()
        errors.show_error(self, "Screen capture failed", message)

    def _end_capture(self) -> None:
        """Forget the selector and bring the ScreenQA window back."""
        if self._selector is not None:
            self._selector.deleteLater()  # let Qt delete it safely once it is idle
            self._selector = None
        self._bring_to_front()

    def _bring_to_front(self) -> None:
        """Show the window in front of everything, un-minimising it if needed."""
        if self.isMinimized():
            # Remove only the "minimised" flag, so a maximised window stays maximised.
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()  # put it in front of other windows
        self.activateWindow()  # and give it keyboard focus

    # ---------- Global keyboard shortcut (Step 13) ----------

    def attach_hotkey(self, hotkey: GlobalHotkey, shortcut: str) -> None:
        """Connect the global shortcut to this window and switch it on."""
        self.hotkey = hotkey
        hotkey.activated.connect(self.on_hotkey_pressed)
        problem = hotkey.register(shortcut)  # None = it worked
        self._show_shortcut_status(shortcut, problem)
        if problem:
            self.statusBar().showMessage(f"Keyboard shortcut not available: {problem}")

    def _show_shortcut_status(self, shortcut: str, problem: str | None) -> None:
        if problem:
            self.shortcut_label.setText(f"Shortcut: <b>{shortcut}</b> "
                                        "<span style='color: #e05050;'>(not available)</span>")
            self.shortcut_label.setToolTip(problem)
        else:
            self.shortcut_label.setText(f"Shortcut: <b>{shortcut}</b> "
                                        "<span style='color: gray;'>(works in any program)</span>")
            self.shortcut_label.setToolTip(f"Press {shortcut} anywhere in Windows to capture a question.")

    def on_hotkey_pressed(self) -> None:
        """The global shortcut was pressed (maybe while another program was in front)."""
        log.info("Global shortcut pressed")
        if self._ai_busy:  # can't start a new capture now; at least show why
            self._bring_to_front()
        self.start_capture()  # it ignores the press if a capture is already running

    # ---------- Reading the text with Windows OCR (Step 9) ----------

    def _start_ocr(self, image: QImage) -> None:
        """Start reading the text in the background."""
        self._ocr_job += 1  # this is now the newest job
        self._set_reading(True)
        self.statusBar().showMessage(
            f"Captured {image.width()} x {image.height()} px. "
            "Reading text with Windows OCR (on this PC - nothing is sent)..."
        )
        # image.copy() gives the background thread its own copy of the picture.
        run_in_background(
            self._ocr_job, read_text, image.copy(),
            on_success=self.on_ocr_finished, on_failure=self.on_ocr_failed,
        )

    def _set_reading(self, busy: bool) -> None:
        """Lock the question controls while OCR runs, so nothing gets overwritten."""
        self.edit_button.setEnabled(not busy)
        self.vision_button.setEnabled(not busy)
        self.ask_button.setEnabled(not busy)
        self.question_edit.setPlaceholderText("Reading text..." if busy else QUESTION_PLACEHOLDER)

    def on_ocr_finished(self, job_id: int, result: OcrResult) -> None:
        if job_id != self._ocr_job:  # result of an older capture: ignore it
            return
        self._set_reading(False)
        if not result.text.strip():
            self.question_edit.setPlaceholderText(
                "No text was found in the selected region.\n"
                "Try a larger or sharper region, or type the question using 'Edit Question'."
            )
            self.statusBar().showMessage("No text found in the selected region.")
            return
        self.question_edit.setPlainText(result.text)
        guess = analyzer.describe_local_guess(result.text)  # e.g. "Looks like: Multiple choice (options a-d)"
        self.statusBar().showMessage(
            f"Read {result.line_count} line(s) in {result.seconds:.2f} s with Windows OCR. "
            f"{guess + '. ' if guess else ''}Check the text - use 'Edit Question' to fix any mistakes."
        )

    def on_ocr_failed(self, job_id: int, error: Exception) -> None:
        if job_id != self._ocr_job:
            return
        self._set_reading(False)
        self.statusBar().showMessage("Could not read the text.")
        errors.show_error(self, "Could not read text",
                          errors.friendly_message(error)
                          + "\n\nYou can still type the question yourself with 'Edit Question'.")

    # ---------- Talking to the AI (Step 10) ----------

    def on_ask_clicked(self) -> None:
        """Send the (checked) question - and the screenshot if ticked - to the AI."""
        question = self.question_edit.toPlainText().strip()
        send_image = self.attach_image_checkbox.isChecked() and self.current_image is not None
        if not question and not send_image:
            QMessageBox.information(
                self, "Nothing to ask",
                "Capture a question first, or type one using 'Edit Question'.",
            )
            return
        if self.edit_button.isChecked():  # finish editing before sending
            self.edit_button.setChecked(False)
        self._send_to_ai(purpose="answer", send_image=send_image)

    def on_vision_clicked(self) -> None:
        """Let the online AI read the screenshot (better for code, math and tables)."""
        if self.current_image is None:
            QMessageBox.information(self, "No screenshot", "Capture a region first.")
            return
        self._send_to_ai(purpose="extract", send_image=True)

    def _send_to_ai(self, purpose: str, send_image: bool) -> None:
        """Common steps for every AI request: consent, privacy indicator, background job.

        purpose="answer":  analyse and answer the question (Step 11, analyzer.py)
        purpose="extract": let the AI read the text in the screenshot (AI Vision)
        """
        provider, model = self.settings.provider, self.settings.model_name
        max_tokens = self.settings.effective_max_tokens()
        temperature = self.settings.effective_temperature()  # None if not set or not supported
        question = self.question_edit.toPlainText().strip()

        # Describe exactly what will leave this PC.
        parts = []
        if purpose == "answer" and question:
            parts.append("the question text")
        if send_image:
            parts.append(f"the selected region ({self.current_image.width()} x "
                         f"{self.current_image.height()} px, not your whole screen)")
        what = " and ".join(parts)

        if not self._confirm_sending(provider, what):
            return

        image_png = to_png_bytes(self.current_image, max_side=AI_IMAGE_MAX_SIDE) if send_image else None
        self._ai_job += 1
        self._set_ai_busy(True, provider, model)
        short = " + ".join(["question" if "question" in what else "", "screenshot" if send_image else ""]).strip(" +")
        self.statusBar().showMessage(f"Sending {short} to {provider.company}... (usually 5-30 s)")

        if purpose == "answer":
            self._question_being_answered = question  # remembered for the history
            run_in_background(
                self._ai_job, analyzer.analyze, question, image_png,
                provider=provider, model=model, max_tokens=max_tokens, temperature=temperature,
                on_success=self.on_analysis_received, on_failure=self.on_ai_failed,
            )
        else:
            run_in_background(
                self._ai_job, ai_client.ask, prompts.EXTRACT_SYSTEM, prompts.EXTRACT_USER, image_png,
                provider=provider, model=model, max_tokens=max_tokens, temperature=temperature,
                on_success=self.on_vision_text_received, on_failure=self.on_ai_failed,
            )

    def _confirm_sending(self, provider: Provider, what: str) -> bool:
        """Ask once per session before sending anything to an online service."""
        if provider.id in self._consent_given:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Send to an online AI service?")
        box.setText(f"ScreenQA is about to send {what} to {provider.label}.")
        box.setInformativeText(
            f"{provider.privacy_note}\n\n"
            "ScreenQA won't ask again until you restart it. The orange SENDING label "
            "at the bottom right always shows when data is being sent."
        )
        send_button = box.addButton("Send", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()  # waits here until the user clicks a button
        if box.clickedButton() is send_button:
            self._consent_given.add(provider.id)
            return True
        self.statusBar().showMessage("Cancelled - nothing was sent.", 3000)
        return False

    def _set_ai_busy(self, busy: bool, provider: Provider | None = None, model: str = "") -> None:
        """Lock the controls and show the orange SENDING label while the AI works."""
        self._ai_busy = busy
        for widget in (self.capture_button, self.edit_button, self.vision_button,
                       self.ask_button, self.attach_image_checkbox):
            widget.setEnabled(not busy)
        self.busy_bar.setVisible(busy)
        if busy:
            self.set_privacy_state(True, f"{provider.company} ({model})")
        else:
            self.set_privacy_state(False)

    def on_analysis_received(self, job_id: int, analysis: Analysis) -> None:
        if job_id != self._ai_job:
            return
        self._set_ai_busy(False)
        self._show_analysis(analysis)
        warnings = f"  {len(analysis.warnings)} warning(s) - see box 4." if analysis.warnings else ""
        self.statusBar().showMessage(
            f"{analysis.type_label} | confidence: {analysis.confidence} | "
            f"{analysis.provider} ({analysis.model}), {analysis.seconds:.1f} s. "
            f"Check it before you use it.{warnings}"
        )
        self._save_to_history(self._question_being_answered, analysis)

    def _show_analysis(self, analysis: Analysis) -> None:
        """Final answer + badges in box 3, all the sections in box 4 (built by render.py)."""
        self.current_analysis = analysis
        self.answer_view.setHtml(answer_html(analysis))
        self.explanation_view.setHtml(explanation_html(analysis))
        self.explanation_view.verticalScrollBar().setValue(0)  # start reading at the top

    def on_vision_text_received(self, job_id: int, response: AIResponse) -> None:
        if job_id != self._ai_job:
            return
        self._set_ai_busy(False)
        self.question_edit.setPlainText(response.text)
        guess = analyzer.describe_local_guess(response.text)
        self.statusBar().showMessage(
            f"Text read by AI Vision ({response.provider}) in {response.seconds:.1f} s. "
            f"{guess + '. ' if guess else ''}Check it, then click 'Ask AI'."
        )

    def on_ai_failed(self, job_id: int, error: Exception) -> None:
        if job_id != self._ai_job:
            return
        self._set_ai_busy(False)
        self.statusBar().showMessage("The AI request failed.")
        errors.show_error(self, "AI request failed", error)

    # ---------- Question history (Step 14) ----------

    def _save_to_history(self, question: str, analysis: Analysis) -> None:
        """Save an answered question. A failure here must never break the answer itself."""
        if self.history is None or not self.settings.save_history:
            return
        try:
            self.history.add(question or "[The question was only in the screenshot]", analysis,
                             screenshot_path=self._current_screenshot_path)
        except HistoryError as error:
            self.statusBar().showMessage(str(error), 6000)
            return
        self.refresh_history()

    def refresh_history(self) -> None:
        """Reload the list on the History tab (keeps the search filter)."""
        self.history_list.clear()
        self.history_detail.clear()
        self.delete_entry_button.setEnabled(False)
        if self.history is None:
            self.history_info_label.setText("History is switched off.")
            self.clear_history_button.setEnabled(False)
            return

        search = self.history_search.text()
        try:
            entries = self.history.list_entries(search=search)
            total = self.history.count()
        except Exception as error:  # e.g. the file is locked by another program
            log.exception("Could not read the history")
            self.history_info_label.setText(f"Could not read the history: {error}")
            return

        for entry in entries:
            first_line = entry.question.strip().splitlines()[0] if entry.question.strip() else ""
            kind = QUESTION_TYPES.get(entry.question_type, "")
            text = (f"{entry.when}   {kind}\n"
                    f"{_shorten(first_line, 70)}\n"
                    f"Answer: {_shorten(entry.final_answer, 60)}")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, entry.id)  # remember which row this is
            self.history_list.addItem(item)

        shown = f"{len(entries)} of {total} shown" if search.strip() else f"{total} saved"
        saving = "" if self.settings.save_history else "Saving is OFF (see Settings). "
        self.history_info_label.setText(f"{saving}{shown} - stored only on this PC ({self.history.path.name})")
        self.history_info_label.setToolTip(str(self.history.path))
        self.clear_history_button.setEnabled(total > 0)

    def on_history_item_selected(self, current: QListWidgetItem | None, _previous=None) -> None:
        """Show the full saved answer for the row the user clicked."""
        self.delete_entry_button.setEnabled(current is not None)
        if current is None or self.history is None:
            return
        found = self.history.get(current.data(Qt.ItemDataRole.UserRole))
        if found is None:  # deleted in the meantime
            self.refresh_history()
            return
        entry, analysis = found
        question = html.escape(entry.question)  # show the question as text, never as HTML
        picture = ""
        if entry.screenshot_path and Path(entry.screenshot_path).exists():  # only if one was saved
            picture = f'<p><img src="{QUrl.fromLocalFile(entry.screenshot_path).toString()}" width="440"></p>'
        self.history_detail.setHtml(
            f'<p style="color: gray;">Asked {html.escape(entry.when)}</p>'
            f'<h3>Question</h3>{picture}<pre style="white-space: pre-wrap;">{question}</pre>'
            f"<h3>Answer</h3>{answer_html(analysis)}"
            f"{explanation_html(analysis)}"
        )

    def on_delete_entry_clicked(self) -> None:
        item = self.history_list.currentItem()
        if item is None or self.history is None:
            return
        self.history.delete(item.data(Qt.ItemDataRole.UserRole))
        self.refresh_history()
        self.statusBar().showMessage("Question deleted from the history.", 3000)

    def on_clear_history_clicked(self) -> None:
        """Delete EVERYTHING - but only after the user confirms."""
        if self.history is None:
            return
        total = self.history.count()
        if total == 0:
            self.statusBar().showMessage("The history is already empty.", 3000)
            return
        answer = QMessageBox.question(
            self, "Clear history?",
            f"Permanently delete all {total} saved question(s) and answer(s)?\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,  # the safe choice is the default
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        deleted = self.history.clear()
        self.history_search.clear()
        self.refresh_history()
        self.statusBar().showMessage(f"History cleared: {deleted} question(s) permanently deleted.", 5000)

    def on_tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is not None and self.tabs.tabText(index) == "History":
            self.refresh_history()  # always show the latest when opening the tab

    # ---------- Settings (Step 15) ----------

    def on_settings_clicked(self) -> None:
        # Switch the global shortcut off while the dialog is open: otherwise pressing
        # it in the "Capture shortcut" box would start a capture instead of recording it.
        if self.hotkey is not None:
            self.hotkey.unregister()
        dialog = SettingsDialog(self.settings, self.history, self)
        saved = dialog.exec() == QDialog.DialogCode.Accepted  # exec() waits until it closes
        self.apply_settings(dialog.result_settings if saved else self.settings, save=saved)

    def apply_settings(self, new: Settings, save: bool = True) -> None:
        """Use new settings: switch the shortcut, then save them to settings.json."""
        old = self.settings
        if self.hotkey is not None:
            problem = self.hotkey.register(new.shortcut)
            if problem and new.shortcut != old.shortcut:
                # The new shortcut can't be used: keep the old one instead.
                QMessageBox.warning(self, "Shortcut not changed", f"{problem}\n\nKeeping {old.shortcut}.")
                new.shortcut = old.shortcut
                problem = self.hotkey.register(old.shortcut)
            self._show_shortcut_status(new.shortcut, problem)
        self.settings = new
        if save:
            try:
                save_settings(new)
            except OSError as error:
                log.exception("Could not save settings")
                errors.show_error(self, "Settings not saved",
                                  f"Could not write the settings file. {errors.friendly_message(error)}\n\n"
                                  "Your changes apply until ScreenQA closes.")
                return
            self.statusBar().showMessage(
                f"Settings saved. AI: {new.provider.label}, model {new.model_name}.", 5000)
        self.refresh_history()


def _shorten(text: str, limit: int) -> str:
    """Cut long text to `limit` characters, adding '...' if it was cut."""
    text = " ".join(text.split())  # also turns line breaks into single spaces
    return text if len(text) <= limit else text[: limit - 3] + "..."
