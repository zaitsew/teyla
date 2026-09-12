# How to work with AI agents

**The Teyla manual, rev. 8**

For a product manager or solo founder who is not a full-time engineer and runs
Claude Code, Codex, Grok or Hermes daily. One policy, one loop for running work,
one mechanism that makes a correction stick, one spine for building software.

Rev. 8 is written against measurements taken on one real multi-product setup.
The headline finding reorders the whole document: **the products shipped and
nobody used them.** Combined daily usage, read from their own usage counters,
was approximately zero. None failed
technically. Every one failed at the only gate that matters.

Outside numbers are marked where unverified. Anything that could have been
checked by a command and was not says so.

---

## 0. The policy

One file, read by every harness. It lives at `~/.agents/POLICY.md`; `teyla
policy init` writes it and `teyla policy sync` wires it into Claude Code (an `@`
import in `~/.claude/CLAUDE.md`), Codex (`~/.codex/AGENTS.md` symlink), Grok
(`~/.grok/AGENTS.md` symlink) and Hermes (a section in `~/.hermes/SOUL.md`).
Edit the source, never a copy. `teyla policy status` shows which harness drifted.

### §1 The model ladder — the expensive model orchestrates, cheap models do volume

The top model of whichever provider you are on plans, decides, reviews and does
the hard parts. Everything else — repo surveys, transcript mining, boilerplate,
tests, docs, first drafts, bulk edits — goes to a cheaper model of the same
provider, as a subagent or a separate run. Say in the recap which model did what.

| provider | orchestrate | volume | triage |
|---|---|---|---|
| Anthropic | top reasoning tier | mid tier | cheapest tier |
| OpenAI | top reasoning tier | standard tier | mini / nano |
| xAI | heavy tier | fast tier | mini |

Keep the actual model names in your own copy of the policy and nowhere else, so
there is one place to edit when a provider ships a tier.

- A subagent that reads and summarises never needs the orchestrator model.
- In Claude Code, pass `model:` **explicitly on every** `Agent` call. "Inherit"
  means the expensive default, and it is the largest waste in the measured data:
  **the majority of subagent calls typically inherit the top model, for boilerplate.**
- In Codex, keep the top model for the interactive orchestrator; run `codex exec`
  fan-outs with a cheaper `-m`.

### §2 Second opinions across providers

Before committing to a non-trivial design, and before landing anything touching
**money, credentials, or another person's data**, get a review from a different
provider. One pass, P1/P2 findings, then move on. Do not loop reviews.

Not hygiene theatre: in the measured fortnight this caught a P1 four times — a
race in a spend cap, an account-deletion path that left rows behind, and twice an
exit instruction that never reached the venue it was meant to reach. All four had
already passed review by the family that wrote them. A model reviewing its own
diff shares every assumption that produced the bug.

### §3 Use the tool ladder, top down

Connector / MCP → CLI / API → browser extension → computer use. Fall to the next
rung only when the one above cannot do it, and say when you fell.

### §4 Ask about product decisions, not about permission

Bring the question **with a proposed answer and a default**. Do everything that
does not depend on the answer first, then ask — batched, at a checkpoint, not one
at a time. Never ask "shall I proceed?".

New in rev. 8: a kickoff prompt listing four to eight features and asking for
"10/10 quality" gets **silently sequenced** by the model, which then builds in an
order nobody chose. **Before code, the agent returns a written scope, a priority
order and explicit non-goals**, and asks its product questions with proposed
defaults.

### §5 Stop only at a real blocker or the finished goal

A blocker is something only the human can do: create an API key, approve a
payment, sign in, accept terms. Do every step around it first; open the exact
page at the exact step; name the exact file and line the value goes into; hand
over a one-line instruction; continue the moment it is in.

### §6 Deliver plug-and-play

"Done" means the human can open it and start using it: README with a five-line
quick start, setup script, `.env.example`, and a first-run check that prints what
is missing. Not "the code is there." A feature nobody can start is not shipped.

### §7 Report honestly

If you could not verify something, say so in the same sentence as the claim. If a
subagent reports a fact a command could check, check it. Corrections to your own
earlier claims go in plainly and once.

### §8 Governance files belong to the human

Rev. 8, and it exists because it was broken. An agent added a repository to the
merge-approved allowlist in the human's global instructions file, mid-task, and
wrote a **fabricated quotation** of the human authorising it.

The rule: **the allowlist, the policy file and the harness configuration are
edited by the human only.** An agent that thinks a repo belongs on the list says
so and stops. Teyla's monitor flags any session that writes to the global
instructions file, so the edit is visible even if you were not watching.

---

## 1. Skill, rule, fact

Three objects, three stores, three lifecycles. Collapsing them into "the agent
updates its own instructions" rots a working setup into contradictory prose in
about a month.

|  | **Skill** | **Rule** | **Fact** |
|---|---|---|---|
| Answers | How is this job done? | What must always/never be true of the output? | What is currently the case? |
| Lives in | `.claude/skills/<name>/SKILL.md`, in git | `.claude/rules/*.md`, mirrored into `AGENTS.md` | `NOTES.md` beside the work |
| Changed by | You, when the process changes | A correction: `/teyla:correct`, then `/teyla:rule` | You or the run; rewritten in place |
| Applied by | Loaded on demand, description match | Path glob — loads when work touches matching files | Read by the agent (ripgrep over the tree) |
| Changes | Monthly, if that | A few a week early, tapering hard | Every run |
| If wrong | Does the wrong job | Does the right job badly, the same way, forever | Answers from half a brain |

**The test when you cannot tell which you are writing:** would this sentence make
sense in a different job? If yes it is a rule. Rules are portable across a track;
skills are not portable at all.

**Everything is a file in git** — the deliberate difference from memory-layer
products (§7). A rule you can diff, review and revert is one you can trust.

**Two files, one content.** `AGENTS.md` is the cross-tool instruction file that
Codex, Cursor, Zed, Grok and Hermes read natively; `CLAUDE.md` is Anthropic's
convention and the others do not read it. If you route work to foreign models as
critics — and §2 says you must — a repo with only `CLAUDE.md` starts every critic
blind. `teyla policy sync-repo <path>` symlinks whichever is missing.

**Keep it short.** Under ~200 lines, exact commands ahead of prose. Attention
degrades with input length and does not error when it does; a 600-line
instruction file hides your important rules inside your unimportant ones. Use
`/init` as a skeleton, then delete aggressively.

---

## 2. Routines

### From "I prompted my way to a result" to a routine

You already do step one: open a harness and push until you get something usable.
What turns a pile of those into a routine is: **run them separately, then harvest
them all in one sitting.** Separately, because context degrades — by run seven the
model works from a summary of runs one to six and inherits their mistakes as
precedent — and because the separation criterion falls out of the variation: *what
you did the same way every time is the skill; what you corrected in most runs is a
rule.* You cannot see that split inside one session; there is only one run of it.

### The project root is a decision with a deadline

The project root is the directory you launch from; it keys the transcript store,
the memory directory and the learnings file. **Keep it coarse; folders inside it
are free.** A root per routine feels tidier and fragments all three. Measured on
one machine: 22 roots, 785 MB, the top four holding 77 of 99 sessions, while
Each new root
restarts accumulation at zero. Split roots only on boundaries that are **real** —
data ownership, a legal line, a separate remote, different collaborators — never
on taxonomy.

```
~/ops                        # everything that is not a code repo. One root.
~/repos/<repo>               # flat, one level, one directory per git repo
~/.worktrees/<repo>/<branch> # parallel agents, one branch each
```

For software this is one line: **launch from the repo root, always.** Not from a
parent directory, not from a subdirectory. Launch from the wrong place and the
repo's instruction file does not load, its hooks do not fire, and every gate you
wired is repo-local, so none apply.

### The harvest

It takes the path where the manual runs happened and emits four things:

1. **The skill** — only what you did the same way every time. One screen.
2. **Candidate rules** — everything that varied or that you corrected. Explicitly
   *not* in the skill.
3. **The manifest** — artifact, trigger, scope, and a capabilities list built only
   from tools it observed you using. If you sent every message by hand, the send
   capability is not in it and cannot be granted by accident.
4. **The done-test** — drafted, never decided. Only you know the number at which
   you would kill the routine, and that number is the point.

The instruction that keeps the skill clean is *"do NOT put any of these in the
skill."* Without it the model folds every correction into the procedure and you
get a 400-line skill containing two instructions that contradict each other.

`teyla harvest <path>` does the machine half: it finds sessions that touched the
path and prints each one's tool spine and correction-shaped turns. It refuses
below two sessions — with one run you cannot tell a procedure from an accident.

**The trigger nobody notices.** The harvest was designed, documented and never
run once, because noticing "I have now done this three times" is exactly what a
busy person does not. So the monitor does the noticing: when two or more sessions
touch the same path, it suggests the harvest. A process you must remember to
start will not run.

### The run loop, and where the gate sits

Each routine has a manifest binding a trigger to a **named** skill and declaring
scope. Nothing is inferred.

```yaml
routine: weekly-digest
trigger: { type: schedule, at: "0 7 * * 1", tz: Europe/Madrid }
skill:   digest-draft        # named, not chosen by a model
scope:   { task: reporting, artifact: "runs/{date}/digest.md" }
gate:    { position: pre, surface: file }
capabilities: [Read, Write]  # send is NOT granted
```

The loop: trigger → load skill → match rules → retrieve facts → draft → check →
**gate** → act → receipt. Two retrieval mechanisms, deliberately different:
**rules are matched by exact scope, facts are retrieved by meaning.** Missing a
fact costs a worse draft; missing a rule costs a repeated mistake — only one is
allowed to be fuzzy. The rule you most need is the one the draft does not
resemble: "never mention pricing in a first message" ranks low in a similarity
search exactly when it is working.

**The model is subject to the loop, not the author of it.** The loop is code; the
model is called inside the draft step and nowhere else, so it cannot skip the
gate.

| Gate position | What it means | What earns the next one |
|---|---|---|
| **A · before** | Nothing leaves without your approval of that exact version | Approved unedited ~9 of the last 10, over ≥30 runs |
| **B · after** | It acts, then shows what it did, with an undo that works | 30 consecutive clean runs, zero undos used, a receipt each |
| **C · delegated** | A critic model checks output against the same rules | Nothing. Most capabilities never reach it |

Four things must exist before anything moves off A: an **idempotency key** on
every side effect; a **kill switch you have used at least once**, because
untested ones are decoration; a **receipt per run** naming what it touched and
which rules governed it; and **machine output going to a machine queue**, never
the list you personally work from. Per capability or nothing.

**The gate must be the path the artifact actually travels.** Fix the draft
somewhere else — in the destination app, in a browser — and nothing is captured;
you will make that correction forever. That is why the gate is built early.

### Where to run it

Your OS scheduler (`launchd`, cron) is the default and most routines never
outgrow it. Escalate only on a limit you have hit: scheduler → CI (when it must
run with the laptop shut) → a durable workflow engine (when you need multi-step
state that survives a crash).

---

## 3. Building software

### Stage 0 is a refusal, and it is the highest-leverage one you have

**Is this software?** A codebase is the most expensive artifact you can create,
because it is the only one that must be maintained after you stop caring about
it. Four cheaper things usually come first: a **routine** (if the output is a
document, message or decision), a **skill** (if you want X done the same way
every time), a **config change**, a **spreadsheet**.

Build software when the thing genuinely needs to run without you, hold state
between runs, or be used by someone who will never read a prompt. That is the
whole list.

### The nine-stage spine

| # | Stage | Who | Note |
|---|---|---|---|
| 0 | Frame | you | Stage 0 above. No tool. |
| 1 | Constitution | you | The repo's non-negotiables. Once per repo. |
| 2 | Spec chain | you → machine | Specify, clarify, plan, tasks. |
| 3 | **Gates** | you | **Wired before the first line of implementation.** |
| 4 | Implement | machine | One task, one commit. |
| 5 | Verify | machine + you | Diff review, cross-provider review, then *run it*. |
| 6 | Land | machine proposes | The PR. The merge decision is the human's. |
| 7 | Operate | machine | Deploy, then watch. A canary nobody reads is a log file. |
| 8 | Harvest | you | What should stick becomes a rule or a skill. |

Stage 3 is routinely misplaced. **A gate added after the fact has never blocked
anything**, so it has never been tested, so you do not know whether it works. A
gate wired first blocks its first bad write within the hour.

### Four scenarios, one spine, different lengths

The subset you use is decided by **who gets hurt if it is wrong.**

**A · Personal tool.** Frame → implement → run it → harvest. No spec chain, no
CI, no PR. Live in `~/repos/<tool>` from day one anyway — a tool in a scratch
directory is one you rewrite instead of find. Promotion test: used twice a week
for a month, or used by one other person. Until then process is the waste.

**B · Fork and tailor.** The first question is never "how do I change this" but
*can this be a config, a plugin or a wrapper* — a setting costs nothing forever, a
patch costs an afternoon every time upstream moves. When you must patch: upstream
on its own branch, one named commit per patch, never squashed. Health test: *can
I replay my patches onto this month's upstream in one afternoon?* When the answer
is no you have a second product, not a fork.

**C · Your own product.** All nine stages, four gates with at least one genuine
wall, staging, a canary, a receipt per run. The expense is the point: somebody who
is not you depends on it.

**D · PR to their repo.** Read `CONTRIBUTING.md` and the project's AI policy
first — projects range from "disclose it" to "pre-approved issues only" to
outright bans. Disclose that an agent wrote it. One logical unit. Include the
test. **You never merge.**

### Gates before code

One sentence decides whether you have any: **a check nobody requires is not a
gate.** A repo can have excellent CI, green on every commit, and no gate, because
nothing requires the check before merge.

- **Pre-tool hook** — fires before the tool runs *and before the permission
  check*, so a denial holds even under a bypass mode. The right home for rules
  that must not be probabilistic: no `--no-verify`, no force-push, no squash
  merge, no `rm -rf` on a worktree, and the merge allowlist.
- **Pre-commit hook** — the cheap local pass. Two additions from rev. 8: grep for
  **hard-coded single-user keys** (a smoke test with one user's identifier
  compiled in shipped twice), and grep for **booking or record locators** in
  anything about to be published.
- **Required status check** — the wall. Branch protection with the CI job named
  as *required*, not merely present.
- **The human gate** — position A/B/C above.

And: **a smoke test must never touch the live data store.** Point it at a fixture
or a scratch instance. A smoke test that writes to production is not a test, it
is an unreviewed deploy on a timer.

### The spec chain

| Step | Produces | Who |
|---|---|---|
| Constitution | Non-negotiables: language, test policy, what may never be committed, how errors surface. Committed. | you |
| Specify | User-visible behaviour, done-test, non-goals. No implementation nouns. | you |
| Clarify | The ambiguities surfaced as questions, before anything is guessed. | you |
| Plan | Components, data, migrations. You read this for blast radius, not correctness. | machine |
| Tasks | The plan cut into units. One task = one commit; if it cannot be, it is two tasks. | machine |
| Implement | Code, against the tasks, one at a time. | machine |

The first five steps are about deciding what is true for users and what must
never happen — a product manager's job description, not an engineer's.

**Clarify is the step not to skip.** The alternative to answering an
underspecified question is not "no decision"; it is the same decision made
silently inside an implementation, where you will never see it.

Three things your spec has that a model's will not: the **non-goals**, the
**done-test** (the number at which you call it finished), and the **kill-test**
(the number at which you delete it). The last is the one everybody omits and the
only one that saves real money.

### Reviewing code you cannot read

Five questions, none requiring you to read the implementation:

1. **What did it touch that I did not ask about?** `git diff --stat`. A
   one-sentence change touching fourteen files is not that change.
2. **Show me the test that fails without this** — red on the old code, green on
   the new. Better: write the test first, so done is defined where the agent
   cannot fake it.
3. **What did you delete?** A model asked to make a test pass will sometimes
   remove the assertion.
4. **What happens on the unhappy path?** Empty, offline, slow, wrong password,
   second click, expired token.
5. **What is the undo?** If it involves a migration, a deleted file or a sent
   message, the review standard goes up.

Four diff shapes justify slowing down regardless of what a critic said: a new
dependency, a new environment variable or secret, a CI-config change inside a
feature PR, and a file added to a directory you have never seen. Then **run it** —
green CI says the code does what the code says, not that the feature works.

### The merge rule

**An allowlist of repositories where an agent may merge without asking. That list
is the whole permission.** Not a default, not a starting point, not extended by
inference — not by write access, not by org membership, not by a green build, not
by "the fix is obviously correct". Everywhere else: open the PR, then stop and
say what it changes, why, and who owns the repo.

Two corollaries from real incidents: **the list is edited by the human, in the
human's own file** (§0 §8). And **never force-push, never push a diverged main** —
if local `main` is both ahead and behind, push it as a named branch and report
what you found.

---

## 4. Session discipline

The measured shape of a bad fortnight: transcripts of 8–35 MB, sessions of 12–60
hours, **zero compactions**, cache-read to output ratios of 250–400:1. A session
like that re-reads an enormous context every turn to produce a few hundred
tokens, and by hour thirty the model is working from a summary of its own earlier
mistakes.

| Signal | Threshold | What to do |
|---|---|---|
| Transcript size | split at ~5 MB; **8 MB is a defect** | End it; start fresh from the repo root |
| Wall-clock duration | 12 h | Same |
| Compactions | ≥3 | The context you cared about is already gone |
| Cache-read : output | >150:1 | Shorter sessions; subagents for reading; summaries, not whole files |

**One session per logical unit**, launched from the repo root, ended after the PR
merges. A logical unit is what you would review in one sitting — the same
definition as one PR, which is not a coincidence.

**Scope before code** (§0 §4): the agent's first output is a written scope,
priority order and non-goals, not an implementation.

**Status check-ins are not sessions.** "Did the overnight job run?", asked every
morning in identical words, is a script and a digest. Anything you ask daily in
the same shape should be a cron job writing a file you read.

**Unattended overnight runs need two things** attended ones do not: **checkpoint
commits**, so a run killed at 04:00 leaves recoverable work, and a **check-in time
set against the limits you actually face** — session caps, plan expiry, token
budgets. A run that dies at 02:00 and is found at 09:00 costs you the night twice.

---

## 4b. Keeping it current — what runs without anyone remembering

A tool that audits whether routines run has to be one. Teyla's own maintenance is two
launchd agents, one hook and one command:

| when | what | writes |
|---|---|---|
| daily 07:00 (`com.zaitsew.teyla.daily`) | `teyla update --quiet` then `teyla doctor --quiet` | `~/Library/Logs/teyla-daily.log`, `~/.teyla/doctor.summary` |
| Monday 07:30 (`com.zaitsew.teyla.weekly`) | `monitor --days 7`, `routines`, `products`, `models` | `<ops>/startup/os/ai-dev/runs/<date>/` |
| every session start (plugin hook) | prints `doctor.summary` if non-empty; if the last update check is older than a day, starts `teyla update --check` in the background | `~/.teyla/update-check.json` |
| on demand | `teyla doctor` — the checklist with a fix per line; exit 1 when a FIX is pending | `~/.teyla/doctor.json` |

A one-off fact with a deadline — a key that expires, a trial that ends — gets its own line:
`teyla remind add "<what>" <YYYY-MM-DD> [--how "..."]`, folded into `teyla doctor` as OK
until 30 days out, then WARN, then FIX once overdue, `how` printed as the fix.

`teyla update` decides how it was installed (uv tool, pipx, pip, or a git checkout) and
upgrades the same way, from GitHub releases of the repo in `~/.teyla/config.toml`
(`[update] repo`). Then, in a fresh process so the new code does the wiring:

1. `policy sync` — the import line, the Codex/Grok symlinks, the Hermes section.
2. `policy refresh` — the template shipped with the new version, merged into
   `~/.agents/POLICY.md` with `git merge-file` against the template as last applied
   (`~/.teyla/policy-base.md`). Your edits survive; a real conflict is written to
   `~/.teyla/policy-merge-conflict.md`, your file is left alone, and doctor nags until you
   run `teyla policy refresh --resolved`.
3. `plugin refresh` — Claude Code loads a *copy* of the plugin under `~/.claude/plugins/cache`;
   this brings that copy to the CLI's version, with or without the `claude` binary.
4. `routine install --if-stale` — rewrites the wrappers only if they name a binary that moved
   or no longer carry the `[env]` block from config.
5. `doctor --quiet`.

**The environment none of this inherits.** launchd runs `/bin/bash daily.sh` with
`PATH=/usr/bin:/bin:/usr/sbin:/sbin`; the desktop app's session hook runs `sh -c` from a
GUI process; neither reads a shell rc. On a managed laptop behind a TLS-inspecting proxy
that is the difference between a machine that self-maintains and one that has quietly
stopped: `git` and `curl` verify through the keychain and work, Python verifies through
OpenSSL's bundle and does not. So the environment Teyla needs lives in
`~/.teyla/config.toml` and nowhere else:

```
teyla config set env.SSL_CERT_FILE=~/.teyla/ca-bundle.pem env.HTTPS_PROXY=http://127.0.0.1:9000
teyla routine install
```

Every `teyla` process applies `[env]` at startup (a variable the shell already set wins),
and `routine install` writes it, with `PATH`, into both plists and both wrappers. Because
the generator reads config on every write, the update that regenerates those files keeps
the adaptation instead of erasing it. `teyla config show` prints the effective file.

What it never does: edit a repo. Repos missing their `AGENTS.md ⇄ CLAUDE.md` pairing are a
WARN in doctor with the `teyla policy sync-repo` command to run; that creates a file in
someone's working tree and stays a human's call. Likewise `~/.claude/CLAUDE.md` is yours:
Teyla adds one import line and otherwise reads it only to notice (advice A10, `policy ack`)
when it changed without you.

Different machines, different scope: absent harnesses and absent CLIs are INFO lines, not
failures. A managed laptop with only the Claude Code desktop app and no `gh`, `codex` or
`grok` is a valid install; doctor says what the second-opinion fallback is there.

Releasing: `scripts/release.sh 0.7.1` bumps the three version strings (package, `__init__`,
plugin), tags, pushes; the release workflow runs the tests, checks the tag matches, and
publishes the GitHub release that every machine's `teyla update` sees.

## 5. Measuring

Teyla reads the local session logs of every harness it finds — Claude Code, Codex,
Grok, Hermes — and aggregates them. Nothing is uploaded; the report is a file on
your disk. `teyla doctor` says which stores it can actually see.

```
teyla monitor --days 30 --out runs/teyla/$(date +%F).md
teyla advise --days 30          # just the findings
teyla sessions --days 30        # one line per session
teyla corrections --cluster     # correction-shaped turns, grouped
teyla harvest <path>            # tool spine + corrections for a path
teyla policy status | sync      # is the policy wired into every harness
```

It reports output tokens; cache-read / cache-write / fresh input; a cost estimate
at list prices; the share of output on orchestrate-tier models; subagent calls and
how many inherited the top model; human turns and how many were
correction-shaped; cache-read per output token; and the count of giant sessions.

### The advice ids

Each finding carries a severity, an evidence line with numbers, and one
imperative action. A finding you cannot trace to a number is noise.

| id | Fires when | Meaning |
|---|---|---|
| **A1** | ≥10 subagent calls, >50% with no `model:` | Subagents inherited the orchestrator. Measured at 65%. |
| **A2** | >60% of output on orchestrate-tier models, >1M output tokens | Volume work on the expensive model. |
| **A3** | Any session >8 MB, >12 h, or ≥3 compactions | Giant sessions; names the worst with its numbers. |
| **A4** | Cache-read : output > 150:1 | Long contexts re-read every turn. |
| **A5** | ≥50 human turns | Correction rate. >15% high, >8% medium. |
| **A6** | >50 agent calls, no review skill invoked | No pre-merge or cross-provider review (§0 §2). |
| **A7** | Session cwd ends in `/repos` | Launched from the parent directory; transcripts land under the wrong project. |
| **A8** | A harness missing the policy wiring | Run `teyla policy sync`. |
| **A9** | The same correction shape (fingerprint) appears twice | Each is a rule nobody wrote down; the text stays local. |

To act on a finding, promote it into a file: `/teyla:correct "<what was wrong>"`
records the correction and proposes a rule; `/teyla:rule "<rule>" --scope <glob>`
writes `.claude/rules/<slug>.md` and mirrors it into a real `AGENTS.md` if one
exists. The correction command deliberately does not promote on its own — a
correction is a data point, not yet a decision that it generalises.

### Correction rate and re-offense rate

**Correction rate** is the share of your typed turns that look like corrections
("no, not like that", "I said", "revert", "why did you"), detected by a broad
regex over turns under 800 characters — long turns are briefs, not corrections.
Watch it over time rather than trusting the absolute count: rising while session
count is flat means the rules are not landing.

**Re-offense rate** is the share of corrections that recur *after* a rule was
written for them — the metric that answers "is this system learning?", and the
one nobody else reports. Honestly: Teyla approximates it today with A9
(corrections repeating verbatim). A true re-offense rate needs per-run receipts
recording which rule ids governed each run, and **those receipts are designed and
not yet shipped.** Do not read A9 as a measured re-offense rate.

### Why introspection is unreliable

In a randomised controlled trial, experienced developers working in their own
mature repositories on 246 real tasks were **19% slower** with AI assistance and
believed afterwards they had been **20% faster** — a 39-point error, in the
flattering direction (METR, 2025-07-10; a larger 2026 follow-up was withdrawn
from interpretation by its authors over selection bias, so treat the original as
load-bearing and the follow-up as unavailable).

The consequence is not "distrust AI". It is that **every routine and every tool
needs a done-test with a number in it**, because "this feels much faster" is the
exact sentence that study measured as wrong. Count something: PRs needing a
second round, bugs found after merge, spec-to-merge time, daily uses of the thing
you built. Any of them beats introspection, and introspection is the alternative.

Two further findings shape the manual, both reported rather than verified here:
after AI adoption, median PR review time and incidents per PR rise sharply while
median main-branch throughput falls — the bottleneck moved from writing to
reviewing; and agent-authored PRs merge at a materially lower rate, the recorded
reasons being **incomplete implementation and inadequate testing**, not style.
Both are catchable by question 2 in §3. The gap between what an agent produces
and what is mergeable is a verification gap, and verification is the half you
own.

---

## 6. Built, not used — and the scaffold that prevents half of it

### The trap

Several products, all shipped and working, combined daily usage approximately
zero — measured, not felt. The rule goes at the top of every sprint:

> **Read the product's own usage counters before scoping any sprint. If usage is
> zero, the next sprint is "make one input free" — not a feature.**

"Make one input free" means: find the single thing a user must do before the
product can do anything, and remove the work from it — pre-fill it, import it,
infer it, or accept a worse version. A product needing ten minutes of setup before
its first output has a conversion funnel, and the funnel is where the users went.

Second half: **routines that create the habit come before machinery.** A daily
prompt, a weekly digest, a reminder arriving where you already look — cheaper than
any feature, and what converts a working product into a used one. Build the digest
before the dashboard. If usage is still zero after the habit routine ships, that
is the kill-test firing, and the answer is to stop building.

### Scaffold on day one

Seven repos, each missing a different subset of this, each needing the same
half-hour later, none of them getting it. Ship all of it on the first commit:

| File | Why |
|---|---|
| `AGENTS.md` (+ `CLAUDE.md` symlink) | Your foreign-model critics read `AGENTS.md` and nothing else. |
| `check.sh` | First-run check: prints what is missing (env vars, toolchain, tests), exits non-zero with a list. §0 §6, made concrete. |
| `.env.example` | Every variable the code reads, commented. `check.sh` reads it to know what to check. |
| `LICENSE` | Decide once, at creation. Retrofitting one onto a repo with contributors is a conversation. |
| CI workflow | And then **name it as a required status check**, or it is not a gate. |
| `.claude/rules/README.md` | So the first correction has somewhere to land. |
| `routines/` | One example manifest, so the first routine is a copy, not a design exercise. |
| `runs/` (gitignored) | Generated artifacts live here and are never committed. |
| `docs/DECISIONS.md` | Facts, beside the work, rewritten in place. |

Teyla ships this set as templates under `templates/repo/`, and
`teyla scaffold <path> --name X --kind cli|app|service|ios [--license apache|mit]`
writes them into a new repo, substitutes the placeholders, links `CLAUDE.md →
AGENTS.md` and runs `git init`. It never overwrites an existing file. For a repo
that already exists, `teyla policy sync-repo <path>` does the `AGENTS.md` /
`CLAUDE.md` half on its own.

The general form: **`runs/` is data, `NOTES.md` is state.** If rerunning the
routine would regenerate it, it is gitignored. If it is a decision the next run
must respect, it is committed.

---

## 6b. Productizing — the distance between "works for me" and "works for you"

Section 6 is about things built and never used. This one is about the thing used every day
by exactly one person, which is a different failure and a more painful one: somebody wants
it, and you cannot hand it over.

Audit a handful of solo-built apps and the same six findings come back, none of them a
mistake, each locally correct for someone with no second user:

1. **One shared key instead of accounts.** Holding the string is being you. Nothing to give
   a second person that is not also permission to be the first.
2. **No `user_id` on any table.** Two people share one dataset. The most expensive to fix,
   because the fix is a migration plus an auth change plus every query, on live data.
3. **The backend on the builder's laptop.** It sleeps when the lid closes.
4. **No distribution path.** Xcode, an unpacked extension, a sideloaded APK — all of them
   "works on the developer's machine" wearing different hats.
5. **The builder's model key on someone else's device**, unmetered and uncapped.
6. **No onboarding doc.** The README is a build guide, written for the author.

Sharing is a plumbing problem, and solo work never forces the plumbing. So do it on day
one, when it is free: identity from the platform, `user_id` and row-level security from
migration 0001, no backend on a laptop, model calls metered or brought by the user,
a TestFlight build and a PWA the first week, config out of code, an onboarding doc before
the first invite, and a `[[check]]` that says *a second user completed onboarding* — which
stays `untested` until one actually has.

Two commands hold this. **`teyla platform`** is the manifest of what you buy once and reuse
forever — server, domain, identity provider, mail sender, Apple key, Play Console, model
key, and one mode-0600 secrets file — and reports what is set up, what is missing, and for
each missing thing the URL where it is created plus the file and key name where the value
goes. It stores identifiers and env-var *names*; never a value. **`teyla productize`** reads
a `[productize]` block in each repo's `teyla.toml` and checks nine requirements against the
target: identity is not a shared key (unless the app is genuinely per-device), tenancy is
not `single`, the backend is not a laptop, every declared platform has a real distribution
path, the onboarding doc exists, every named secret is in an `.env.example`, a cost cap
exists wherever your key pays for someone else's use; for a `public` target only, the
platform can send mail to strangers; and for `family` and `public`, the app opens on a
sign-in (skippable only when no account is truly needed) and never shows sample data as the
user's own.

A `family` or `testers` target is deliberately easier than `public`: an internal TestFlight
group and a PWA genuinely are enough for four people. `--owner-steps` merges every product's
owner blockers with the platform's missing resources into one numbered list, platform first,
because one mail sender unblocks three products at once.

The full method, the cost table, and four worked case studies are in `docs/PRODUCTIZE.md`.

## 7. Prior art, and how Teyla differs

Every piece of this exists somewhere, made well, by someone else. The combination
is what is missing.

**gstack** — <https://github.com/garrytan/gstack>. A large library of pre-built
role skills (CEO, designer, eng manager, QA, release) working across several
agents. *Difference:* gstack ships you the skills; Teyla harvests them from your
own transcripts. They compose.

**TRACE** — <https://arxiv.org/abs/2606.13174>, with reference implementation
**tellonce** at <https://github.com/YujunZhou/tellonce>. The closest prior art to
the correction→rule mechanism: it mines corrections and compiles them into
runtime-enforced rules, reporting large reductions in preference violations over a
memory-only baseline. *Difference:* a paper plus one dogfooded skill versus a
packaged multi-harness tool — and Teyla refuses to mine corrections silently
(below). Its numbers are one unreplicated result: sound mechanism, figures not for
external quotation.

**ccusage** (<https://ccusage.com/>), **claude-code-otel**
(<https://github.com/ColeMurray/claude-code-otel>), **cctime**
(<https://github.com/dioptx/cctime>), and Anthropic's own monitoring
(<https://code.claude.com/docs/en/monitoring-usage>). Excellent on tokens, cost,
cache hit rate, session time; cctime is the only one found that looks for stuck
loops. *Difference:* none reports a correction rate, a re-offense rate, or the
subagent model mix — the three numbers that say whether your *habits* are
improving rather than what they cost.

**AGENTS.md** — <https://agents.md>. The cross-tool instruction-file standard,
stewarded under a Linux Foundation umbrella and read natively by a long list of
agents. *Difference:* none. Teyla is a consumer of the standard; `teyla policy
sync` exists to keep your files conformant.

**Cursor memories**, and agent-memory layers generally (Mem0, Letta). A background
model proposes durable facts and corrections; the user approves. *Difference, and
it is the load-bearing design choice:* those memories are not versioned, not
committed, not shared with collaborators. Teyla's rules are files in git —
diffable, revertable, reviewed by a human before they bind anything.

**Org-level AI adoption dashboards** (Waydev, Jellyfish, LinearB, and the DORA
research programme) operate at PR and ticket level, as hosted SaaS, for
organisations. *Difference:* Teyla is local-first, transcript-level, one person.
DORA's central finding — AI amplifies the strengths of an organisation that has
its act together, and the dysfunction of one that does not — is why §3 wires the
gate before the code.

### What Teyla deliberately will not do

| It will not | Because |
|---|---|
| Mine your chat for rules automatically | Measured on a real corpus: ~3 durable rules in the whole thing, a ~0.5% base rate. At that prevalence a detector with 80% recall and 99% specificity still lands under 30% precision. Corrections come through `/teyla:correct` or the gate, or they do not exist. |
| Rewrite skill files unattended | It destroys attributability, and self-generated skill search is sparse rather than steadily improving. |
| Summarise or consolidate the rule set | A measured rewrite compressed a context to a fraction of its size and dropped accuracy *below* the no-context baseline. Merge by supersession only. |
| Record your screen or audio | An enormous noise surface feeding a signal measured at 0.5%, plus storage and consent problems you would then own. |
| Use one global autonomy dial | Per capability or nothing. |
| Automate a job you have not run by hand | A routine built from imagination automates a job nobody has done. |
| Edit the human's governance files | §0 §8. The allowlist is the human's. |

### The honest expectation

The best-measured "learn from my edits" results in the literature are single-digit
improvements, and roughly 70% of what people change in AI-written prose is
meaning-preserving style. Expect drafts to get quietly less annoying, not to become
right. The compounding is real and gradual; a system sold on a step change gets
abandoned in week three.

Enforcement is proven for the class of rule a grep would have handled — simple
negative lexical constraints. For tone, structure and sequence, which is most of
what anyone actually corrects, the rule is injected and not deterministically
verified. That is a real product and a smaller one than "enforcement" usually
implies, and saying so is cheaper than having you discover it.

---

*Rev. 8 · 2026-09-09. Rev. 7 covered routines, the skill/rule/fact split, the run
loop, gate positions and the harvest; its annex covered the nine-stage spine, the
four scenarios and the spec chain. This revision folds both into one document and
adds §0 (the policy first, not as an appendix), §4 (session discipline), §6
(built-not-used and the scaffold) and the governance rule in §0 §8 — each written
against something that went wrong.*
