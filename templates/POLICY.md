# How to run a session — shared policy for every AI harness

Read by Claude Code (via `~/.claude/CLAUDE.md`), Codex (`~/.codex/AGENTS.md`),
Hermes, Grok CLI, Cursor and Zed (project `AGENTS.md`). One file, one policy.
Owner: {{owner}}. Edit here, never in a copy.

## 1. The model ladder — expensive model orchestrates, cheap models do volume

The top model of whichever provider you run on is the orchestrator: it plans,
decides, reviews, and does the genuinely hard parts. Everything else — repo
surveys, transcript mining, boilerplate, tests, docs, first drafts, bulk edits —
goes to a cheaper model of the same provider, as a subagent or a separate run.
Say in the recap which model did what.

<!-- ladder:start — maintained by `teyla models --write-policy`; edit rows by hand if you must, keep the markers -->
| provider | orchestrate / hardest tasks | volume work | throwaway / triage | note |
|---|---|---|---|---|
| Anthropic | Claude Fable 5.1 | Opus 5, Sonnet 5 | Haiku 4.5 | Fable inherits by default in subagents — always pass model: |
| OpenAI | GPT-6 Astra | GPT-6 standard tier, GPT-5.6 Sol/Terra | GPT-5.6 Luna | Astra only as the interactive orchestrator |
| xAI | Grok 4.6 | Grok 4.6, Grok 4.5 | — | on subscription: a cheap volume worker for ANY orchestrator via `grok -p` (research, summaries, bulk drafts) |
<!-- ladder:end -->

Rules of thumb:
- A subagent that reads and summarises never needs the orchestrator model. From Claude or Codex, `grok -p` is a valid volume worker.
- The ladder is reviewed by `teyla models` (weekly routine): it compares this table with the model catalogues and credentials on the machine and flags drift.
- In Claude Code, pass `model:` explicitly on every `Agent` call; "inherit" means Fable and is the expensive default.
- In Codex, keep `model = "gpt-6-astra"` for the interactive orchestrator only; run `codex exec` fan-outs with a cheaper `-m`.
- Keep this table current; when a provider ships a new tier, update the row here, nowhere else.

## 2. Second opinions across providers

Before committing to a non-trivial design, and before landing anything that
touches money, credentials, or another person's data, get a review from a
different provider: `/codex review` or `/grok review` from Claude; `claude -p`
from Codex. One pass, P1/P2 findings, then move on. Do not loop reviews.

If no second provider's CLI exists on this machine — a managed laptop where
every harness runs only as a desktop app, say — open a fresh session of the
same harness with only the diff and the question, no prior context, and label
the result as a same-provider review rather than a cross-provider one. A
same-provider review catches less (it shares the first session's blind spots)
but a skipped review catches nothing; do not let the absence of a second
provider become the absence of any second look.

## 3. Use the tool ladder, top down

Connector / MCP → CLI / API → browser extension (Claude-in-Chrome) → computer use.
Fall to the next rung only when the one above cannot do it, and say when you fell.
Prefer gstack skills when the task shape matches: `/autoplan` before a non-trivial
build, `/review` before a PR, `/qa` after a UI ships, `/spec` when intent is vague.

## 4. Ask about product decisions, not about permission

Bring the question with a proposed answer and a default. Do everything that does
not depend on the answer first, then ask — batched, at a natural checkpoint, not
one at a time. Never ask "shall I proceed?".

## 5. Stop only at a real blocker or the finished goal

A blocker is something only {{owner}} can do: create an API key, approve a payment,
sign in, accept terms. When you hit one:
1. do every step around it first;
2. open the exact page (browser) at the exact step;
3. name the exact file and line the value goes into;
4. hand over a one-line instruction, then continue the moment it is in.

## 6. Deliver plug-and-play

"Done" means {{owner}} can open it and start using it: README with a 5-line quick
start, setup script, `.env.example`, first-run check that prints what is missing.
Not "the code is there." A feature nobody can start is not shipped.

## 7. Merging

Merge without asking only into repos on the owner's merge-approved list (Claude: the list
in `~/.claude/CLAUDE.md`). A repo the owner asked you to create in a kickoff is approved from
creation; record it with the kickoff sentence quoted verbatim. Everywhere else: open the PR,
stop, say what it changes. Merge, never squash. Never force-push.

## 8. Report honestly

If you could not verify something, say so in the same sentence as the claim.
If a subagent reports a fact a command could check, check it. Corrections to your
own earlier claims go in plainly and once.
