"""`teyla design-hint` — the UserPromptSubmit hook that points the model at the drawings-first flow.

POLICY section 16 (2026-11-27): a request for drawings, mockups, concepts or screen redesigns
for review produces standalone static images first. It does not authorise source code, app
builds, simulators, test suites or shipping. This hook reads the prompt and, when it is such a
request, prints up to three lines of context (UserPromptSubmit stdout reaches the model in
Claude Code, Codex and Grok). Silent otherwise, and never fails the session.
"""
from __future__ import annotations

import json
import re
import sys

from . import design_lexicon as lex

DESIGN_ONLY = (
    "Design request: draw standalone static images first (two variants per new screen, full device context incl. bottom navigation).\n"
    "Do not write source, build the app, boot a simulator or run tests unless asked; implementation needs a separate ask.\n"
    "Follow templates/design/STANDARD.md and the product's DESIGN.md (POLICY section 16)."
)
IMPLEMENT_OK = (
    "Design request that also asks for implementation: implementation is authorized.\n"
    "Open one PR per screen or unit; show the static frames for review first if none exist.\n"
    "Follow templates/design/STANDARD.md and the product's DESIGN.md (POLICY section 16)."
)


def _alt(words) -> str:
    return "(?:" + "|".join(words) + ")"


_FLAGS = re.IGNORECASE | re.UNICODE
_B = r"(?<![\w-])"  # no word character before
_E = r"(?![\w])"
_STRONG = re.compile(_B + _alt(lex.DESIGN_STRONG) + _E, _FLAGS)
_DRAW = re.compile(_B + _alt(lex.DRAW_VERBS) + _E + r"(?:\W+\w+){0,5}?\W+" + _alt(lex.UI_NOUNS) + _E, _FLAGS)
_IMPL = re.compile(_B + _alt(lex.IMPLEMENT) + _E, _FLAGS)
_NEG = re.compile(_B + _alt(lex.NEGATION) + r"\W+(?:\w+\W+){0,2}$", _FLAGS)
_PROOF = re.compile(_alt(lex.NOT_DESIGN), _FLAGS)


def is_design_request(prompt: str) -> bool:
    text = _PROOF.sub(" ", prompt)
    return bool(_STRONG.search(text) or _DRAW.search(text))


def wants_implementation(prompt: str) -> bool:
    for m in _IMPL.finditer(prompt):
        if not _NEG.search(prompt[max(0, m.start() - 40):m.start()]):
            return True
    return False


def hint(prompt: str) -> str:
    """The context lines for this prompt, or an empty string."""
    if not prompt or not is_design_request(prompt):
        return ""
    return IMPLEMENT_OK if wants_implementation(prompt) else DESIGN_ONLY


def hook_main(stream=None) -> None:
    """Entry point for plugin/hooks/design-hint.sh. Never raises."""
    try:
        from .adapters import human_text
        from .corrections import _pick, headless
        data = json.load(stream or sys.stdin)
        prompt = _pick(data) if isinstance(data, dict) else None
        if not isinstance(prompt, str) or headless(data):
            return
        out = hint(human_text(prompt.strip()) or "")
        if out:
            sys.stdout.write(out + "\n")
    except BaseException:  # noqa: BLE001 — a hook must never fail the session
        pass


if __name__ == "__main__":
    hook_main()
