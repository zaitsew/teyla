#!/bin/sh
# UserPromptSubmit: cheap correction-word heuristic, catching what the model
# might not notice mid-turn. Deliberately coarse — it is a broad net over
# obvious correction phrasing, not a classifier, and it errs toward capturing.
#
# UserPromptSubmit: cheap correction-word heuristic, catching what the model
# might not notice mid-turn. Deliberately coarse — it is a broad net over
# obvious correction phrasing, not a classifier, and it errs toward capturing.
#
# Not every prompt is the human typing. Claude Code fires this hook for turns it
# injects itself — a `<task-notification>` when a background subagent finishes, a
# `<system-reminder>`, a `[SYSTEM NOTIFICATION …]`, a slash-command expansion, an
# interrupted request, a continued-session summary — and their boilerplate ("it
# will run again", "don't wait") matches the heuristic. Those are dropped first,
# with the same list `teyla monitor` uses (`is_noise_turn` in src/teyla/adapters).
#
# One script for every harness. `teyla harness sync` copies it to ~/.teyla/hooks/ and
# wires it as Cursor's beforeSubmitPrompt, Grok's UserPromptSubmit and Hermes's
# pre_llm_call shell hook, so the prompt arrives under different keys: Claude Code
# and Cursor send `prompt`, Grok `prompt` in a camelCase envelope with `workspaceRoot`,
# Hermes `extra.user_message`. Grok also loads ~/.cursor/hooks.json, so the same
# prompt can arrive twice — a record equal to the last one within ten seconds is
# not written again.
#
#
# Silent by construction: UserPromptSubmit stdout is injected into the model's
# context, so this hook never writes to stdout, match or no match. It also
# never fails the session — every error path below still exits 0.

{
  python3 -c '
import json, re, sys, os, datetime, pathlib

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

def pick(d):
    for k in ("prompt", "text", "user_message", "userMessage", "message", "input"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v
    ex = d.get("extra")
    return pick(ex) if isinstance(ex, dict) else None

prompt = pick(data)
if not isinstance(prompt, str):
    sys.exit(0)

# Harness-generated turns: not the human typing, never a correction. Same list as
# teyla.adapters.is_noise_turn (NOISE_TAGS / NOISE_PREFIXES); kept inline so the hook
# stays import-free.
HARNESS_TAGS = ("task-notification", "system-reminder", "command-name", "command-message",
                "local-command", "ci-monitor", "ide_")
head = prompt.lstrip()
if head.startswith(("[SYSTEM NOTIFICATION", "[Request interrupted",
                    "This session is being continued from a previous conversation")):
    sys.exit(0)
if head.startswith("<") and any(tag in head[:60] for tag in HARNESS_TAGS):
    sys.exit(0)

cwd = data.get("cwd") or data.get("workspaceRoot") or data.get("workspace_root") or os.getcwd()


PATTERNS = [
    r"\bdon\x27t\b",
    r"\bwrong\b",
    r"\bnot like that\b",
    r"\bagain\b",
    r"\brevert\b",
    r"не так",
    r"неправильно",
    r"опять",
]

if not any(re.search(p, prompt, re.IGNORECASE) for p in PATTERNS):
    sys.exit(0)

teyla_dir = pathlib.Path(cwd) / ".teyla"
teyla_dir.mkdir(parents=True, exist_ok=True)

now = datetime.datetime.now(datetime.timezone.utc)
rec = {
    "ts": now.isoformat(timespec="seconds"),
    "cwd": cwd,
    "text": prompt[:500],
}

out = teyla_dir / "corrections.jsonl"
try:
    last = json.loads(out.read_text().splitlines()[-1])
    if last.get("text") == rec["text"]:
        then = datetime.datetime.fromisoformat(last["ts"])
        if abs((now - then).total_seconds()) < 10:
            sys.exit(0)
except Exception:
    pass

with open(out, "a") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
' 2>/dev/null
} >/dev/null 2>&1

exit 0
