# Rules

A rule is a **constraint** — what must always or never be true. It is not a
procedure (that's a skill, in `.claude/skills/`) and not state (that's prose,
next to the work it describes).

Empty for now, by design. Rules are not written in advance — every rule here
should trace back to a correction that actually happened: someone said "no,
not like that" once, and this is where that gets remembered so it doesn't
have to be said twice.

## Shape

One file per rule cluster, named for what it constrains. Frontmatter carries
the path glob that scopes it, so the rule only loads when the work touches
matching files:

```markdown
---
globs: src/**
---

- One or two sentences. State the constraint, not the reasoning.
```

## Writing rules

- **One or two sentences.** The reasoning and history belong in the commit
  message, not the rule.
- **Scope with the narrowest glob that covers it.** A rule globbed to `**`
  loads on every task and gets ignored along with everything else that
  always loads.
- **Say what to do, not just what to avoid.** "Don't be sloppy" is
  unactionable; a concrete, checkable instruction isn't.
- **One correction, one rule.** Don't bundle two into one file.
