"""
api_keys.py - loads and saves API keys WITHOUT putting them in the code (Step 10).

Where ScreenQA looks for a key, in this order:
  1. A Windows environment variable (e.g. GEMINI_API_KEY)
  2. The file %APPDATA%\\ScreenQA\\.env

That .env file is outside the project folder, so it can never be uploaded to
GitHub by accident. It is plain text that only your Windows account can read.

Save a key (you paste it, and it is NOT shown on screen):
    python -m screenqa.api_keys
"""

import getpass
import os
import sys
from pathlib import Path

from dotenv import dotenv_values, set_key, unset_key

from screenqa.paths import data_dir


# Step 10 stored the chosen AI service here. Since Step 15 the choice lives in
# settings.json; this is only read once, to carry your earlier choice over.
ACTIVE_PROVIDER_VAR = "SCREENQA_PROVIDER"


def env_file() -> Path:
    """The .env file that stores API keys."""
    return data_dir() / ".env"


def get_active_provider_id() -> str | None:
    """The id of the AI service chosen with the helper (e.g. "groq"), or None."""
    return get_api_key(ACTIVE_PROVIDER_VAR)


def get_api_key(var_name: str) -> str | None:
    """Return the value stored under var_name, or None if there isn't one."""
    value = os.environ.get(var_name)
    if not value and env_file().exists():
        # dotenv_values reads the file into a dictionary WITHOUT changing the
        # environment, and it re-reads the file each time, so a newly saved
        # key works without restarting ScreenQA.
        value = dotenv_values(env_file()).get(var_name)
    value = (value or "").strip().strip('"').strip("'")  # ignore stray spaces/quotes
    return value or None


def save_api_key(var_name: str, value: str) -> None:
    """Store a key in the .env file (replacing any older value)."""
    path = env_file()
    path.touch(exist_ok=True)  # create an empty file if it doesn't exist yet
    set_key(str(path), var_name, value.strip(), quote_mode="never")


def key_source(var_name: str) -> str | None:
    """Where a key comes from: "environment" (a Windows variable), "file" (.env) or None."""
    if os.environ.get(var_name, "").strip():
        return "environment"
    if env_file().exists() and (dotenv_values(env_file()).get(var_name) or "").strip():
        return "file"
    return None


def delete_api_key(var_name: str) -> None:
    """Remove a key from the .env file (a Windows environment variable is not touched)."""
    if env_file().exists() and var_name in dotenv_values(env_file()):
        unset_key(str(env_file()), var_name)


def mask(key: str) -> str:
    """Show only the start and end of a key, e.g. 'AIza...x9Qk'. Never print whole keys."""
    return f"{key[:4]}...{key[-4:]}" if len(key) > 12 else "****"


def main() -> int:
    """A small command-line helper to save a key."""
    from screenqa.providers import PROVIDERS

    providers = list(PROVIDERS.values())
    print("Save an API key for ScreenQA\n")
    for number, provider in enumerate(providers, start=1):
        print(f"  {number}. {provider.label}  - get a key at {provider.key_url}")
    choice = input("\nChoose a number [1]: ").strip() or "1"
    if not choice.isdigit() or not 1 <= int(choice) <= len(providers):
        print("Please run it again and type one of the numbers shown.")
        return 1
    provider = providers[int(choice) - 1]

    # getpass hides what you type/paste, so the key never appears on screen.
    key = getpass.getpass(f"Paste your {provider.company} API key (it stays hidden) and press Enter: ").strip()
    if not key:
        print("Nothing was entered - no changes made.")
        return 1
    save_api_key(provider.key_env_var, key)

    # Use this service from now on (the same choice as in the Settings window).
    from screenqa.settings import load_settings, save_settings

    settings = load_settings()
    settings.provider_id, settings.model = provider.id, ""
    save_settings(settings)
    print(f"\nSaved {provider.key_env_var} = {mask(key)}")
    print(f"ScreenQA will now use: {provider.label}")
    print(f"File: {env_file()}")
    print("Now test it with:  python -m screenqa.ai_client")
    return 0


if __name__ == "__main__":
    sys.exit(main())
