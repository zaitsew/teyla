# Handover: the practices that travel to a second machine

What moves from one person's setup to another (here: a personal Mac → a corporate laptop
with Claude Code, Codex and Hermes, GitLab instead of GitHub). Each row says where the
practice came from, what `teyla` installs, and what has to be adapted by hand.

| practice | origin | installed by | adapt at work |
|---|---|---|---|
| **The model ladder**: the top model orchestrates, cheaper tiers do volume, say which model did what | POLICY §1 | `teyla policy init` → `~/.agents/POLICY.md` | delete providers you do not have; name the top tier your org licenses |
| **Second opinion across providers** before designs and anything touching money, keys, people's data | POLICY §2 | POLICY.md | Codex via ChatGPT desktop or `codex exec`; if only Claude exists, a fresh Claude session with the diff and no context |
| **Tool ladder**: connector → CLI → browser → computer use, say when you fell | POLICY §3 | POLICY.md | corporate connectors (messaging, Jira/Confluence, Drive) come first; computer use may be disallowed |
| **Ask with a default, never for permission** | POLICY §4 | POLICY.md | — |
| **Blocker protocol**: do everything around it, open the exact page, name the file and line | POLICY §5 | POLICY.md | SSO pages instead of API-key pages |
| **Plug-and-play is done** | POLICY §6 | POLICY.md, `teyla scaffold` | a Confluence page can be the README |
| **Merge rule**: an explicit allowlist or "open the MR and stop" | global CLAUDE.md | `teyla policy init --claude-md --merge-rule "…"` | at work: never merge; MR + stop |
| One PR/MR per unit; merge don't squash; never force-push; never push a diverged main; check before destructive git; never move a worktree | global CLAUDE.md | `--claude-md` | squash may be mandated by the team — then say so in the file |
| **Layout**: flat code root, one ops root, worktrees outside the tree, no harness names in paths, launch from the repo root | global CLAUDE.md, advice A7 | `--claude-md --code-root --ops-root` | `~/work/<repo>` and `~/work-ops` |
| **Secrets**: never committed, never printed; a key seen in chat is rotated | global CLAUDE.md, a hard-coded-key incident | `--claude-md` | corporate vault |
| **Reporting**: unverified claims say so; check what a subagent claims; corrections once | global CLAUDE.md | `--claude-md` | — |
| **Skill / rule / fact split**; skills flat, routed by description; rules from corrections; facts beside the work | ops CLAUDE.md | `teyla policy init --ops-root-init` | — |
| **`runs/` gitignored, `NOTES.md` committed** | ops CLAUDE.md | `--ops-root-init` | — |
| **Harvest after the second manual run**; never a speculative skill | ops CLAUDE.md, harvest skill | plugin skill `harvest`, `teyla harvest` | — |
| **Corrections → rules**: a correction said twice is a rule; capture hook; `/teyla:rule` | Teyla | plugin | mirror rules into AGENTS.md so Codex/Hermes obey them |
| **Facts → wiki**: agent writes drafts, human confirms; stale after 90 days; inbox for the unfileable | Karpathy's LLM-wiki, Teyla | `teyla wiki init`, skill `wiki-pass` | the team's GitLab Wiki is a git repo of .md — same layout, MR as the review |
| **Routines vs checks**: what must run without you vs what you confirm by hand, in `teyla.toml`; a weekly self-report | the "built, not used" finding | `teyla routines`, `teyla routine install` | routines under a corporate scheduler; the plugin's own `teyla.toml` |
| **Session discipline**: one session per unit; split at 5 MB; status check-ins are scripts | advice A3, A4, A7; the retrospective | monitor | — |
| **Model on every subagent**; `inherit` is the expensive default | advice A1 | monitor | — |
| **Governance file is the human's**; A10 flags any session that writes it | the fabricated-quote incident | monitor | the allowlist becomes "the MR approvers" |
| **Memory conventions**: one fact per file with frontmatter, an index of one-liners, never content in the index | Claude Code auto-memory practice | (Claude Code built-in) | — |
| **Data boundary for feedback**: aggregates only, fingerprints not text, pseudonymous projects | reviews of 0.1.0 | `teyla monitor --share`, `teyla feedback` | the only two files that cross the boundary |

What does **not** travel: the merge-approved list itself, the App Store release path, the
personal product manifests, anything with a name in it.

## Updating a second machine

Once Teyla is on a machine, it maintains itself (`docs/MANUAL.md` §4b). The one manual step is the bootstrap from any version before 0.7.0; [`prompts/work-account-update.md`](../prompts/work-account-update.md) is the paste-able version of that step plus the verification.
