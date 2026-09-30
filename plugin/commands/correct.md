---
description: Record a correction (scrubbed, outside the repo) with `teyla correct`, then propose a rule to promote it
argument-hint: <what was wrong>
---

Record this correction: $ARGUMENTS

## 1. Record it

Run `teyla correct` with the argument text above, verbatim — do not tidy it or
generalize it. Pass it through a quoted heredoc so quotes and newlines survive:

```sh
teyla correct "$(cat <<'TEYLA_EOF'
<the argument text, verbatim>
TEYLA_EOF
)"
```

It appends `{ts, text, cwd}` to this repo's file under `~/.teyla/corrections/`
— outside the repo, so it can never be committed, with tokens, keys and
`password=`-style values replaced by `[redacted]` — and prints the file and how
many corrections it holds.

If `teyla` is not installed (`command -v teyla || ls ~/.local/bin/teyla`), do
not write the record some other way: say it was not recorded and that
`uv tool install git+https://github.com/zaitsew/teyla` makes this command work.
A hand-written copy would skip the secret scrubber.

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
