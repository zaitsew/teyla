---
description: Record a correction into .teyla/corrections.jsonl, then propose a rule to promote it
argument-hint: <what was wrong>
---

Record this correction: $ARGUMENTS

## 1. Append the record

Append one JSON line to `.teyla/corrections.jsonl` in the current repo (create
the `.teyla/` directory if it doesn't exist). The record has exactly three
fields: `ts` (UTC ISO-8601, seconds precision), `text` (the argument text
above, verbatim — do not tidy it or generalize it), and `cwd` (this session's
working directory).

```sh
mkdir -p .teyla
python3 - "$PWD" <<'PY'
import json, sys, datetime, pathlib
cwd = sys.argv[1]
text = """$ARGUMENTS"""
rec = {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "text": text,
    "cwd": cwd,
}
with open(pathlib.Path(cwd) / ".teyla" / "corrections.jsonl", "a") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
PY
```

(Substitute the actual argument text for `$ARGUMENTS` when you run this — don't
rely on shell interpolation inside the heredoc to do it for you if the text
contains quotes or newlines; write the Python literal carefully or pass the
text through argv instead.)

## 2. Propose a rule

Draft one candidate rule sentence from the correction — the same in-your-words
standard as `/teyla:rule`: state the constraint, not the reasoning, in
language close to what was actually said. Also propose a scope glob, based on
what kind of work was in progress when the correction happened (default `**`
if nothing narrower is obvious).

## 3. Ask, don't promote

Show the correction as recorded and the proposed rule + scope, then ask
whether to promote it now with `/teyla:rule "<rule text>" --scope <glob>`. Do
not call `/teyla:rule` yourself unless told to — a correction is a data point,
not yet a decision that it generalizes into a standing rule.
