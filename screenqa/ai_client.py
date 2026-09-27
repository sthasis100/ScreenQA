"""
ai_client.py - sends a question (and optionally a screenshot) to an AI service (Step 10).

This is the ONLY file that talks to the internet. The window never does.

Three "styles" of service are supported (see providers.py):
  * Google Gemini      -> Google's official `google-genai` library
  * Anthropic Claude   -> Anthropic's official `anthropic` library
  * OpenAI-compatible  -> the `openai` library (for other services, later)

Test your connection on its own:
    python -m screenqa.ai_client                      (a tiny text question)
    python -m screenqa.ai_client C:\\path\\picture.png  (AI Vision on a picture)
"""

import base64
import logging
import re
import time
from dataclasses import dataclass

from screenqa import api_keys
from screenqa.providers import Provider

log = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 120  # give up on one attempt after 2 minutes
MAX_RETRIES = 1  # retry once on network hiccups / "busy" errors, then report

# Some models "think out loud" inside <think>...</think> before answering.
# We remove that part so only the real answer is shown.
THINK_BLOCK = re.compile(r"<think>.*?(</think>|$)", re.DOTALL | re.IGNORECASE)

# Claude models that get Anthropic's recommended "fallbacks" option: if the
# model declines a request, Anthropic's server retries it on a suitable model.
CLAUDE_FALLBACK_MODELS = {"claude-opus-5"}


class AIError(Exception):
    """An AI problem we can explain to the user in plain English."""


@dataclass
class AIResponse:
    text: str
    provider: str  # e.g. "Google Gemini (free tier)"
    model: str
    seconds: float
    truncated: bool  # True if the answer was cut off at the maximum length


def active_provider() -> tuple[Provider, str]:
    """Which provider and model are chosen in Settings (used by the command-line test)."""
    from screenqa.settings import load_settings  # imported here to avoid a circular import

    settings = load_settings()
    return settings.provider, settings.model_name


def ask(
    system_prompt: str,
    user_text: str,
    image_png: bytes | None = None,
    *,
    provider: Provider,
    model: str,
    max_tokens: int | None = None,
    json_schema: dict | None = None,
    temperature: float | None = None,
    api_key: str | None = None,
) -> AIResponse:
    """Send one question and return the answer. Safe to call from a background thread.

    json_schema: if given, ask the service to reply with JSON in that shape
                 (each service supports this a little differently - see below).
    temperature: None = the model's default. Lower = more consistent answers.
    api_key:     use this key instead of the saved one (Settings' "Test connection").

    Raises AIError with a friendly message when anything goes wrong.
    """
    max_tokens = max_tokens or provider.max_output_tokens  # each service has its own limit
    key = api_key or api_keys.get_api_key(provider.key_env_var)
    if not key:
        raise AIError(
            f"No API key found for {provider.label}.\n\n"
            f"1. Get a key at {provider.key_url}\n"
            "2. Click Settings, paste the key into 'API key' and click Save."
        )

    # Log WHAT kind of data is sent and where - never the key, never the text itself.
    image_note = f" + a {len(image_png) // 1024} KB image" if image_png else ""
    log.info("Sending %d characters of text%s to %s (%s)", len(user_text), image_note, provider.company, model)

    started = time.perf_counter()
    try:
        request = (key, provider, system_prompt, user_text, image_png, model, max_tokens, json_schema, temperature)
        if provider.api_style == "gemini":
            text, truncated = _ask_gemini(*request)
        elif provider.api_style == "anthropic":
            text, truncated = _ask_anthropic(*request)
        else:
            text, truncated = _ask_openai_style(*request)
    except AIError:
        raise
    except Exception as error:  # turn library errors into friendly messages
        raise _friendly_error(error, provider, model) from error
    seconds = time.perf_counter() - started

    if not text.strip():
        if truncated:  # it used up the whole length limit while still thinking
            raise AIError("The AI ran out of space before it finished answering.\n\n"
                          "Try a smaller region or a shorter question.")
        raise AIError("The AI sent back an empty answer. Please try again.")
    log.info("Answer received from %s in %.1f s (%d characters, truncated=%s)",
             provider.company, seconds, len(text), truncated)
    return AIResponse(text=text.strip(), provider=provider.label, model=model,
                      seconds=seconds, truncated=truncated)


def _ask_gemini(key, provider, system_prompt, user_text, image_png, model, max_tokens, json_schema, temperature):
    """Send the request to Google Gemini with Google's official library.

    Works with both kinds of Google key: the newer "AQ." keys and older "AIza..." keys.
    """
    import ssl

    import truststore
    from google import genai  # imported here so the app starts even if it is missing
    from google.genai import types

    # Trust the same certificates Windows trusts. By default this library only
    # trusts Python's built-in list, which fails when antivirus software (e.g.
    # Avast Web Shield) or a school/work network inspects secure connections.
    windows_trust = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    client = genai.Client(
        api_key=key,
        http_options=types.HttpOptions(
            base_url=provider.base_url,  # None = Google's normal address
            timeout=REQUEST_TIMEOUT_SECONDS * 1000,  # careful: this library counts in MILLISECONDS
            retry_options=types.HttpRetryOptions(attempts=1 + MAX_RETRIES),  # first try + retries
            client_args={"verify": windows_trust},
        ),
    )

    # "contents" is a list of parts: the picture (if any) and then the text.
    contents = []
    if image_png:
        contents.append(types.Part.from_bytes(data=image_png, mime_type="image/png"))
    contents.append(user_text)

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,  # the standing instructions
            max_output_tokens=max_tokens,  # maximum answer length
            temperature=temperature,  # None = Gemini's default
            # Gemini's "JSON mode": the reply is always valid JSON.
            response_mime_type="application/json" if json_schema else None,
            # We give the AI no tools to call, so switch that feature off.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )

    # Google can block a request (prompt_feedback) or stop an answer (finish_reason).
    feedback = response.prompt_feedback
    if feedback is not None and feedback.block_reason:
        reason = getattr(feedback.block_reason, "name", feedback.block_reason)
        raise AIError(f"Google's safety filter blocked this request ({reason}).")
    finish = response.candidates[0].finish_reason if response.candidates else None
    blocked = {types.FinishReason.SAFETY, types.FinishReason.PROHIBITED_CONTENT,
               types.FinishReason.BLOCKLIST, types.FinishReason.IMAGE_SAFETY, types.FinishReason.SPII}
    if finish in blocked:
        raise AIError("Google's safety filter blocked the answer.")
    return response.text or "", finish == types.FinishReason.MAX_TOKENS


def _ask_openai_style(key, provider, system_prompt, user_text, image_png, model, max_tokens, json_schema,
                      temperature):
    """Send the request to an OpenAI-compatible service (e.g. Groq)."""
    import openai  # imported here so the app starts even if it is missing

    client = openai.OpenAI(api_key=key, base_url=provider.base_url,
                           timeout=REQUEST_TIMEOUT_SECONDS, max_retries=MAX_RETRIES)

    # A message can hold several "parts": here some text and (optionally) a picture.
    content = [{"type": "text", "text": user_text}]
    if image_png:
        # Pictures travel inside the request as base64 text: a "data URL".
        encoded = base64.b64encode(image_png).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}})

    request = dict(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        max_tokens=max_tokens,
        **provider.extra_options,  # service-specific settings, e.g. Groq's reasoning_effort
    )
    if temperature is not None:
        request["temperature"] = temperature
    if json_schema:
        # "JSON mode": the service makes sure the reply is valid JSON. (The exact
        # keys are described in the prompt, since not every service accepts a schema.)
        request["response_format"] = {"type": "json_object"}

    try:
        response = client.chat.completions.create(**request)
    except openai.BadRequestError as error:
        # Groq refuses to send a reply that isn't perfect JSON ("json_validate_failed").
        # Try once more without JSON mode - analyzer.py can cope with almost-JSON.
        if "response_format" in request and "json_validate_failed" in str(error):
            log.warning("%s could not produce valid JSON; retrying without JSON mode", provider.company)
            del request["response_format"]
            response = client.chat.completions.create(**request)
        else:
            raise
    if not response.choices:
        raise AIError("The AI service sent back no answer. Please try again.")
    choice = response.choices[0]
    if choice.finish_reason == "content_filter":
        raise AIError(f"{provider.company}'s safety filter blocked this request.")
    text = THINK_BLOCK.sub("", choice.message.content or "")
    return text, choice.finish_reason == "length"


def _ask_anthropic(key, provider, system_prompt, user_text, image_png, model, max_tokens, json_schema,
                   temperature):
    """Send the request to Anthropic's Claude."""
    import anthropic

    client = anthropic.Anthropic(api_key=key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=MAX_RETRIES)

    content = []
    if image_png:  # Claude works best with the picture BEFORE the text
        encoded = base64.standard_b64encode(image_png).decode("utf-8")
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": encoded}})
    content.append({"type": "text", "text": user_text})

    request = dict(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": content}],
    )
    if temperature is not None:  # only sent for models that accept it (see providers.py)
        request["temperature"] = temperature
    if json_schema:
        # "Structured outputs": Claude is guaranteed to reply with JSON in exactly this shape.
        request["output_config"] = {"format": {"type": "json_schema", "schema": json_schema}}
    if model in CLAUDE_FALLBACK_MODELS:
        response = client.beta.messages.create(
            **request, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
        )
    else:
        response = client.messages.create(**request)

    if response.stop_reason == "refusal":
        raise AIError("Claude declined to answer this request.")
    # The reply is a list of "blocks"; we only want the text blocks.
    text = "".join(block.text for block in response.content if block.type == "text")
    return text, response.stop_reason == "max_tokens"


def _classify(error: Exception) -> tuple[str, int | None, str]:
    """Sort an error from ANY of the three libraries into one of a few kinds.

    Returns (kind, HTTP status code or None, the library's own message).
    """
    import anthropic
    import httpx  # the web library google-genai uses underneath
    import openai
    from google.genai import errors as google_errors

    def is_a(name: str) -> bool:  # openai and anthropic use the same error class names
        return isinstance(error, (getattr(openai, name), getattr(anthropic, name)))

    detail = getattr(error, "message", None) or str(error)
    if isinstance(error, google_errors.APIError):
        status = error.code  # Google's library calls the HTTP status "code"
    else:
        status = getattr(error, "status_code", None)
    words = f"{getattr(error, 'status', '')} {detail}".lower()

    # Timeouts first: a timeout is also a kind of connection error.
    if is_a("APITimeoutError") or isinstance(error, httpx.TimeoutException):
        return "timeout", status, detail
    if is_a("APIConnectionError") or isinstance(error, httpx.TransportError):
        return "connection", status, detail
    if status in (401, 403) or any(w in words for w in ("api key", "auth key", "unauthenticated")):
        return "bad_key", status, detail
    # Groq: over a per-minute token allowance ("Request too large ... tokens per minute")
    if status == 413 or "request too large" in words or "tokens per minute" in words:
        return "too_large", status, detail
    if status == 429 or "resource_exhausted" in words:
        return "rate_limit", status, detail
    if status == 404:
        return "not_found", status, detail
    if status and status >= 500:
        return "server", status, detail
    if status:
        return "bad_request", status, detail
    return "unknown", status, detail


def _friendly_error(error: Exception, provider: Provider, model: str) -> AIError:
    """Translate a library error into a message a person can act on."""
    kind, status, detail = _classify(error)
    company = provider.company
    log.error("AI request to %s (%s) failed [%s]: %s (status %s): %s",
              company, model, kind, type(error).__name__, status, detail)

    if kind == "timeout":
        return AIError(f"{company} took too long to answer (over {REQUEST_TIMEOUT_SECONDS} seconds). Please try again.")
    if kind == "connection":
        return AIError(f"Could not connect to {company}.\n\nCheck your internet connection "
                       "(and any VPN or firewall), then try again.")
    if kind == "bad_key":
        return AIError(f"{company} rejected your API key ({detail.strip()}).\n\n"
                       "Make sure you copied the whole key, then paste it again in Settings "
                       "(use 'Test connection' to check it).\n\n"
                       f"If it still fails, create a new key at {provider.key_url} and save that one.")
    if kind == "too_large":
        return AIError(f"{company}'s free plan only handles a limited amount of text per minute, "
                       "and that allowance is used up for now.\n\n"
                       "Wait about a minute and try again. If it keeps happening, select a smaller "
                       "region or untick 'Send screenshot with question'.")
    if kind == "rate_limit":
        if provider.free:
            return AIError(f"You've reached {company}'s free-tier limit.\n\nThe free tier allows only a "
                           "limited number of requests per minute and per day. Wait a minute and try "
                           "again. If it keeps happening, today's limit is used up; it resets tomorrow.")
        return AIError(f"{company} says too many requests (or your account is out of credit). "
                       "Wait a minute and try again, or check your billing page.")
    if kind == "not_found":
        return AIError(f"{company} doesn't recognise the model '{model}'. It may have been renamed or retired.")
    if kind == "server":
        return AIError(f"{company}'s service is having problems right now (error {status}). Try again shortly.")
    if kind == "bad_request":
        return AIError(f"{company} could not process this request (error {status}):\n{detail}")
    return AIError(f"Unexpected problem while contacting {company}: {error}")


# ----------------------------------------------------------------------
# Run this file directly to test the AI connection on its own.
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    from PySide6.QtGui import QImage

    from screenqa.imaging import to_png_bytes
    from screenqa.prompts import EXTRACT_SYSTEM, EXTRACT_USER

    chosen, chosen_model = active_provider()
    print(f"Testing {chosen.label} with model {chosen_model} ...")
    print(f"(This sends a small test request to {chosen.company}.)\n")
    try:
        if len(sys.argv) > 1:
            picture = QImage(sys.argv[1])
            if picture.isNull():
                print(f"Could not open the picture: {sys.argv[1]}")
                sys.exit(1)
            result = ask(EXTRACT_SYSTEM, EXTRACT_USER, to_png_bytes(picture, max_side=2000),
                         provider=chosen, model=chosen_model)
        else:
            result = ask("You are a helpful assistant.", "What is 7 x 6? Reply with only the number.",
                         provider=chosen, model=chosen_model)
    except AIError as problem:
        print(f"PROBLEM: {problem}")
        sys.exit(1)
    print(result.text)
    print(f"\n--- OK: {result.provider} / {result.model} answered in {result.seconds:.1f} s")
