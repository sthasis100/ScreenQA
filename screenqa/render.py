"""
render.py - turns an Analysis into something nice to read (Step 12).

  answer_html()      -> box 3: the final answer, big, with coloured badges
  explanation_html() -> box 4: clear sections (explanation, wrong options, steps...)
  to_plain_text()    -> for "Copy All" (and the history in Step 14)

Safety rule: everything the AI wrote is ESCAPED before it goes into HTML
(html.escape turns "<" into "&lt;"), so text like "<b>" or "<script>" in an
answer is shown as text instead of being treated as page formatting.

Qt's text boxes understand a SUBSET of HTML: tables, colours, <b>, <pre>,
<sup>... but not modern CSS like rounded corners or padding on <span>.
That's why the badges below are built with small tables.
"""

import html
import re

from screenqa.analyzer import Analysis

# Badge colours: (background, text). Chosen to be readable in dark AND light mode.
CONFIDENCE_COLORS = {
    "high": ("#2e7d32", "#ffffff"),  # green
    "medium": ("#ef8f00", "#000000"),  # orange
    "low": ("#c62828", "#ffffff"),  # red
    "unknown": ("#616161", "#ffffff"),  # grey
}
TYPE_COLORS = ("#1565c0", "#ffffff")  # blue
WARNING_COLORS = ("#ffd54f", "#000000")  # yellow
MUTED = "#8a8a8a"  # grey text for less important parts
CODE_FONT = "Consolas, 'Courier New', monospace"

FENCED_CODE = re.compile(r"```[\w+#-]*[ \t]*\n?(.*?)```", re.DOTALL)  # ```python ... ```
INLINE_CODE = re.compile(r"`([^`\n]+)`")  # `x = 1`
BOLD = re.compile(r"\*\*(.+?)\*\*")  # **important**
# Math is written between dollar signs: $x^2$ or $$x^2$$. Money must NOT count:
# in "$5 and $10" the second $ has a space BEFORE it, so it can't close math.
# Rule: after the opening $ comes no space; before the closing $ comes no space;
# and the closing $ is not followed by a letter or digit.
DISPLAY_MATH = re.compile(r"\$\$([^$\n]+?)\$\$")
INLINE_MATH = re.compile(r"(?<![\w$\\])\$(?=\S)([^$\n]*?\S)\$(?![\w$])")

# Common LaTeX commands and the symbol to show instead.
LATEX_SYMBOLS = {
    r"\times": "×", r"\cdot": "·", r"\div": "÷", r"\pm": "±", r"\leq": "≤", r"\le": "≤",
    r"\geq": "≥", r"\ge": "≥", r"\neq": "≠", r"\ne": "≠", r"\approx": "≈", r"\infty": "∞",
    r"\pi": "π", r"\theta": "θ", r"\alpha": "α", r"\beta": "β", r"\lambda": "λ", r"\mu": "μ",
    r"\sigma": "σ", r"\Delta": "Δ", r"\to": "→", r"\rightarrow": "→", r"\degree": "°",
    r"\left": "", r"\right": "", r"\,": " ", r"\;": " ", r"\ ": " ",
}


# ======================================================================
# Small building blocks
# ======================================================================

def rich(text: str) -> str:
    """AI text -> safe HTML, keeping code blocks, `code`, **bold** and $math$."""
    parts, position = [], 0
    for block in FENCED_CODE.finditer(text):
        parts.append(_inline(text[position:block.start()]))
        code = html.escape(block.group(1).rstrip("\n"))
        # <pre> keeps every space and line break, so indentation survives.
        parts.append(f'<pre style="font-family: {CODE_FONT}; background-color: rgba(127,127,127,0.18);">'
                     f"{code}</pre>")
        position = block.end()
    parts.append(_inline(text[position:]))
    return "".join(parts)


def _inline(text: str) -> str:
    """Escape ordinary text, then add our few formatting marks back."""
    escaped = html.escape(text, quote=False)
    escaped = INLINE_CODE.sub(lambda m: f'<code style="font-family: {CODE_FONT};">{m.group(1)}</code>', escaped)
    escaped = BOLD.sub(r"<b>\1</b>", escaped)
    escaped = DISPLAY_MATH.sub(lambda m: f"<i>{latex_to_html(m.group(1))}</i>", escaped)
    escaped = INLINE_MATH.sub(lambda m: f"<i>{latex_to_html(m.group(1))}</i>", escaped)
    return escaped.replace("\n", "<br>")


def latex_to_html(expression: str) -> str:
    r"""Make simple LaTeX readable: x^2 -> x², \frac{a}{b} -> a/b, \sqrt{x} -> √x."""
    result = expression
    for _ in range(4):  # repeat a few times so nested ones like \frac{\sqrt{2}}{2} work
        before = result
        result = re.sub(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}",
                        lambda m: f"{_group(m.group(1))}/{_group(m.group(2))}", result)
        result = re.sub(r"\\sqrt\{([^{}]*)\}", lambda m: f"√{_group(m.group(1))}", result)
        result = re.sub(r"\^\{([^{}]*)\}", r"<sup>\1</sup>", result)
        result = re.sub(r"_\{([^{}]*)\}", r"<sub>\1</sub>", result)
        if result == before:
            break
    result = re.sub(r"\^([A-Za-z0-9])", r"<sup>\1</sup>", result)  # x^2
    result = re.sub(r"_([A-Za-z0-9])", r"<sub>\1</sub>", result)  # x_1
    for command in sorted(LATEX_SYMBOLS, key=len, reverse=True):  # longest first: \leq before \le
        result = result.replace(command, LATEX_SYMBOLS[command])
    return result.replace("{", "").replace("}", "")


def _group(part: str) -> str:
    """Add brackets around multi-part pieces: \frac{x+1}{2} -> (x+1)/2, but \frac{1}{2} -> 1/2."""
    return part if re.fullmatch(r"[A-Za-z0-9.√π]+", part) else f"({part})"


def _badge(text: str, colors: tuple[str, str]) -> str:
    background, foreground = colors
    return (f'<td bgcolor="{background}"><span style="color: {foreground}; font-weight: bold; '
            f'font-size: 9pt;">&nbsp;{html.escape(text)}&nbsp;</span></td><td width="6"></td>')


# ======================================================================
# Box 3 and box 4
# ======================================================================

def answer_html(analysis: Analysis) -> str:
    """Box 3: the final answer in large bold text, with badges underneath."""
    answer = rich(analysis.final_answer) if analysis.final_answer else "(no clear answer - see the explanation)"
    badges = _badge(analysis.type_label, TYPE_COLORS)
    badges += _badge(f"{analysis.confidence.title()} confidence", CONFIDENCE_COLORS.get(analysis.confidence,
                                                                                     CONFIDENCE_COLORS["unknown"]))
    if analysis.warnings:
        badges += _badge(f"{len(analysis.warnings)} warning(s)", WARNING_COLORS)
    return (f'<div style="font-size: 16pt; font-weight: bold;">{answer}</div>'
            f'<table cellspacing="0" cellpadding="3" style="margin-top: 8px;"><tr>{badges}</tr></table>')


def explanation_html(analysis: Analysis) -> str:
    """Box 4: every section of the analysis, most important first."""
    sections = []

    if analysis.warnings:  # yellow box at the very top, so it can't be missed
        background, foreground = WARNING_COLORS
        items = "".join(f"<li>{html.escape(w)}</li>" for w in analysis.warnings)
        sections.append(f'<table width="100%" cellpadding="6"><tr><td bgcolor="{background}">'
                        f'<span style="color: {foreground};"><b>Check carefully:</b><ul>{items}</ul></span>'
                        f"</td></tr></table>")

    def section(title: str, body: str, muted: bool = False) -> None:
        color = f' style="color: {MUTED};"' if muted else ""
        sections.append(f"<h3{color}>{title}</h3><div{color}>{body}</div>")

    if analysis.explanation:
        section("Explanation", rich(analysis.explanation))
    if analysis.other_choices:
        items = "".join(f"<li><b>{rich(choice)}</b>" + (f" - {rich(why)}" if why else "") + "</li>"
                        for choice, why in analysis.other_choices)
        section("Why the other choices are incorrect", f"<ul>{items}</ul>")
    if analysis.steps:
        items = "".join(f"<li>{rich(step)}</li>" for step in analysis.steps)
        section("Steps", f"<ol>{items}</ol>")
    if analysis.check:
        section("How the answer was checked", rich(analysis.check))
    if analysis.assumptions:
        items = "".join(f"<li>{rich(a)}</li>" for a in analysis.assumptions)
        section("Assumptions", f"<ul>{items}</ul>")
    if analysis.confidence_reason or analysis.confidence != "unknown":
        section("Confidence", f"<b>{html.escape(analysis.confidence.title())}</b>"
                + (f" - {rich(analysis.confidence_reason)}" if analysis.confidence_reason else ""))
    if not analysis.parsed_ok and not analysis.explanation and analysis.raw_text:
        section("The AI's reply", rich(analysis.raw_text))
    if analysis.working:
        section("The AI's working", rich(analysis.working), muted=True)

    if analysis.provider:
        sections.append(f'<p style="color: {MUTED}; font-size: 8pt;">Answered by {html.escape(analysis.provider)} '
                        f"({html.escape(analysis.model)}) in {analysis.seconds:.1f} s. "
                        "AI answers can be wrong - check before you use them.</p>")
    return "".join(sections)


def to_plain_text(analysis: Analysis) -> str:
    """The whole analysis as plain text, in the classic 'Answer / Explanation' layout."""
    lines = [f"Answer: {analysis.final_answer}",
             f"Type: {analysis.type_label} | Confidence: {analysis.confidence}"
             + (f" ({analysis.confidence_reason})" if analysis.confidence_reason else "")]
    if analysis.warnings:
        lines += ["", "Warnings:"] + [f"- {w}" for w in analysis.warnings]
    if analysis.explanation:
        lines += ["", "Explanation:", analysis.explanation]
    if analysis.other_choices:
        lines += ["", "Why the other choices are incorrect:"]
        lines += [f"{choice} - {why}" if why else choice for choice, why in analysis.other_choices]
    if analysis.steps:
        lines += ["", "Steps:"] + [f"{n}. {step}" for n, step in enumerate(analysis.steps, start=1)]
    if analysis.check:
        lines += ["", f"How it was checked: {analysis.check}"]
    if analysis.assumptions:
        lines += ["", "Assumptions:"] + [f"- {a}" for a in analysis.assumptions]
    if not analysis.parsed_ok and not analysis.explanation and analysis.raw_text:
        lines += ["", analysis.raw_text]
    return "\n".join(lines).strip()
