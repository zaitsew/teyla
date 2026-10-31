# Roadmap: Teyla as the coordinator

Status: 2026-10-17. Night sprint 2 starts today.

Teyla is the owner's coordinator for sessions, projects and products. It owns four standards
across every product: how agents write, the UX bar, what a session reports, and what docs say.
One window on the Mac and on the iPhone shows what waits on the owner, what got done, what is
running and what comes next, and the owner works from it, by voice too.

Sources: the owner's request of 2026-10-16 and his corrections that evening and on 2026-10-17
(`teyla intent teyla`); a Codex (GPT-6.1 Sol) and a Grok 4.7 consult on 2026-10-16.

## What he asked, what exists, what 10/10 is

Quotes are translated from Russian; the source is in `~/.teyla/intent/teyla.md`.

| He asked | Exists on 2026-10-17 | Now | 10/10 means |
|---|---|---|---|
| "Teyla could take the role of coordinator of sessions / projects / products (become a Product / Project manager)" | A Mac window with questions and running sessions | 5 | One window, Mac and iPhone, answers: what needs me, what got done, what runs, what is next per product. It also starts work. |
| 1. "AI models write very voluminously and unclearly … work out a tone of voice in three languages at once (English, Spanish, Russian)" | Policy §16 writing contract, `teyla prose`, a voice-chart template | 5 | Median agent reply under 150 words and a card on 90% of session ends, measured weekly. A voice chart per language for the owner's social channel, and `teyla voice check` on every draft. |
| 2. "see all open questions to me / tasks only I can do, across all sessions, on one screen, and work with them"; "these tasks / bugs are not recorded anywhere" | `teyla asks`, `teyla answer`, the Mac window | 6 | Questions, owner-only tasks (a key to create, a PR to merge) and each product's bug backlog on one screen, Mac and iPhone. No question older than 3 days without an answer or a snooze. |
| 3. "Claude made an md plan that was very far from the original ideas, and lost the valuable information" | Verbatim capture in `~/.teyla/intent/`, a pointer at session start, the §4 rule | 6 | `teyla intent cover <plan>` lists every source sentence a plan neither quotes nor marks out of scope. Plans pass it before work starts. |
| 4. "UX / UI … the weakest link … a lot of noise and little logic … several versions / iterations for me to review" | `templates/design/STANDARD.md`, `teyla ux check`; the concept and roadmap for the rest in [STUDIO.md](STUDIO.md) | 3 | The owner reviews the real app on the phone by tapping and talking, and every comment becomes a decision or a PR (`teyla review`). A fixed screenshot matrix catches drift on every UI PR. The largest app's five worst screens rebuilt in two variants each, judged in pairs, the accepted cuts applied; its owner score moves two points. Every UI repo has a `DESIGN.md` under 100 lines. |
| "go through cybersecurity … so nothing leaks … confidential information must not leak to the network, and products and GitHub must not include confidential information or information specific to me … should this be part of Teyla or a separate product?" | `leak_check.py`, the private-terms list, `docs/PRIVACY.md` with its tripwire, safe mode, the kill switch; the concept and roadmap for the rest in [SHIELD.md](SHIELD.md) | 4 | One command on any repo says what would leak, in the tree, the index and the outgoing commits, and the same scanner stops an agent before it publishes. Every product declares its security contract in `teyla.toml` and `teyla shield check --release` is green before an upload. Every MCP server passes the injection corpus against its own handlers. |
| 5. "visualise and present status, questions to me and the result more clearly, so I can process it many times faster" | The session-end card in the policy | 4 | A results feed: every session that ended in the last 24 h as one card (status, result, links, what it needs) in the window. |
| 6. "a README must say clearly what the product is and how it helps … internal docs describe the decision process rather than the end state" | `teyla docs check`, Teyla's README rewritten | 6 | `teyla docs check --all` is clean on every public repo. Decisions live in PRs and `docs/decisions/`. |
| "delegate to AI agents as much as possible … give commands by voice … correct actions in real time, give tasks, answer questions … the primary tool here should probably be Codex" | Nothing | 1 | Push-to-talk in the window turns speech into an answer, a correction to a running session, or a new task in a product. New tasks run on Codex by default. A computer-use trial ran on one bounded task. |

## Decisions

1. **Teyla is the coordinator.** The window is the place to work; sessions are where agents
   work. Teyla reads the session stores, it does not replace them.
2. **Backlog: GitHub Issues per repo.** They are free, agents already use `gh`, and Linear had
   no activity in 30 days. The window counts open issues and PRs that wait on the owner's merge.
   A session that finds a bug it does not fix files an issue.
3. **iPhone: a client of the Mac, through an iCloud Drive folder.** The Mac writes the
   snapshot to `iCloud Drive/Teyla/`; the phone writes answers, corrections and new tasks to
   an outbox there; the Mac delivers them. No server, no cost. Each outbox entry is signed with
   a key the two devices share once by QR code, and the Mac refuses anything unsigned. The
   snapshot is visible to Apple unless Advanced Data Protection is on; the relay is off until
   the owner turns it on (`teyla relay on`).
   POLICY §14 trigger: the owner asked for iOS on 2026-10-17. Cheapest form: the same SwiftUI
   code as an iOS target, read and answer only, no Mac-side features.
4. **Voice: on-device speech recognition** (Apple Speech, `requiresOnDeviceRecognition`), in
   English, Spanish and Russian. No audio leaves the device. Push-to-talk in the window and a
   global shortcut on the Mac.
5. **New tasks: `teyla dispatch <product> -- <text>`** starts a session in a fresh worktree
   under `~/.worktrees/<repo>/`, Codex by default (`codex-lane`, behind the machine guard),
   Claude on request. Corrections to a running session go through `codex queue` or open the
   session; Teyla never resumes a session that is live, so two writers never share one transcript.
6. **Voice charts are the owner's, not the repo's.** They live in `~/.teyla/voice/<channel>/`,
   one file per language, each written from the brief by a native-level model, never translated.
   The repo keeps the template and `teyla voice check`.
7. **UX work happens in the product, the review happens in the window.** Variants are built in
   the product's repo; the owner reviews them on the phone; only accepted cuts are applied.
8. **Computer use: one bounded trial, attended.** It needs the owner present to grant app
   access, so it is not part of a night sprint.

## Night sprint 2 (2026-10-17)

| Lane | Ships | Model |
|---|---|---|
| 0 | This roadmap and the snapshot contract v2 (`docs/APP.md`, fixture, Swift models) | Opus 5.5 |
| A | `teyla state` v2: results feed, owner tasks, issue backlog, product dedupe | Sonnet 5.5 |
| B | `teyla relay`: iCloud Drive mirror, signed outbox, pairing key | Sonnet 5.5 |
| C | Mac window v2: results, tasks, new task, push-to-talk, corrections, pairing QR, icon, ⌘0 | Sonnet 5.5 |
| D | iPhone client: the same views, voice, answer and new task through the relay | Sonnet 5.5 |
| E | `teyla dispatch` and `teyla say` (corrections); the answer-delivery check | Sonnet 5.5 |
| F | Voice charts EN / ES / RU for the owner's build-in-public channel; `teyla voice check` | Sonnet 5.5 |
| G | `teyla intent cover` | Sonnet 5.5 |
| H | The largest app: five worst screens in two variants each, for review (its own session, in that repo) | Sonnet 5.5 |

Every lane lands as its own PR with a cross-provider review (`codex-review`; `--high` for B and
E, which carry the owner's data and start work). Opus 5.5 orchestrates, reviews and merges.

## Next

- iPhone in TestFlight once its App Store Connect record exists (owner step).
- Notifications on the iPhone for a new question (needs a push path; the relay folder cannot wake the phone).
- The computer-use trial (decision 8).
- UX passes for the other apps that `teyla ux check` rates FIX.
- `teyla docs check --all` fixes, one PR per repo.

## Owner decisions

- **Focus.** Codex recommends two active products and the rest parked. The window shows the load; the choice is the owner's.
- **Relay on or off.** Default off. Turning it on puts the snapshot in iCloud Drive.
