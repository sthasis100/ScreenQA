"""Tests for ai_client.py, using a pretend AI service on this PC (no real requests)."""

import dataclasses

import pytest

from screenqa import ai_client
from screenqa.ai_client import AIError
from screenqa.providers import CLAUDE, GROQ
from tests.fake_ai_server import error, reply

KEY = "gsk_TESTkeyNOTreal"


def first_line_of_result(fake_ai, *responses, **options) -> str:
    """Ask the fake service; return "OK" or the first line of the error message."""
    fake_ai.respond(*responses)
    try:
        ai_client.ask("system", "What is 7 x 6?", provider=fake_ai.provider, model="m", api_key=KEY, **options)
        return "OK"
    except AIError as problem:
        return str(problem).split("\n")[0]


# Each row: what the service answers -> how the message must start.
@pytest.mark.parametrize("response, message_start", [
    (error(401, "Invalid API Key", "invalid_api_key"), "Groq rejected your API key"),
    (error(429, "Rate limit reached", headers={"retry-after": "0"}), "You've reached Groq's free-tier limit."),
    (error(413, "Request too large on tokens per minute (TPM)"), "Groq's free plan only handles a limited amount"),
    (error(500, "oops", headers={"retry-after": "0"}), "Groq's service is having problems right now (error 500)"),
    (error(404, "model not found"), "Groq doesn't recognise the model 'm'"),
    (error(400, "image too large"), "Groq could not process this request (error 400)"),
    (reply(""), "The AI sent back an empty answer."),
    (reply("", finish="length"), "The AI ran out of space before it finished answering."),
    ((200, "<html>Service unavailable</html>", {}, 0), "Unexpected problem while contacting Groq"),
])
def test_service_problems_become_friendly_messages(fake_ai, response, message_start):
    assert first_line_of_result(fake_ai, response).startswith(message_start)


def test_a_normal_answer(fake_ai):
    fake_ai.respond(reply("42"))
    response = ai_client.ask("s", "q", provider=fake_ai.provider, model="m", api_key=KEY)
    assert (response.text, response.truncated) == ("42", False)


def test_thinking_tags_are_removed(fake_ai):
    fake_ai.respond(reply("<think>let me see...</think>\nAnswer: 42"))
    assert ai_client.ask("s", "q", provider=fake_ai.provider, model="m", api_key=KEY).text == "Answer: 42"


def test_missing_key_points_to_settings():
    with pytest.raises(AIError, match="Click Settings, paste the key"):
        ai_client.ask("s", "q", provider=GROQ, model=GROQ.default_model)


def test_no_connection():
    offline = dataclasses.replace(GROQ, base_url="http://127.0.0.1:9/v1")  # nothing listens on port 9
    with pytest.raises(AIError, match="Could not connect to Groq"):
        ai_client.ask("s", "q", provider=offline, model="m", api_key=KEY)


def test_timeout(fake_ai, monkeypatch):
    monkeypatch.setattr(ai_client, "REQUEST_TIMEOUT_SECONDS", 1)
    assert first_line_of_result(fake_ai, (*reply("late")[:3], 3)) == \
        "Groq took too long to answer (over 1 seconds). Please try again."


def test_groq_json_failure_is_retried_without_json_mode(fake_ai):
    result = first_line_of_result(fake_ai, error(400, "Failed to generate JSON", "json_validate_failed"),
                                  reply('{"final_answer": "42"}'), json_schema={"type": "object"})
    assert result == "OK"
    assert "response_format" in fake_ai.requests[0] and "response_format" not in fake_ai.requests[1]


def test_temperature_and_answer_length_are_sent(fake_ai):
    fake_ai.respond(reply("OK"))
    ai_client.ask("s", "q", provider=fake_ai.provider, model="m", api_key=KEY, temperature=0.3, max_tokens=500)
    assert (fake_ai.requests[0]["temperature"], fake_ai.requests[0]["max_tokens"]) == (0.3, 500)
    fake_ai.respond(reply("OK"))
    ai_client.ask("s", "q", provider=fake_ai.provider, model="m", api_key=KEY)
    assert "temperature" not in fake_ai.requests[0]


def test_screenshot_is_sent_as_a_picture(fake_ai):
    fake_ai.respond(reply("OK"))
    ai_client.ask("s", "q", b"\x89PNG fake", provider=fake_ai.provider, model="m", api_key=KEY)
    parts = fake_ai.requests[0]["messages"][1]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_claude_request_shape(monkeypatch):
    """Claude: temperature only for Haiku, and the JSON format request (checked with a fake client)."""
    import anthropic

    captured = {}

    class FakeClaude:
        def __init__(self, **kwargs):
            self.messages = self.beta = self

        def create(self, **kwargs):
            captured.update(kwargs)
            block = type("Block", (), {"type": "text", "text": "OK"})()
            return type("Reply", (), {"stop_reason": "end_turn", "content": [block]})()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClaude)
    ai_client.ask("s", "q", provider=CLAUDE, model="claude-haiku-4-5", api_key=KEY, temperature=0.4,
                  json_schema={"type": "object"})
    assert captured["temperature"] == 0.4
    assert captured["output_config"]["format"]["type"] == "json_schema"
