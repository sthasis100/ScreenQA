"""Tests for analyzer.py: finding answer choices, guessing the type, reading AI replies."""

import json

import pytest

from screenqa import analyzer as an


# ---------- finding answer choices ----------

@pytest.mark.parametrize("text, letters", [
    ("Q?\na. IAM Roles\nb. IAM Policies\nc. IAM Users\nd. IAM Groups", "abcd"),
    ("Pick one: A) O(n)  B) O(log n)  C) O(1)", "abc"),                 # on one line
    ("(a) red\n(b) blue\n(c) green", "abc"),                              # (a) style
    ("A. O(n) B. O(log n) C. O(n log n) D. O(1)", "abcd"),                # as OCR joins them
    ("We used Plan A. Then we stopped.", ""),                             # not a list
    ("a. only one", ""),                                                  # one is not a list
    ("Use a tool, e.g. a hammer.", ""),                                   # 'e.g.' is not a choice
])
def test_detect_choices(text, letters):
    assert "".join(letter for letter, _ in an.detect_choices(text)) == letters


def test_choice_text_is_kept():
    assert an.detect_choices("Q?\na. IAM Roles\nb. IAM Policies")[1] == ("b", "IAM Policies")


# ---------- guessing the question type (no AI) ----------

@pytest.mark.parametrize("text, expected", [
    ("Which?\na. x\nb. y", "multiple_choice"),
    ("True or False: The sun is a star.", "true_false"),
    ("The sun is a star.\na. True\nb. False", "true_false"),
    ("What does this print?\nfor i in range(3):\n    print(i)", "programming"),
    ("Calculate the area of a circle with radius 3 cm.", "calculation"),
    ("What is 12 * 7?", "calculation"),
    ("Explain what DNS is.", ""),
])
def test_guess_question_type(text, expected):
    assert an.guess_question_type(text, an.detect_choices(text)) == expected


def test_status_bar_description():
    assert an.describe_local_guess("Q?\na. x\nb. y\nc. z\nd. w") == "Looks like: Multiple choice (options a-d)"


# ---------- reading the AI's reply ----------

GOOD = {
    "question_type": "multiple_choice", "working": "Groups share permissions.", "final_answer": "d. IAM Groups",
    "choice_letters": "d", "explanation": "Groups let you manage teams.",
    "other_choices": [{"choice": "a. IAM Roles", "why_wrong": "for services"}],
    "steps": [], "check": "Re-read the question.", "assumptions": [], "confidence": "Medium",
    "confidence_reason": "Wording is vague.",
}


def test_clean_json():
    result = an.parse_analysis(json.dumps(GOOD))
    assert (result.parsed_ok, result.final_answer, result.confidence) == (True, "d. IAM Groups", "medium")
    assert result.other_choices == [("a. IAM Roles", "for services")]


def test_json_inside_code_fence():
    assert an.parse_analysis("Here:\n```json\n" + json.dumps(GOOD) + "\n```").choice_letters == "d"


def test_text_around_json_and_wrong_types_are_fixed():
    result = an.parse_analysis('Sure! {"final_answer": "42", "question_type": "Calculation", '
                               '"steps": "6*7=42", "explanation": ["It is", "6 times 7."]} Hope that helps')
    assert (result.final_answer, result.question_type, result.steps, result.explanation) == (
        "42", "calculation", ["6*7=42"], "It is 6 times 7.")


def test_cut_off_json_still_gives_the_answer():
    result = an.parse_analysis('{"question_type": "true_false", "final_answer": "True", "explanation": "Because the su')
    assert (result.parsed_ok, result.final_answer, result.question_type) == (False, "True", "true_false")


def test_plain_text_reply_keeps_minus_sign():
    result = an.parse_analysis("**Answer:** -5\n\nExplanation: subtract.")
    assert (result.parsed_ok, result.final_answer) == (False, "-5")


def test_unknown_values_are_normalised():
    result = an.parse_analysis('{"final_answer": "x", "question_type": "essay", "confidence": "very sure"}')
    assert (result.question_type, result.confidence) == ("unknown", "unknown")


def test_numbering_added_by_the_ai_is_removed():
    result = an.parse_analysis('{"final_answer": "4", "steps": ["1. first", "Step 2: second", "3) third"]}')
    assert result.steps == ["first", "second", "third"]


# ---------- ScreenQA's own checks ----------

CHOICES = [("a", "x"), ("b", "y"), ("c", "z"), ("d", "w")]


def warnings_for(**changes):
    result = an.parse_analysis(json.dumps({**GOOD, **changes}))
    an.add_warnings(result, CHOICES)
    return result.warnings


def test_consistent_answer_has_no_warnings():
    assert warnings_for() == []


def test_letter_not_on_screen_is_flagged():
    assert any("only shows options a-d" in w for w in warnings_for(final_answer="e. X", choice_letters="e"))


def test_contradiction_is_flagged():
    assert any("contradicted itself" in w for w in warnings_for(final_answer="b. IAM Policies", choice_letters="d"))


def test_schema_is_valid_for_claude_structured_outputs():
    """Claude requires additionalProperties=false and every key 'required' on every object."""
    def objects(schema):
        if schema.get("type") == "object":
            yield schema
            for child in schema["properties"].values():
                yield from objects(child)
        if schema.get("type") == "array":
            yield from objects(schema["items"])

    for obj in objects(an.ANALYSIS_SCHEMA):
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])
