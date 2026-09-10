# Kickoff prompt for a second machine (paste into Claude Code on the work laptop)

You are setting up how this account works with AI agents, using Teyla — https://github.com/zaitsew/teyla (Apache-2.0, Python 3.11+, stdlib only). Nothing leaves this machine. The only outputs I will carry out by hand are two redacted markdown files. Work autonomously; stop only at a real blocker (a permission, SSO, a tool this laptop cannot install), and when you do, open the exact page and name the exact file and line for me.

## 1. Install Teyla and the operating policy

Follow https://raw.githubusercontent.com/zaitsew/teyla/main/prompts/onboard.md. In short: `uv tool install git+https://github.com/zaitsew/teyla` (fallbacks: `pipx`, or `git clone https://github.com/zaitsew/teyla && PYTHONPATH=src python3 -m teyla`), then `teyla doctor`.

Then create the operating layer in one command, adapting the values:

```
teyla policy init --owner "<my name>" --claude-md --ops-root-init \
  --code-root "~/work" --ops-root "~/work-ops" \
  --merge-rule "Never merge. Open the GitLab MR, then stop and tell me what it changes."
teyla policy sync
```

This writes `~/.agents/POLICY.md` (model ladder, second opinions, tool ladder, ask-with-a-default, blocker protocol, plug-and-play, merge rule), `~/.claude/CLAUDE.md` (shipping rules, layout, secrets, reporting), and `~/work-ops` (skill / rule / fact split, `runs/` ignored). It links the policy into Codex (`~/.codex/AGENTS.md`), Grok and Hermes where they exist. Read https://github.com/zaitsew/teyla/blob/main/docs/HANDOVER.md — it lists every practice and what to adapt — then edit `~/.agents/POLICY.md`: keep only the providers this laptop has and name the top tier for each (the ladder is: the most capable model orchestrates and reviews; cheaper models read, draft and do boilerplate; one cross-provider review before anything touching money, credentials or other people's data). Edit `~/.claude/CLAUDE.md` if the team mandates squash merges or a different layout.

Install the plugin: `claude plugin marketplace add zaitsew/teyla && claude plugin install teyla@teyla` (fallback: clone and `claude plugin marketplace add <path>`). **If there is no `claude` binary on PATH at all** (`command -v claude` finds nothing — Claude runs only as the desktop app, which is the normal case on a managed laptop), both of those are unavailable and so is the fallback. Run `teyla plugin install zaitsew/teyla` instead: it clones the marketplace, copies the plugin into the cache path, and writes the same registry entries `claude plugin install` would, backing up both registry files first; `teyla plugin uninstall teyla` reverses it. It adds `/teyla:rule`, `/teyla:correct`, and the skills harvest, adoption-review and wiki-pass, plus a silent correction-capture hook. Add `AGENTS.md → CLAUDE.md` links to the repos I work in with `teyla policy sync-repo <path>` so Codex and Hermes read the same instructions.

**Codex likely has no CLI here either** — on a machine where every harness is a desktop app, `codex` lives inside the ChatGPT app and is not on PATH, so `codex exec` and `codex review` are unavailable even with a live credential and session history. There is nothing to install for this; the cross-provider review practice falls back to a same-provider review (§2 of `~/.agents/POLICY.md`) — a fresh session of the same harness, only the diff and the question, no prior context, labelled as such.

## 2. First adoption review

`teyla monitor --days 30`. Read the advice (A1–A10: https://github.com/zaitsew/teyla#the-advice-rules). Apply the pure file edits (a `model:` override on subagents, a rule in `.claude/rules/`, an `AGENTS.md` line); list the rest for me with the number that triggered each.

## 3. Review this account's setup and connectors

Follow https://raw.githubusercontent.com/zaitsew/teyla/main/prompts/work-account-plugin-review.md (self-contained, embeds the miner). It audits my internal plugin against the skill / rule / fact test, counts used vs never-used skills, and reports connector use (messaging, Jira/Confluence, Drive) as counts only. Write a `teyla.toml` for the plugin: its routines (what must run without me) and its manual checks (what I confirm). Output: `teyla-work-report.md`.

## 4. The wiki

Read https://github.com/zaitsew/teyla/blob/main/docs/WIKI.md. Clone the team's GitLab wiki (a GitLab Wiki is a git repo of markdown; `git clone <project>.wiki.git ~/work-ops/wiki`). Run `teyla wiki lint` and `teyla wiki status` on it and tell me what the layout needs to fit (index.md, pages/, inbox.md, log.md, page frontmatter with sources and last_verified). Then run the wiki-pass skill on this session's facts. A GitLab wiki repo takes no MR, so use review mode B from docs/WIKI.md: run `teyla wiki lint`, show me `git diff`, and push only after I say so. Agent-written pages are drafts; I confirm or correct.

## 5. Feedback

`teyla feedback` → `teyla-feedback-<date>.md`. Answer the five questions at the end honestly, especially "what a corporate version would need" (SSO, no local logs, GitLab instead of GitHub, a Confluence page instead of a README).

## 6. Hand over

Give me `teyla-work-report.md` and `teyla-feedback-<date>.md` and stop. Both must contain no ticket keys, document titles, names, paths or message text — counts, rates, tool and skill names only. I carry them across by hand; feedback lands at https://github.com/zaitsew/teyla/issues/new?template=feedback.md.

Reference: the method is https://github.com/zaitsew/teyla/blob/main/docs/MANUAL.md; the plugin is https://github.com/zaitsew/teyla/tree/main/plugin.
