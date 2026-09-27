"""Tests for settings.py, api_keys.py and the Settings window."""

import json

from PySide6.QtGui import QKeySequence

from screenqa import api_keys
from screenqa import settings as st
from screenqa.paths import data_dir, settings_file
from screenqa.settings_dialog import SettingsDialog


def test_saved_settings_load_back_identically():
    original = st.Settings(provider_id="anthropic", model="claude-haiku-4-5", temperature=0.2,
                           max_output_tokens=1200, shortcut="Ctrl+Alt+F10", save_history=False, save_screenshots=True)
    st.save_settings(original)
    assert st.load_settings() == original
    assert "API_KEY" not in settings_file().read_text()  # keys never go into settings.json


def test_damaged_file_gives_defaults():
    settings_file().write_text("{ this is not json", encoding="utf-8")
    assert st.load_settings() == st.Settings()


def test_each_wrong_value_falls_back_to_its_default():
    settings_file().write_text(json.dumps({"provider_id": "nope", "temperature": 5, "max_output_tokens": -5,
                                           "save_history": "yes", "shortcut": 42, "model": None}))
    loaded = st.load_settings()
    assert (loaded.provider_id, loaded.temperature, loaded.max_output_tokens, loaded.save_history,
            loaded.shortcut, loaded.model) == ("groq", None, 0, True, "Ctrl+Shift+Space", "")


def test_first_run_keeps_the_service_chosen_in_step_10():
    api_keys.save_api_key("SCREENQA_PROVIDER", "gemini")
    assert st.load_settings().provider_id == "gemini"


def test_answer_length_limits():
    assert st.Settings(provider_id="groq").effective_max_tokens() == 900  # automatic
    assert st.Settings(provider_id="groq", max_output_tokens=5000).effective_max_tokens() == 900  # capped
    assert st.Settings(provider_id="groq", max_output_tokens=100).effective_max_tokens() == 200  # minimum
    assert st.Settings(provider_id="anthropic").effective_max_tokens() == 16000


def test_temperature_only_where_the_model_accepts_it():
    assert st.Settings(provider_id="groq", temperature=0.2).effective_temperature() == 0.2
    assert st.Settings(provider_id="anthropic", temperature=0.2).effective_temperature() is None  # Opus 5
    assert st.Settings(provider_id="anthropic", model="claude-haiku-4-5", temperature=0.2).effective_temperature() == 0.2


def test_api_keys_save_mask_and_delete():
    api_keys.save_api_key("GROQ_API_KEY", "  gsk_abcdefghijkl1234  ")
    assert api_keys.get_api_key("GROQ_API_KEY") == "gsk_abcdefghijkl1234"
    assert api_keys.key_source("GROQ_API_KEY") == "file"
    assert api_keys.mask("gsk_abcdefghijkl1234") == "gsk_...1234"
    api_keys.delete_api_key("GROQ_API_KEY")
    assert api_keys.get_api_key("GROQ_API_KEY") is None
    assert (data_dir() / ".env").exists()


def test_settings_dialog_follows_the_chosen_service(qapp):
    dialog = SettingsDialog(st.Settings())
    assert dialog.max_tokens_spin.maximum() == 900  # Groq's free limit
    dialog.provider_combo.setCurrentIndex(dialog.provider_combo.findData("anthropic"))
    assert dialog.temperature_check.isEnabled() is False  # Claude Opus 5 has no temperature
    dialog.model_combo.setCurrentText("claude-haiku-4-5")
    assert dialog.temperature_check.isEnabled() is True
    assert dialog.max_tokens_spin.maximum() == 16000


def test_settings_dialog_save(qapp, monkeypatch):
    dialog = SettingsDialog(st.Settings())
    warnings = []
    monkeypatch.setattr("screenqa.settings_dialog.QMessageBox.warning",
                        lambda *args, **kwargs: warnings.append(args[2]))
    dialog.shortcut_edit.setKeySequence(QKeySequence("Shift+A"))
    dialog._on_save()
    assert dialog.result_settings is None and "Ctrl, Alt or Win" in warnings[-1]  # stays open

    dialog.key_edit.setText("gsk_TYPEDfakeKEY")
    dialog.temperature_check.setChecked(True)
    dialog.temperature_spin.setValue(0.2)
    dialog.shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+F10"))
    dialog._on_save()
    result = dialog.result_settings
    assert (result.temperature, result.shortcut) == (0.2, "Ctrl+Alt+F10")
    assert api_keys.get_api_key("GROQ_API_KEY") == "gsk_TYPEDfakeKEY"  # saved to .env
