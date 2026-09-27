"""
settings.py - your preferences, saved in %APPDATA%\\ScreenQA\\settings.json (Step 15).

JSON is a simple text format; you could even open the file in Notepad.
API keys are NOT stored here: they stay in the separate .env file (Step 10),
so this file never contains secrets.

Loading is forgiving: a missing file, a damaged file, or a wrong value (for
example text where a number should be) never crashes ScreenQA - the default
for that setting is used instead.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from screenqa.hotkey import DEFAULT_SHORTCUT
from screenqa.paths import settings_file
from screenqa.providers import DEFAULT_PROVIDER_ID, PROVIDERS, Provider

log = logging.getLogger(__name__)

MIN_OUTPUT_TOKENS = 200  # shorter than this and answers get cut off


@dataclass
class Settings:
    provider_id: str = DEFAULT_PROVIDER_ID
    model: str = ""  # "" = the provider's recommended model
    temperature: float | None = None  # None = the model's own default
    max_output_tokens: int = 0  # 0 = automatic (the longest the provider allows)
    shortcut: str = DEFAULT_SHORTCUT
    save_history: bool = True
    save_screenshots: bool = False  # privacy: OFF unless you switch it on

    @property
    def provider(self) -> Provider:
        return PROVIDERS.get(self.provider_id, PROVIDERS[DEFAULT_PROVIDER_ID])

    @property
    def model_name(self) -> str:
        return self.model.strip() or self.provider.default_model

    def effective_max_tokens(self) -> int:
        """The answer-length limit to actually use (never above what the provider allows)."""
        limit = self.provider.max_output_tokens
        if self.max_output_tokens <= 0:
            return limit
        return max(MIN_OUTPUT_TOKENS, min(self.max_output_tokens, limit))

    def effective_temperature(self) -> float | None:
        """The temperature to send, or None if it isn't set or the model doesn't accept one."""
        if self.temperature is None or not self.provider.supports_temperature(self.model_name):
            return None
        return self.temperature


def load_settings(path: Path | None = None) -> Settings:
    path = path or settings_file()
    if not path.exists():
        return _first_run_settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("the file does not contain a JSON object")
    except (OSError, ValueError) as error:
        log.error("Could not read %s (%s) - using default settings", path.name, error)
        return Settings()
    return _from_dict(data)


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Write the settings safely: first to a temporary file, then swap it in.

    If the PC crashed half-way through writing, you'd still have the old,
    complete file - never a half-written one.
    """
    path = path or settings_file()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    try:
        os.replace(temporary, path)  # replaces the old file in one step
    except OSError:
        temporary.unlink(missing_ok=True)  # don't leave the temporary file lying around
        raise  # let the caller show the error
    log.info("Settings saved: provider=%s model=%s shortcut=%s history=%s screenshots=%s",
             settings.provider_id, settings.model_name, settings.shortcut,
             settings.save_history, settings.save_screenshots)


def _first_run_settings() -> Settings:
    """Defaults - but keep the AI service chosen with 'python -m screenqa.api_keys' in Step 10."""
    settings = Settings()
    from screenqa import api_keys  # imported here to avoid a circular import

    earlier_choice = api_keys.get_active_provider_id()
    if earlier_choice in PROVIDERS:
        settings.provider_id = earlier_choice
    return settings


def _from_dict(data: dict) -> Settings:
    """Build Settings from the file's data, keeping only values of the right type."""
    defaults = Settings()
    values = {}
    for setting in fields(Settings):
        default = getattr(defaults, setting.name)
        value = data.get(setting.name, default)
        if setting.name == "temperature":
            is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
            valid = value is None or (is_number and 0 <= value <= 2)
            value = float(value) if valid and value is not None else value
        elif isinstance(default, bool):  # check bool BEFORE int: in Python, True is also an int
            valid = isinstance(value, bool)
        elif isinstance(default, int):
            valid = isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else:
            valid = isinstance(value, str)
        if not valid:
            log.warning("Ignoring invalid setting %s=%r; using %r", setting.name, value, default)
        values[setting.name] = value if valid else default
    if values["provider_id"] not in PROVIDERS:
        values["provider_id"] = DEFAULT_PROVIDER_ID
    return Settings(**values)
