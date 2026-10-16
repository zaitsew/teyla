# Roadmap: Teyla as chief of staff

Status: 2026-10-16. Sprint 1 is in progress.

Teyla takes on four jobs: it collects every question waiting on the owner, it keeps the
owner's own words, it sets a writing contract, and it keeps docs honest. It does not become
a project manager, a design tool, a memory service or a voice agent. Linear, Figma, a company knowledge base
and the harnesses already do those jobs.

Sources: a Codex (GPT-6.1 Sol) consult, a Grok 4.7 consult, two web-research lanes (Sonnet
5.5) and two local surveys (Haiku 5.5), all on 2026-10-16. Both consults reached the same
core plan independently.

## The evidence

| Problem | What the survey found |
|---|---|
| Lost questions | In 14 days, 40 Claude Code sessions ended on a question to the owner. 38 of them are archived. 1 got an answer. The desktop app marks 40 sessions `blocked` with a `needs_action` line, and no tool reads it. |
| Untracked tasks | Linear is connected, but no issue changed in 30 days. |
| Lost context | In 30 days the owner wrote 231 prompts over 400 characters (208 in Claude, 23 in Codex). Nothing keeps them apart from the raw transcripts. |
| Verbose output | No limit and no measure. |
| Weak UX (the largest app) | The largest app has a design system (`DesignSystem.swift`, `docs/DESIGN.md`), but also 469 SwiftUI views, 170 hard-coded font sizes and 24 `UX-*.md` sprint files. Too many things on each screen is the problem. A missing design system is not. |
| Stale docs | Teyla's README has 11,017 words. Its command table takes 48% of them. `docs/MANUAL.md` carries its revision history. The README presents `reel` as shipped, but `docs/reel.md` calls it a v0 spec. |

## Decisions

1. **Questions: Teyla collects them, and the session stays the place to answer.** `teyla asks`
   reads Claude desktop session metadata, Claude Code transcripts, Codex rollouts and Teyla's
   own inbox. It lists every open question in one place, archived sessions included, with
   the question word for word, its age and a link that reopens the session. Bugs with a repro
   go to Linear (products) or GitHub Issues (open source). Questions never go to Linear.
2. **Context: keep the owner's words verbatim, outside the repo.** Prompts of 400 characters
   or more go to `~/.teyla/intent/<repo>.md`, append-only, with secrets scrubbed. A session
   that plans is pointed at that file, and the policy says a plan quotes the sentences it
   serves. No LLM summarises the log: the earlier drift came from a summary standing in for
   the source. The company knowledge base stays the place for company facts and gbrain for code search.
3. **Writing: one contract in the policy, three registers.**
   - Agent replies and internal docs follow STE-like rules: the answer first, one idea per
     sentence, at most 20 words per instruction, active voice, and a ban list.
   - Product UI strings follow each product's `DESIGN.md` voice section.
   - Social posts follow a voice chart per language (EN, ES, RU). Each language's post is
     written from the brief and never translated from English.

   `teyla prose` measures the reply side. Vale and Glavred (a Russian clarity checker) are optional linters. No paid
   tone tool: Writer starts at $29 per seat per month, and Jasper at $59 per month.
4. **Session output: a card, not an essay.** Each session ends with a card: status word,
   result in at most three bullets, at most one need with a proposed answer, links. The
   policy defines it, and `teyla asks` shows the need.
5. **Docs: current state only.** A README opens with what the product is, who it is for and
   why it helps, then gives a five-line start. Decisions go in PRs or `docs/decisions/`.
   `teyla docs check` flags a README without that opening, commands it names that no longer
   exist, and dated narrative in docs.
6. **UX: cut, don't add.** The shared standard and its audit live in Teyla:
   `templates/design/STANDARD.md` and `teyla ux check`. Each product keeps its own design
   system (`DESIGN.md`, tokens). The work itself happens in the product: take the five worst
   screens, build two different variants of each, the owner reviews them on the phone, and the
   agent applies only the cuts the owner accepts. The bar is one primary action per screen that
   is obvious within five seconds. See [UX.md](UX.md).
7. **Voice and computer control: trial what exists, build nothing yet.** Claude computer use
   is available in this setup. Codex's computer use may not be available in the EU, which
   is unverified. Run one bounded trial in one repo with no side effects, under `teyla load`.
   Do not try it on mail, the stores or payments.

## Sprint 1: Teyla 0.26 (autonomous, from 2026-10-16)

| Lane | Ships | Model |
|---|---|---|
| A | `teyla asks`: collector, CLI, a one-page HTML view, a banner count, `done` / `snooze`. Also fixes the doctor check that looked for the inbox at the wrong path. | Sonnet 5.5 |
| B | `teyla intent`: a capture hook, a 30-day backfill, a list command, and a pointer at session start. | Sonnet 5.5 |
| C | A writing contract and session card in the policy template, `teyla prose`, and a voice-chart template. | Sonnet 5.5 |
| D | `teyla docs check`, then a one-page README with the command table moved to `docs/COMMANDS.md`. | Sonnet 5.5 |

Every lane gets a cross-provider review (`codex-review`), passes `./check.sh` and lands as its
own PR. Fable 5.1 orchestrates and reviews.

## Later

- A UX pass on the largest app (five screens, two variants each), run in that repo.
- An intent coverage check: which of the owner's source sentences a plan does not serve.
- A voice and computer-use trial (decision 7).
- Linear for bugs only, if the owner wants a backlog.

## Owner decisions

- **Focus.** Codex recommends choosing two active products and parking the rest. Teyla can
  show the load, but the choice is the owner's.
- **Auto-archive on PR close** (Claude app setting, currently on). Once `teyla asks` lists
  archived sessions, archiving no longer hides questions, so it can stay on.
