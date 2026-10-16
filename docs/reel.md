# Session Reel — `teyla reel`

Turns one agent session (Claude Code or Codex) plus the git history it produced into a
vertical 1080×1920 video. The video is a legible "terminal story" you can post or cut into
a longer episode. The reader should understand it at phone size, with the sound off, in
under a minute: what was asked, what the agents did, and what shipped.

Status: v0 spec, 2026-10-16.

## Why

A screen recording of a terminal is unreadable on a phone: tiny type, scrolling noise, and
whatever secret happened to be on screen. The session log already holds everything worth
showing — the ask, the edits, the test runs, the commits, the PRs and the cost — as
structured data. Rendering from that data gives large type and pacing that fits the story.
It also makes redaction a property of the pipeline rather than a hope.

## Commands

```
teyla reel list   [--since 24h] [--repo NAME]            # sessions with repo, span, commits, PRs
teyla reel story  <session-id> [--ask TEXT] [-o story.json]
teyla reel check  <session-id | story.json>              # every string that would be rendered
teyla reel render <session-id | story.json> [--seconds 45] [-o DIR]
```

- `<session-id>` accepts a prefix. A Claude Code session id and a Codex rollout id are both
  accepted; `list` prints both kinds.
- `render` writes `reel.mp4`, `reel.srt` (one caption per beat), `story.json`,
  `reel.txt` (every rendered string, one per line) and `contact.png` (nine keyframes). The
  default `DIR` is `~/Movies/teyla-reel/<yyyy-mm-dd>-<repo>-<id8>/`.
- `check` prints exactly what `reel.txt` would contain, then a count of what was dropped,
  by reason (`secret`, `private-term`, `email`, `path`, `too-long`). It never prints the
  dropped text.

## Pipeline

```
transcript (adapters/claude_code.py, adapters/codex.py)
   + git log of the session's repo between start and end
   → events            (tool calls and results, commits, PR commands)
   → redact            (every string, before it can enter a Story)
   → Story             (title, ask, beats, totals)  ← the only input the renderer sees
   → select + pace     (≤ 12 beats for 45 s)
   → frames (Pillow) → ffmpeg → reel.mp4
```

The stages are pure functions over plain data, except the last line. Each has tests built
on synthetic transcripts. The extraction, redaction and story stages have no dependencies,
like the rest of teyla. Rendering needs the optional extra `teyla[reel]` (Pillow) and
`ffmpeg` on `PATH`. Without them, `render` says what is missing and still writes
`story.json`, `reel.txt` and `reel.srt`.

## The Story

```
Story  { id, harness, repo, started, ended, ask, title, beats[], totals }
Beat   { t, kind, headline, lines[], diff? }
         t        seconds since the session started
         kind     ask | lane | edit | test | command | commit | pr | review
         headline ≤ 48 chars
         lines    ≤ 8 lines of ≤ 34 chars (monospace at ~52 px on 1080 wide)
         diff     ≤ 10 lines, each "+", "-" or " " prefixed
Totals { wall_clock, commits, files_changed, lines_added, lines_removed,
         tests_passed, tests_failed, prs_opened, prs_merged, lanes, cost_usd? }
```

Where beats come from:

| Event in the log | Beat |
|---|---|
| The first user message, or `--ask` | `ask`. With `--ask`, its text is used as given (after redaction); otherwise the first message, redacted, cut to 140 chars |
| `Agent` / sub-agent spawn | `lane`: the description |
| `Edit`, `Write`, `MultiEdit`, Codex `apply_patch` | `edit`: repo-relative path, +/- counts, the most telling hunk |
| A command that runs tests or a gate (`pytest`, `check.sh`, `swift test`, `xcodebuild test`, `npm test`, `bun test`, `cargo test`, `go test`) | `test`: passed or failed and the counts when the output has them |
| `git commit` | `commit`: the subject line |
| `gh pr create` / `gh pr merge` | `pr`: number and title |
| `codex-review` / `claude-review` | `review`: the P1/P2 counts it printed |
| Other shell commands | `command`, used only to fill gaps, never more than 2 |

Assistant prose and tool output beyond the counts above are never rendered in v0. This
rule keeps the leak surface small.

Selection: keep the ask and the last commit/PR, then pick beats in this order: failed then
passed tests, PRs, commits, the largest edits, lanes, and fill with commands. Spread them
over the session time and order them by `t`. Pacing: a 2.5 s title card, beats at 2–4 s
each (longer for diffs), and a 3 s end card with the totals.

## Redaction

Every string passes `reel.redact` before it can enter a Story, including file paths, commit
subjects and diff lines. Redaction drops a string rather than masking it: a masked secret
still tells the viewer where a secret was.

1. **Secrets** → drop the beat. This covers the patterns `leak_check.py` already knows
   (provider key prefixes, GitHub tokens, AWS key ids, Slack tokens, JWTs, PEM blocks), any
   `NAME=value` where `NAME` contains `KEY`, `TOKEN`, `SECRET` or `PASSWORD`, and any run of
   32 or more base64 or hex characters.
2. **Private terms** → drop the beat. The list is the one `leak_check` uses:
   `~/.config/teyla/private-terms.txt` or `$TEYLA_PRIVATE_TERMS`, with the same matching.
   When the session's repo name itself is a private term, `story` and `render` refuse to
   run unless `--allow-repo` is passed.
3. **E-mail addresses and phone numbers** → drop the line.
4. **Paths** → a path inside the repo becomes repo-relative. Any other absolute path
   becomes `…/<basename>`. A home directory or user name never survives.
5. **URLs** → reduced to the host, except `github.com/<owner>/<repo>/pull/<n>`, which is
   reduced to `#<n>`.
6. **Length** → anything longer than its slot is cut at a word boundary with `…`, never
   mid-token.

`reel.txt` is the audit trail: if a string is not in it, it is not in the video. The
renderer draws only `Story` fields, and a test asserts that every text it draws appears in
`reel.txt`.

## Look

- **Canvas.** 1080×1920, 30 fps, H.264, yuv420p, `+faststart`; no audio track in v0.
- **Theme.** Near-black background, off-white type, green for additions and passed tests,
  red for removals and failures, and one accent for the progress bar.
- **Fonts.** A monospace system font: Menlo on macOS, DejaVu Sans Mono on Linux;
  `--font PATH` overrides it. The headline is ≥ 64 px, the lines ≥ 48 px. The safe area
  keeps 160 px clear at the top and 320 px at the bottom for platform UI.
- **Layout, top to bottom.**
  - Top bar: the repo name, the harness badge (`claude` / `codex`) and the session clock
    (`02:14:07`, session time, not video time).
  - The beat card: kind label, headline, lines or diff. It slides in over 6 frames; no
    other motion.
  - Bottom: a progress bar of session time, plus live counters (commits, tests ✓, PRs)
    that tick up as beats pass.
- **End card.** `N commits · +A −R · T tests · P PRs · wall clock`, and the cost when
  known.

## Acceptance (v0)

1. `teyla reel list` shows today's Claude Code and Codex sessions with repo and span.
2. `teyla reel story` on a synthetic Claude transcript and a synthetic Codex rollout gives
   the expected beats (fixture tests).
3. Planted secrets, private terms, e-mails and home paths never reach `story.json` or
   `reel.txt`. The fixtures build those strings at run time, so no secret-shaped literal
   sits in the repo.
4. `teyla reel render` on a real session of this machine gives a playable 30–60 s
   `reel.mp4` at 1080×1920, plus the `contact.png` and `reel.txt` (a smoke test skipped
   when Pillow or ffmpeg is missing).
5. `./check.sh` is green, and `leak_check` is clean.

## Not in v0

Voice-over and music, picture-in-picture with an iPhone screen recording (a video editor composes
that), several sessions in one reel, landscape and square formats, and an LLM-written
headline.
