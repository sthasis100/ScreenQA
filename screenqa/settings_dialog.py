"""
settings_dialog.py - the Settings window (Step 15).

A QDialog is a separate window that stays on top of the main window until you
close it. This one doesn't change anything until you click Save: it then puts
the new choices in `result_settings`, and main_window.py applies and saves them.

(The one exception: an API key you paste is written to the .env file when you
click Save, because keys never go into settings.json.)
"""

import logging

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from screenqa import ai_client, api_keys
from screenqa.ai_client import AIResponse
from screenqa.history import HistoryStore, delete_all_screenshots
from screenqa.hotkey import DEFAULT_SHORTCUT, ShortcutError, parse_shortcut
from screenqa.paths import screenshots_dir
from screenqa.providers import PROVIDERS, Provider
from screenqa.settings import MIN_OUTPUT_TOKENS, Settings
from screenqa.workers import run_in_background

log = logging.getLogger(__name__)

NOTE_STYLE = "color: gray;"
GOOD_STYLE = "color: #3c9d3c; font-weight: bold;"
BAD_STYLE = "color: #e05050;"


def _note(text: str = "") -> QLabel:
    """A small grey explanation under a setting."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(NOTE_STYLE)
    return label


def _row(*widgets) -> QWidget:
    """Put several widgets side by side (a form row can only hold one widget)."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        layout.addWidget(widget)
    return container


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, history: HistoryStore | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ScreenQA Settings")
        self.setMinimumWidth(600)
        self._history = history
        self._test_job = 0
        self.result_settings: Settings | None = None  # filled in when you click Save

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_ai_group())
        layout.addWidget(self._build_answer_group())
        layout.addWidget(self._build_shortcut_group())
        layout.addWidget(self._build_privacy_group())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)  # reject() = close without saving
        layout.addWidget(buttons)

        self._load_values(settings)

    # ------------------------------------------------------------------
    # Building the window
    # ------------------------------------------------------------------

    def _build_ai_group(self) -> QGroupBox:
        group = QGroupBox("AI service")
        form = QFormLayout(group)  # a two-column layout: label on the left, control on the right

        self.provider_combo = QComboBox()
        for provider in PROVIDERS.values():
            self.provider_combo.addItem(provider.label, provider.id)  # shown text + hidden id
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)  # you may also type a model name that isn't listed
        self.privacy_note = _note()

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)  # shows dots instead of the key
        self.show_key_button = QPushButton("Show")
        self.show_key_button.setCheckable(True)
        self.key_status = _note()
        self.get_key_link = QLabel()
        self.get_key_link.setOpenExternalLinks(True)  # clicking the link opens your web browser
        self.remove_key_button = QPushButton("Remove saved key")
        self.test_button = QPushButton("Test connection")
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)

        form.addRow("Service:", self.provider_combo)
        form.addRow("Model:", self.model_combo)
        form.addRow("", self.privacy_note)
        form.addRow("API key:", _row(self.key_edit, self.show_key_button))
        form.addRow("", self.key_status)
        form.addRow("", _row(self.get_key_link, self.remove_key_button))
        form.addRow("", _row(self.test_button, self.test_result))

        self.provider_combo.currentIndexChanged.connect(lambda _index: self._on_provider_changed())
        self.model_combo.currentTextChanged.connect(lambda _text: self._update_temperature_state())
        self.show_key_button.toggled.connect(self._on_show_key)
        self.remove_key_button.clicked.connect(self._on_remove_key)
        self.test_button.clicked.connect(self._on_test)
        return group

    def _build_answer_group(self) -> QGroupBox:
        group = QGroupBox("Answers")
        form = QFormLayout(group)

        self.temperature_check = QCheckBox("Use a custom temperature")
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 1.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setDecimals(1)
        self.temperature_note = _note()

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setSingleStep(100)
        self.max_tokens_spin.setSuffix(" tokens")
        # When the value is at its minimum (0), the box shows this text instead of "0".
        self.max_tokens_spin.setSpecialValueText("Automatic (recommended)")
        self.max_tokens_note = _note()

        form.addRow("Temperature:", _row(self.temperature_check, self.temperature_spin))
        form.addRow("", self.temperature_note)
        form.addRow("Maximum answer length:", self.max_tokens_spin)
        form.addRow("", self.max_tokens_note)

        self.temperature_check.toggled.connect(lambda _on: self._update_temperature_state())
        self.max_tokens_spin.valueChanged.connect(lambda _value: self._update_max_tokens_note())
        return group

    def _build_shortcut_group(self) -> QGroupBox:
        group = QGroupBox("Keyboard shortcut")
        form = QFormLayout(group)
        # QKeySequenceEdit records the next key combination you press in it.
        self.shortcut_edit = QKeySequenceEdit()
        self.shortcut_edit.setMaximumSequenceLength(1)  # one combination, not a sequence of them
        reset_button = QPushButton("Reset")
        reset_button.clicked.connect(lambda: self.shortcut_edit.setKeySequence(QKeySequence(DEFAULT_SHORTCUT)))
        form.addRow("Capture shortcut:", _row(self.shortcut_edit, reset_button))
        form.addRow("", _note("Click the box, then press the new key combination. It must include "
                              "Ctrl, Alt or Win. It works in every program while ScreenQA is running."))
        return group

    def _build_privacy_group(self) -> QGroupBox:
        group = QGroupBox("Privacy - what is kept on this PC")
        layout = QVBoxLayout(group)
        self.save_history_check = QCheckBox("Save questions and answers in the History tab")
        self.save_screenshots_check = QCheckBox("Save a copy of each captured region as a picture (PNG)")
        open_folder = QPushButton("Open screenshots folder")
        delete_screenshots = QPushButton("Delete all saved screenshots")
        self.screenshots_info = _note()

        layout.addWidget(self.save_history_check)
        layout.addWidget(self.save_screenshots_check)
        layout.addWidget(_note("Off by default: captured regions are normally kept in memory only and "
                               "forgotten. Saved pictures can contain private information from your screen."))
        layout.addWidget(_row(open_folder, delete_screenshots))
        layout.addWidget(self.screenshots_info)

        open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(screenshots_dir()))))
        delete_screenshots.clicked.connect(self._on_delete_screenshots)
        self._update_screenshots_info()
        return group

    # ------------------------------------------------------------------
    # Filling in and reacting
    # ------------------------------------------------------------------

    def _load_values(self, settings: Settings) -> None:
        self.provider_combo.setCurrentIndex(max(0, self.provider_combo.findData(settings.provider_id)))
        self._on_provider_changed()  # fills the model list for that provider
        self.model_combo.setCurrentText(settings.model_name)
        self.temperature_check.setChecked(settings.temperature is not None)
        self.temperature_spin.setValue(settings.temperature if settings.temperature is not None else 0.2)
        self.max_tokens_spin.setValue(settings.max_output_tokens)
        self.shortcut_edit.setKeySequence(QKeySequence(settings.shortcut))
        self.save_history_check.setChecked(settings.save_history)
        self.save_screenshots_check.setChecked(settings.save_screenshots)
        self._update_temperature_state()
        self._update_max_tokens_note()

    def _provider(self) -> Provider:
        return PROVIDERS[self.provider_combo.currentData()]

    def _model(self) -> str:
        return self.model_combo.currentText().strip() or self._provider().default_model

    def _on_provider_changed(self) -> None:
        provider = self._provider()
        self.model_combo.blockSignals(True)  # don't react while we refill the list
        self.model_combo.clear()
        self.model_combo.addItems(provider.models)
        self.model_combo.blockSignals(False)
        cost = "Free" if provider.free else "Paid"
        self.privacy_note.setText(f"{cost}. Your questions (and screenshots, if you send them) go to "
                                  f"{provider.company}. {provider.privacy_note}")
        self.get_key_link.setText(f'<a href="{provider.key_url}">Get a{" free" if provider.free else "n"} '
                                  f"{provider.company} API key</a>")
        self.key_edit.clear()
        self.test_result.clear()
        self._update_key_status()
        self.max_tokens_spin.setMaximum(provider.max_output_tokens)
        self._update_max_tokens_note()
        self._update_temperature_state()

    def _update_key_status(self) -> None:
        provider = self._provider()
        source = api_keys.key_source(provider.key_env_var)
        key = api_keys.get_api_key(provider.key_env_var)
        if source == "environment":
            self.key_status.setText(f"Using the Windows environment variable {provider.key_env_var} "
                                    f"({api_keys.mask(key)}). Paste a key here to save one in ScreenQA instead.")
        elif source == "file":
            self.key_status.setText(f"A key is saved ({api_keys.mask(key)}). Paste a new one to replace it.")
        else:
            self.key_status.setText("No key saved yet - paste one above.")
        self.key_edit.setPlaceholderText("Paste a new key to replace it" if key else "Paste your API key here")
        self.remove_key_button.setEnabled(source == "file")

    def _update_temperature_state(self) -> None:
        provider, model = self._provider(), self._model()
        supported = provider.supports_temperature(model)
        self.temperature_check.setEnabled(supported)
        self.temperature_spin.setEnabled(supported and self.temperature_check.isChecked())
        if supported:
            self.temperature_note.setText("Lower = more consistent, focused answers (0.2 suits exams); "
                                          "higher = more varied. Unticked = the model's own default.")
        else:
            self.temperature_note.setText(f"{model} doesn't allow changing the temperature, "
                                          "so its built-in setting is always used.")

    def _update_max_tokens_note(self) -> None:
        limit = self._provider().max_output_tokens
        value = self.max_tokens_spin.value()
        if value == 0:
            text = f"Automatic: up to {limit} tokens (about {limit * 3 // 4} words)."
        else:
            used = max(MIN_OUTPUT_TOKENS, value)
            text = f"About {used * 3 // 4} words." + (f" (At least {MIN_OUTPUT_TOKENS} is used.)" if value < MIN_OUTPUT_TOKENS else "")
        self.max_tokens_note.setText(f"{text} A token is about 3/4 of a word. "
                                     f"{self._provider().label} allows at most {limit}.")

    def _update_screenshots_info(self) -> None:
        count = len(list(screenshots_dir().glob("*.png")))
        self.screenshots_info.setText(f"{count} saved screenshot(s) in {screenshots_dir()}")

    def _on_show_key(self, show: bool) -> None:
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password)
        self.show_key_button.setText("Hide" if show else "Show")

    def _on_remove_key(self) -> None:
        provider = self._provider()
        answer = QMessageBox.question(self, "Remove key?",
                                      f"Delete the saved {provider.company} API key from this PC?")
        if answer == QMessageBox.StandardButton.Yes:
            api_keys.delete_api_key(provider.key_env_var)
            self._update_key_status()

    def _on_delete_screenshots(self) -> None:
        answer = QMessageBox.question(self, "Delete screenshots?",
                                      "Permanently delete all saved screenshots? This cannot be undone.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        deleted = delete_all_screenshots()
        if self._history is not None:
            self._history.forget_screenshots()
        self._update_screenshots_info()
        QMessageBox.information(self, "Screenshots deleted", f"{deleted} screenshot(s) deleted.")

    # ---------- "Test connection" ----------

    def _on_test(self) -> None:
        provider, model = self._provider(), self._model()
        typed_key = self.key_edit.text().strip() or None
        if not typed_key and not api_keys.get_api_key(provider.key_env_var):
            self.test_result.setStyleSheet(BAD_STYLE)
            self.test_result.setText("Paste a key first.")
            return
        self._test_job += 1
        self.test_button.setEnabled(False)
        self.test_result.setStyleSheet(NOTE_STYLE)
        self.test_result.setText("Testing... (sends only a tiny test message)")
        run_in_background(
            self._test_job, ai_client.ask, "You are a connection test.", "Reply with exactly the word OK.", None,
            provider=provider, model=model, max_tokens=min(300, provider.max_output_tokens), api_key=typed_key,
            on_success=self._on_test_ok, on_failure=self._on_test_failed,
        )

    def _on_test_ok(self, job_id: int, response: AIResponse) -> None:
        if job_id != self._test_job:
            return
        self.test_button.setEnabled(True)
        self.test_result.setStyleSheet(GOOD_STYLE)
        self.test_result.setText(f"Connected! {response.model} answered in {response.seconds:.1f} s.")

    def _on_test_failed(self, job_id: int, error: Exception) -> None:
        if job_id != self._test_job:
            return
        self.test_button.setEnabled(True)
        self.test_result.setStyleSheet(BAD_STYLE)
        self.test_result.setText(str(error).split("\n\n")[0])  # the first paragraph is the key message

    # ---------- Save ----------

    def _on_save(self) -> None:
        shortcut = self.shortcut_edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        try:
            parse_shortcut(shortcut)  # same check the real registration uses
        except ShortcutError as error:
            QMessageBox.warning(self, "Shortcut not allowed", f"{shortcut or 'No shortcut'}: {error}")
            return  # keep the dialog open so it can be fixed

        provider, model = self._provider(), self._model()
        new_key = self.key_edit.text().strip()
        if new_key:
            api_keys.save_api_key(provider.key_env_var, new_key)
            log.info("API key saved for %s (%s)", provider.company, api_keys.mask(new_key))

        self.result_settings = Settings(
            provider_id=provider.id,
            model="" if model == provider.default_model else model,
            temperature=round(self.temperature_spin.value(), 2) if self.temperature_check.isChecked() else None,
            max_output_tokens=self.max_tokens_spin.value(),
            shortcut=shortcut,
            save_history=self.save_history_check.isChecked(),
            save_screenshots=self.save_screenshots_check.isChecked(),
        )
        if not api_keys.get_api_key(provider.key_env_var):
            QMessageBox.information(self, "No API key yet",
                                    f"There is no {provider.company} API key saved, so 'Ask AI' won't work "
                                    "until you add one here.")
        self.accept()  # accept() = close the dialog and report "Save"
