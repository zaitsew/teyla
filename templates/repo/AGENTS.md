# {{name}} — agent guide

One line: {{name}} is a {{kind}} project, scaffolded plug-and-play from day one.

## How to run / check it

```
./check.sh
```

The one command that says what is missing (env vars, toolchain, tests) and exits
non-zero with a list. Run it before you start, and again before you push.

## Conventions

- **Skills** are procedures: `.claude/skills/<name>/SKILL.md`, loaded on demand.
  **Rules** are constraints from real corrections: `.claude/rules/`, path-globbed.
  **Facts** are state: a `NOTES.md` or `docs/DECISIONS.md` beside the work,
  rewritten in place. Keep the three apart.
- Routine output goes in `runs/` (gitignored, see `routines/README.md`); a
  decision the next run must respect goes in a committed doc.
- Shipping: open the PR and stop unless this repo is named on the merge-approved
  list in `~/.claude/CLAUDE.md`. One PR per logical unit, `gh pr merge --merge`,
  never squash, never force-push.

{{release_section}}

Shared session policy for every harness: `~/.agents/POLICY.md`.
