"""
analyzer.py - turns a question into a checked, structured answer (Step 11).

What happens, in order:
  1. LOCAL guess (on your PC, instant): find answer choices like "a. ... b. ..."
     and guess the question type with simple rules.
  2. The AI gets strict instructions (prompts.ANALYZE_SYSTEM): understand,
     solve, check the answer a second way, and reply as JSON - a fixed format
     with separate parts (answer, explanation, wrong options, steps...).
  3. We read that JSON carefully. If the AI broke the format, we rescue what
     we can instead of failing.
  4. ScreenQA double-checks the result itself (e.g. did the AI pick an option
     letter that actually exists?) and adds warnings for you.
"""

import json
import logging
import re
from dataclasses import dataclass, field

from screenqa import ai_client, prompts
from screenqa.providers import Provider

log = logging.getLogger(__name__)

# The question types, with the names shown to the user.
QUESTION_TYPES = {
    "multiple_choice": "Multiple choice",
    "true_false": "True / False",
    "short_answer": "Short answer",
    "programming": "Programming / code",
    "calculation": "Calculation / math",
    "technical": "Technical question",
}
CONFIDENCE_LEVELS = ("high", "medium", "low")

# The exact reply format we want from the AI, written as a "JSON schema".
# Claude is FORCED to follow it; the other services are asked to in the prompt.
ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "question_type": {"type": "string", "enum": list(QUESTION_TYPES)},
        "working": {"type": "string"},
        "final_answer": {"type": "string"},
        "choice_letters": {"type": "string"},
        "explanation": {"type": "string"},
        "other_choices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"choice": {"type": "string"}, "why_wrong": {"type": "string"}},
                "required": ["choice", "why_wrong"],
                "additionalProperties": False,
            },
        },
        "steps": {"type": "array", "items": {"type": "string"}},
        "check": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
        "confidence_reason": {"type": "string"},
    },
    "required": [
        "question_type", "working", "final_answer", "choice_letters", "explanation",
        "other_choices", "steps", "check", "assumptions", "confidence", "confidence_reason",
    ],
    "additionalProperties": False,
}


@dataclass
class Analysis:
    """Everything we know about one answered question."""

    question_type: str = "unknown"
    working: str = ""  # the AI's brief reasoning
    final_answer: str = ""
    choice_letters: str = ""  # e.g. "b" or "a, c"
    explanation: str = ""
    other_choices: list[tuple[str, str]] = field(default_factory=list)  # (choice, why it's wrong)
    steps: list[str] = field(default_factory=list)
    check: str = ""  # how the AI verified its answer
    assumptions: list[str] = field(default_factory=list)
    confidence: str = "unknown"  # high / medium / low
    confidence_reason: str = ""
    warnings: list[str] = field(default_factory=list)  # added by ScreenQA's own checks
    parsed_ok: bool = False  # True if the AI replied in the expected JSON format
    raw_text: str = ""  # the AI's reply exactly as received
    provider: str = ""
    model: str = ""
    seconds: float = 0.0
    truncated: bool = False

    @property
    def type_label(self) -> str:
        return QUESTION_TYPES.get(self.question_type, "Unknown type")


# ======================================================================
# 1. Local detection (no AI, instant)
# ======================================================================

# An answer-choice marker: "a." "B)" "(c)" "D:" at the start of a line or after a space.
CHOICE_MARKER = re.compile(r"(?:^|(?<=\s))\(?([A-Ha-h])[.):]\s+", re.MULTILINE)
TRUE_FALSE_HINT = re.compile(r"\btrue\s*(?:or|/)\s*false\b|\bT\s*/\s*F\b", re.IGNORECASE)
CODE_HINT = re.compile(
    r"\bdef \w+\(|\bprint\(|#include|public static|console\.log|System\.out|"
    r"\bfor\s*\(|\bwhile\s*\(|\bint \w+\s*=|[{};]\s*$|^\s{4}\S",
    re.MULTILINE,
)
MATH_HINT = re.compile(
    r"\b(calculate|compute|solve|evaluate|simplify|how many|how much|find the value)\b"
    r"|\d\s*[-+*/^=×÷]\s*\d|\$[^$]+\$",
    re.IGNORECASE,
)


def detect_choices(text: str) -> list[tuple[str, str]]:
    """Find answer choices like 'a. IAM Roles'. Returns [('a', 'IAM Roles'), ...].

    Only a run that starts at 'a' and goes a, b, c... in order counts, so
    ordinary sentences like "Plan A. Then..." are not mistaken for choices.
    """
    markers = list(CHOICE_MARKER.finditer(text))
    best: list[re.Match] = []
    for index, first in enumerate(markers):
        if first.group(1).lower() != "a":
            continue
        run = [first]
        for marker in markers[index + 1:]:
            next_letter = chr(ord(run[-1].group(1).lower()) + 1)
            same_case = marker.group(1).isupper() == first.group(1).isupper()
            if marker.group(1).lower() == next_letter and same_case:
                run.append(marker)
        if len(run) > len(best):
            best = run
    if len(best) < 2:  # one "a." on its own is not a list of choices
        return []

    choices = []
    for index, marker in enumerate(best):
        end = best[index + 1].start() if index + 1 < len(best) else len(text)
        option_lines = text[marker.end():end].strip().splitlines()
        choices.append((marker.group(1).lower(), option_lines[0].strip() if option_lines else ""))
    return choices


def guess_question_type(text: str, choices: list[tuple[str, str]]) -> str:
    """A quick rule-based guess. Returns a QUESTION_TYPES key, or "" if unsure."""
    options = {option.lower().rstrip(".") for _, option in choices}
    if (choices and options <= {"true", "false"}) or TRUE_FALSE_HINT.search(text):
        return "true_false"
    if choices:
        return "multiple_choice"
    if CODE_HINT.search(text):
        return "programming"
    if MATH_HINT.search(text):
        return "calculation"
    return ""  # can't tell locally - the AI will decide


def describe_local_guess(text: str) -> str:
    """A short description for the status bar, e.g. 'Looks like: Multiple choice (options a-d)'."""
    choices = detect_choices(text)
    kind = guess_question_type(text, choices)
    if not kind:
        return ""
    description = f"Looks like: {QUESTION_TYPES[kind]}"
    if choices and kind == "multiple_choice":
        description += f" (options {choices[0][0]}-{choices[-1][0]})"
    return description


# ======================================================================
# 2. Asking the AI
# ======================================================================

def analyze(question: str, image_png: bytes | None, *, provider: Provider, model: str,
            max_tokens: int | None = None, temperature: float | None = None) -> Analysis:
    """Ask the AI to analyse and answer the question. Safe to call from a background thread.

    Raises ai_client.AIError if the request itself fails.
    """
    choices = detect_choices(question)
    local_type = guess_question_type(question, choices)
    user_text = prompts.analyze_user_text(question, has_image=image_png is not None,
                                          choice_letters=[letter for letter, _ in choices])

    response = ai_client.ask(prompts.ANALYZE_SYSTEM, user_text, image_png,
                             provider=provider, model=model, json_schema=ANALYSIS_SCHEMA,
                             max_tokens=max_tokens, temperature=temperature)

    analysis = parse_analysis(response.text)
    analysis.provider, analysis.model = response.provider, response.model
    analysis.seconds, analysis.truncated = response.seconds, response.truncated
    add_warnings(analysis, choices)
    log.info("Analysis: type=%s (local guess: %s), confidence=%s, parsed_ok=%s, warnings=%d",
             analysis.question_type, local_type or "none", analysis.confidence,
             analysis.parsed_ok, len(analysis.warnings))
    return analysis


# ======================================================================
# 3. Reading the AI's reply
# ======================================================================

# Finds "Answer: B" / "**Answer:** -5" / "## Final answer: 42" in plain-text replies.
ANSWER_LINE = re.compile(
    r"^[\s*#>_-]*(?:final\s+)?answer[\s*_]*:[\s*_]*(.+)$", re.IGNORECASE | re.MULTILINE
)
STRING_FIELD = r'"{name}"\s*:\s*"((?:[^"\\]|\\.)*)"'  # a "key": "value" pair in JSON text
# Numbering the AI added itself ("1. ", "Step 2: ") - we number the steps ourselves.
STEP_NUMBER = re.compile(r"^\s*(?:step\s*)?\d+\s*[.):]\s*", re.IGNORECASE)


def parse_analysis(text: str) -> Analysis:
    """Turn the AI's reply into an Analysis, coping with imperfect replies."""
    data = _extract_json(text)
    if data is not None:
        analysis = _from_dict(data)
        analysis.parsed_ok = True
    else:
        rescued = _rescue_string_fields(text)  # e.g. JSON that was cut off half-way
        if rescued.get("final_answer"):
            analysis = _from_dict(rescued)
        else:  # not JSON at all: show the reply as it is
            match = ANSWER_LINE.search(text)
            first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
            answer = match.group(1).strip().strip("*").strip() if match else first_line
            analysis = Analysis(final_answer=answer, explanation=text)
    analysis.raw_text = text
    return analysis


def _extract_json(text: str) -> dict | None:
    """Find a JSON object in the reply: the whole reply, a ```json block, or {...}."""
    cleaned = text.strip()
    candidates = [cleaned]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1))
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if 0 <= start < end:
        candidates.append(cleaned[start:end + 1])
    for candidate in candidates:
        try:
            # strict=False tolerates raw line breaks inside strings, which AIs sometimes write.
            value = json.loads(candidate, strict=False)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _rescue_string_fields(text: str) -> dict:
    """Pull out simple "key": "value" pairs from broken JSON."""
    rescued = {}
    for name in ("question_type", "final_answer", "choice_letters", "explanation",
                 "check", "confidence", "confidence_reason", "working"):
        match = re.search(STRING_FIELD.format(name=name), text, re.DOTALL)
        if match:
            try:
                rescued[name] = json.loads(f'"{match.group(1)}"', strict=False)  # undo \n, \" etc.
            except ValueError:
                rescued[name] = match.group(1)
    return rescued


def _from_dict(data: dict) -> Analysis:
    """Copy the fields we know from a dictionary, fixing wrong types along the way."""
    other_choices = []
    for item in _as_list(data.get("other_choices")):
        if isinstance(item, dict):
            other_choices.append((_as_str(item.get("choice")), _as_str(item.get("why_wrong") or item.get("reason"))))
        elif item:
            other_choices.append((_as_str(item), ""))

    question_type = _as_str(data.get("question_type")).lower().replace(" ", "_").replace("/", "_")
    if question_type not in QUESTION_TYPES:
        question_type = "unknown"
    confidence = _as_str(data.get("confidence")).lower()
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "unknown"

    return Analysis(
        question_type=question_type,
        working=_as_str(data.get("working")),
        final_answer=_as_str(data.get("final_answer")),
        choice_letters=_as_str(data.get("choice_letters") or data.get("choice_letter")),
        explanation=_as_str(data.get("explanation")),
        other_choices=other_choices,
        steps=[STEP_NUMBER.sub("", _as_str(step)) for step in _as_list(data.get("steps")) if step],
        check=_as_str(data.get("check")),
        assumptions=[_as_str(a) for a in _as_list(data.get("assumptions")) if a],
        confidence=confidence,
        confidence_reason=_as_str(data.get("confidence_reason")),
    )


def _as_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):  # e.g. an explanation sent as a list of sentences
        return " ".join(_as_str(v) for v in value)
    return str(value).strip()


def _as_list(value) -> list:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


# ======================================================================
# 4. ScreenQA's own checks
# ======================================================================

def add_warnings(analysis: Analysis, choices: list[tuple[str, str]]) -> None:
    """Compare the AI's answer with what ScreenQA saw, and warn about anything odd."""
    warn = analysis.warnings.append
    if analysis.truncated:
        warn("The AI's reply was cut off at the length limit, so parts may be missing.")
    if not analysis.parsed_ok:
        warn("The AI didn't reply in the expected format; some sections may be missing.")
    if not analysis.final_answer:
        warn("The AI did not give a clear final answer.")

    picked = re.findall(r"\b([a-h])\b", analysis.choice_letters.lower())
    shown = [letter for letter, _ in choices]
    if shown and picked and any(letter not in shown for letter in picked):
        warn(f"The AI picked option {', '.join(picked)}, but the question only shows "
             f"options {shown[0]}-{shown[-1]}. Check carefully.")

    # Does the letter in the answer text agree with the chosen letter(s)?
    leading = re.match(r"\s*\(?([a-h])[.):]\s", analysis.final_answer.lower())
    if leading and picked and leading.group(1) not in picked:
        warn(f"The answer text says '{leading.group(1)}' but the AI chose '{', '.join(picked)}'. "
             "The AI contradicted itself - treat this answer with care.")

    if shown and analysis.question_type == "multiple_choice" and not picked and not leading:
        warn("The AI did not name which option letter it chose.")

# (Turning an Analysis into something readable lives in render.py - Step 12.)
