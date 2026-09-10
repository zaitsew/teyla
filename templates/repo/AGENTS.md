# {{name}} — agent guide

One line: {{name}} is a {{kind}} project, scaffolded plug-and-play from day one.

## How to run / check it

```
./check.sh
```

That is the one command that tells you what is missing (env vars, toolchain,
tests) and exits non-zero with a clear list if something is wrong. Run it
before you start, and again before you push.

## Skill, rule, fact — three different things

- **A skill is a procedure.** It answers *how do I do this*. It lives in
  `.claude/skills/<name>/SKILL.md`, loaded on demand when its description
  matches the task.
- **A rule is a constraint.** It answers *what must always/never be true*. It
  lives in `.claude/rules/`, path-globbed, and comes from a correction that
  actually happened — see `.claude/rules/README.md`.
- **A fact is state.** It answers *what is currently true right now*. It goes
  in prose next to the work it describes (a `NOTES.md`, `docs/DECISIONS.md`),
  and gets rewritten in place, not appended to.

Don't dump a constraint into a skill or a procedure into a rule file — each
only fires, or only stays followable, when it lives in its own shape.

## Where run artifacts go

Every routine writes into `runs/`, gitignored on purpose:

```
routines/
  README.md        # the routine schema
  example.yml       # copy this, don't edit it
runs/               # drafts, logs, generated output — gitignored, never committed
```

If rerunning the routine would regenerate a file, it goes in `runs/`. If it is
a decision the next run must respect, it goes in a committed doc instead.

## Shipping

Open the PR, then stop and say what it changes, why, and who owns the repo.
**Do not merge without asking** unless this repo is explicitly named on the
merge-approved list in `~/.claude/CLAUDE.md` — that list is the whole
permission, checked at merge time, not inferred from write access or a green
CI run. One PR per logical unit. Merge commits (`gh pr merge --merge`), never
squash, never force-push.

{{release_section}}

## Shared policy

Read `~/.agents/POLICY.md` — the model ladder, the tool ladder, when to ask
vs. act, and what "done" means (plug-and-play: README, setup, `.env.example`,
first-run check). One policy, every harness, edited only there.
