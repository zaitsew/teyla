# ops — agent guide

This is {{owner}}'s operations root. Everything that is *run* lives here; everything
that is *built* lives in a code repo under `{{code_root}}/`. Sessions launched from
here accumulate their transcripts, memory and learnings against this root; do not
`cd` into a subfolder and relaunch.

## What belongs here

Plans, decisions, playbooks, notes, routine manifests, the wiki of facts, and the
`runs/` output of routines. Prose and small data files. No application code.

## Skill, rule, fact — three different things

**A skill is a procedure** (how do I do this). `.claude/skills/<name>/SKILL.md`,
loaded on demand by its description. Only steps done the same way every time; under
one screen.

**A rule is a constraint** (what must always/never be true). `.claude/rules/*.md`,
path-globbed; one or two sentences; born from a correction. `/teyla:rule` writes one.

**A fact is state** (what is currently true). `NOTES.md` beside the work, or a page
in `wiki/` — rewritten in place, never appended. The wiki-pass skill files facts
there as drafts; the human confirms.

The failure mode: dumping everything into the skill. Split them.

## Where run artifacts go

```
<track>/<task>/
  NOTES.md      # durable state — committed
  teyla.toml    # routines that must run without me + checks I confirm
  runs/         # drafts, logs, generated reports — gitignored
    2026-09-09/
```

If rerunning the routine would regenerate it, it goes in `runs/`. If the next run
must respect it, it goes in `NOTES.md`.

## Skill routing

Skills are flat under `.claude/skills/`. Scope comes from the description: name the
trigger phrases the owner actually says, say what the skill is *not* for, one skill per
artifact type. When no skill matches, do the work, then run `/teyla:harvest <path>`
after the second time — skills are harvested from sessions that happened, never
written speculatively.

## Conventions

- Markdown for everything. Dates in filenames are ISO.
- Never commit secrets or `.env`.
- Commit prose in reasonably sized commits with a real message; the history is a
  record of decisions.
