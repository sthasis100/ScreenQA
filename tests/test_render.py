"""Tests for render.py: safe HTML, code, math and the 'Copy All' text."""

import pytest

from screenqa import render
from screenqa.analyzer import Analysis


def test_html_from_the_ai_is_shown_as_text():
    assert render.rich("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_bold_and_inline_code():
    assert render.rich("a **b** c") == "a <b>b</b> c"
    assert "x = 1</code>" in render.rich("use `x = 1`")


def test_code_block_keeps_indentation_and_is_escaped():
    html = render.rich("Look:\n```python\nif a < b:\n    print(a)\n```\ndone")
    assert "<pre" in html and "    print(a)" in html and "if a &lt; b" in html


@pytest.mark.parametrize("latex, expected", [
    ("x^2 + 3x - 4 = 0", "x<sup>2</sup> + 3x - 4 = 0"),
    (r"\frac{1}{2}", "1/2"),
    (r"\frac{x+1}{2}", "(x+1)/2"),
    (r"\sqrt{16} = 4", "\u221a16 = 4"),
    (r"a \times b \leq c", "a \u00d7 b \u2264 c"),
    ("x_1 + x_{10}", "x<sub>1</sub> + x<sub>10</sub>"),
    (r"\frac{\sqrt{2}}{2}", "\u221a2/2"),
])
def test_latex_becomes_readable(latex, expected):
    assert render.latex_to_html(latex) == expected


@pytest.mark.parametrize("text, expected", [
    ("so $x^2 = 9$ gives", "so <i>x<sup>2</sup> = 9</i> gives"),
    ("$x = 2$ or $x = 3$", "<i>x = 2</i> or <i>x = 3</i>"),
    ("It costs $5 and $10 later", "It costs $5 and $10 later"),     # money is NOT math
    ("A shirt costs $20. Tax is 5%.", "A shirt costs $20. Tax is 5%."),
])
def test_math_versus_money(text, expected):
    assert render.rich(text) == expected


def test_copy_all_uses_the_classic_layout():
    analysis = Analysis(question_type="multiple_choice", final_answer="b. Stack", explanation="LIFO.",
                        other_choices=[("a. Queue", "FIFO")], confidence="high", parsed_ok=True)
    text = render.to_plain_text(analysis)
    assert text.splitlines()[0] == "Answer: b. Stack"
    assert "Explanation:\nLIFO." in text
    assert "Why the other choices are incorrect:\na. Queue - FIFO" in text


def test_badges_show_type_confidence_and_warnings():
    html = render.answer_html(Analysis(question_type="calculation", final_answer="42", confidence="low",
                                       warnings=["check this"]))
    assert "Calculation / math" in html and "Low confidence" in html and "1 warning(s)" in html
