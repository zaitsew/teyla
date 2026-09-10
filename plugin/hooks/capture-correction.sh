#!/bin/sh
# UserPromptSubmit: cheap correction-word heuristic, catching what the model
# might not notice mid-turn. Deliberately coarse — it is a broad net over
# obvious correction phrasing, not a classifier, and it errs toward capturing.
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

prompt = data.get("prompt")
if not isinstance(prompt, str):
    sys.exit(0)

cwd = data.get("cwd") or os.getcwd()

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

rec = {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "cwd": cwd,
    "text": prompt[:500],
}

with open(teyla_dir / "corrections.jsonl", "a") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
' 2>/dev/null
} >/dev/null 2>&1

exit 0
