# How to run a session — shared policy for every AI harness

Read by Claude Code, Codex, Hermes, Grok CLI, Cursor and Zed. One file, one policy.
Owner: {{owner}}. Edit here, never in a copy.

<!-- teyla-template: work — code on this machine goes only to AI providers IT approved for it -->

## 1. The model ladder — expensive model orchestrates, cheap models do volume

The top model of an approved provider plans, decides, reviews and does the genuinely hard
parts. Everything else — repo surveys, transcript mining, boilerplate, tests, docs,
first drafts, bulk edits — goes to a cheaper model of the same provider, as a
subagent or a separate run. Say in the recap which model did what.

Code, diffs, logs and transcripts from this machine go only to providers IT has approved
for this code. A provider with a CLI installed here is not approved by that fact; add its
row below only when it is.

<!-- Example ladder: replace these rows with the models you actually use. -->
<!-- ladder:start — maintained by `teyla models --write-policy`; edit rows by hand if you must, keep the markers -->
| provider | orchestrate / hardest tasks | volume work | throwaway / triage | note |
|---|---|---|---|---|
| Anthropic | Claude Fable 5.1 | Opus 5, Sonnet 5 | Haiku 4.5 | Fable inherits by default in subagents — always pass model: |
<!-- ladder:end -->

- In Claude Code, pass `model:` explicitly on every `Agent` call; "inherit" means Fable.
- When a provider ships a new tier, update the row here, nowhere else.

## 2. Second opinions from a fresh session

Before committing to a non-trivial design, and before landing anything that touches
money, credentials, or another person's data, get a second opinion from a fresh session
of the same harness: only the diff and the question, no prior context, labelled a
same-provider review. One pass, P1/P2 findings, then move on. Do not loop reviews. A
review covers only the diff it saw: a commit after the review means review again, or
merge what was reviewed and put the rest in its own PR.

Never send a diff to a provider that is not in the ladder above for a review — not
`/codex review`, not `/grok review`, not a paste into a chat app.

## 3. Use the tool ladder, top down

Connector / MCP → CLI / API → browser extension (Claude-in-Chrome) → computer use.
Fall to the next rung only when the one above cannot do it, and say when you fell.
Prefer gstack skills when the task shape matches: `/autoplan` before a non-trivial
build, `/review` before a PR, `/qa` after a UI ships, `/spec` when intent is vague.

## 4. Ask about product decisions, not about permission

Bring the question with a proposed answer and a default. Do everything that does not
depend on the answer first, then ask — batched, at a natural checkpoint. Never ask
"shall I proceed?".

## 5. Stop only at a real blocker or the finished goal

A blocker is something only {{owner}} can do: create an API key, approve a payment, sign
in, accept terms. When you hit one: do every step around it first; open the exact
page at the exact step; name the exact file and line the value goes into; hand over
a one-line instruction, then continue the moment it is in.

## 6. Deliver plug-and-play

"Done" means {{owner}} can open it and start using it: README with a 5-line quick start,
setup script, `.env.example`, first-run check that prints what is missing. A feature
nobody can start is not shipped.

## 7. Merging

Merge without asking only into repos on your merge-approved list (Claude: the
list in `~/.claude/CLAUDE.md`). A repo you were asked to create in a kickoff is
approved from creation; record it with the kickoff sentence quoted verbatim.
Everywhere else: open the PR, stop, say what it changes. Merge, never squash. Never
force-push.

## 8. Report honestly

If you could not verify something, say so in the same sentence as the claim. If a
subagent reports a fact a command could check, check it. Corrections to your own
earlier claims go in plainly and once.

## 9. "Did it run?" is answered from the record, not from the code

When asked whether a product ran, works, or is up ("did it run this morning?",
"why is there no build?"), start from `teyla routines <repo>` — the routine rows
(loaded, last run, stale) and the manual checks — and the logs its `teyla.toml`
names. Read code and git history only once the record shows something wrong and
the cause is needed. Answered from the record it costs one command; answered by
reading code it costs a session.

## 10. One machine, a budget — the guard decides, not the agent

Every agent on a laptop shares one CPU, one RAM and one swap file, and none of them
sees the others. Ten sessions that each boot "just one" simulator and run "just one"
build exhaust memory together: swap fills, load climbs into the hundreds, and the
kernel panics. So:

- **Check before heavy work.** `teyla load` gives the verdict (OK / BUSY / CRITICAL)
  with the numbers. On CRITICAL, start nothing heavy — no build, no simulator, no
  headless lane — and finish or stop what you started.
- **Wait, do not retry.** When the machine guard refuses a command, run it as
  `teyla load --wait --kind <build|sim|lane> && <command>`. It blocks until a slot is
  free; a retry loop is the same overload with extra steps.
- **Reuse a booted simulator.** Boot one only when none of the booted ones fits; shut
  down every simulator your lane booted when the lane ends (`xcrun simctl shutdown <udid>`).
- **Stop your daemons.** A lane that ran Gradle ends with `./gradlew --stop`.
- **Parallel lanes cost memory, not only tokens.** Fan out only as wide as
  `guard.max_builds` and `guard.max_sims` allow; queue the rest.
- After a crash, `teyla crash` says what the machine looked like before it; read it
  before starting the next sprint.
