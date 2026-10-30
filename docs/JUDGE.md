# The judge and the reference library

Status: shipped in Sprint 1 of [Studio](STUDIO.md) (decisions S7 and S9, lane D). Three parts: `teyla ux judge`
compares two screens, `templates/design/REFERENCE.md` names the screens to compare against, and the calibration
set tells you whether to trust the judge on a product. The weekly scout that keeps the library current is in
[SCOUT.md](SCOUT.md).

```
teyla ux judge before.png after.png --repo atlas          # which screen is better, on five items
teyla ux judge ours.png reference.png --repo atlas        # ours against a reference screen
teyla ux judge A.png B.png --dry                          # print the prompt, call nothing
teyla ux judge --calibrate atlas                          # does the judge agree with you on your decided pairs
```

Quick start: `claude` on the PATH and signed in, two screenshots, `teyla ux judge A.png B.png`. The first run
prints a note that the judge is not calibrated on a product yet; that is true until `--calibrate` passes.

## What it does

A vision model is a judge only in pairs. Scores of one lone screenshot have no evidence behind them; a
comparison of two does (docs/STUDIO.md §3). `teyla ux judge` sends both pictures and the five items of Part 5 of
[`STANDARD.md`](../templates/design/STANDARD.md) to Sonnet 5.5 (`--model` changes it), with the product's
`DESIGN.md` (first 12,000 characters) when `--repo` names one. Each picture gets 0, 1 or 2 on each item:

| Item | Asks |
|---|---|
| Task hierarchy | Is the primary action obvious at a glance? |
| Native conventions | Does it use the platform's own controls and placements? |
| Readability | Type sizes, contrast, truncation |
| Layout coherence | Spacing, alignment, one grid |
| Copy and brand fit | The voice chart and the glossary of `DESIGN.md` |

An item the picture cannot show is **not assessed**, never guessed (for example, copy and brand fit when no
`DESIGN.md` is given). The code adds up the scores, not the model:

- The totals count only the items that both pictures were assessed on, so a gap in one picture does not
  decide the winner.
- The winner is `A`, `B`, or `tie` when the totals are equal. Ties and "feels native" go to you.
- A picture with a 0 is flagged: the standard calls a screen with a 0 not done.

Output: the winner, the totals, then for each item one line per picture saying what the model saw, and
`--json` the same as data (`winner`, `totals`, `assessed`, `items`, `zeros`, `order_consistent`, `cost_usd`).

The judge **never gates a merge**. It flags a regression; it cannot certify good UX. The diff and the owner
decide. A product's score is the share of its screens that beat their reference, not a 1 to 10 feeling.

`--both-orders` asks twice, the second time with the pictures swapped, and answers `tie` when the two answers
disagree on the winner. Models prefer the first picture more often than chance, so use it for pairs that
matter and in the calibration run when the judge shows a position habit (all its mistakes on one side).

## How the pictures travel

`claude -p` is started with no tools, no skills, no MCP and no saved session (the call `teyla review triage`
makes) and reads one stream-json message on stdin. The two pictures are base64 image blocks in that message, so
the model is never given a file tool to read your disk. A picture is a PNG, JPEG or GIF of at most 5 MB (the API's
limit for one image); a larger one is refused with a `sips -Z 1600` hint. If your `claude` is too old for
`--input-format stream-json`, update it; there is no second path on purpose. What leaves the Mac: the pictures and
`DESIGN.md`, to Anthropic ([PRIVACY.md](PRIVACY.md), row 25). Safe mode refuses the call without `--allow-network`;
`--dry` never calls. Everything in a picture or in `DESIGN.md` is marked to the model as data, not instructions.

## Calibration: 16 of 20 before you rely on it

A judge is used on a product only after it agrees with you on 16 of 20 pairs you already decided. Make those
pairs once and keep them in the product's repo, in `design/references/calibration/`. One JSON file per pair:

```json
{
  "a": "list-v1.png",
  "b": "list-v2.png",
  "pick": "b",
  "date": "2026-10-30",
  "note": "v2 has one clear add control"
}
```

- `a` and `b` are file names of two pictures in the same folder (PNG, JPEG or GIF, at most 5 MB each).
  No paths: a name with a slash or `..` makes the file skipped.
- `pick` is `a`, `b` or `tie`: what you chose, before you saw the judge's answer.
- `date` is when you decided. `note` is optional, one line.
- The file name (without `.json`) is the pair's id in the report.

Choose pairs that cover the product's screen types and that you can defend. Mix the sides: if you always pick
`b`, the judge's habit for the second picture will look like agreement. `--calibrate` prints the counts of `a`,
`b` and `tie` in `--dry`.

```
teyla ux judge --calibrate atlas
atlas: the judge agreed with the owner on 17 of 20 pair(s) (16 of 20 needed)
  ok  list-1: owner b, judge b
  no  detail-3: owner a, judge b
  ...
calibrated: the judge may be used on atlas (it still never gates a merge)
```

It judges each pair, counts a match when the judge's winner equals your pick, and exits 1 when the product is not
calibrated. The rule: at least 20 usable pairs and agreement on at least 80% of them (16 of 20). A pair whose call
failed counts as a disagreement and shows its error. The result is written to
`design/references/calibration-result.json` (`date`, `model`, `pairs`, `agree`, `calibrated`); a later
`teyla ux judge --repo atlas` reads it and prints a note on stderr while the product is not calibrated. A new
model or a changed standard is a reason to run `--calibrate` again. A run makes one model call per pair (two with
`--both-orders`) and prints the total cost in `--json`.

## The reference library

`templates/design/REFERENCE.md` lists, per screen type (onboarding, list, detail, settings, chat, voice,
timeline), up to three named reference screens, what to copy from each, and a link. A reference is a named screen,
not a library of thousands: a successful app does not always have a good UI. The first entries are the set the
research returned (Things, Flighty, Structured, Tiimo, Sunsama's ritual, ChatGPT voice, Finch, and the 2026 Apple
Design Awards apps Moonlitt and grug). Entries marked **to confirm** come from an award text or a second-hand report: open
the app and replace the line before relying on it.

A product copies the files in `templates/design/references/` to `design/references/` and edits them. The format
is the one in [TASTE.md](TASTE.md): `screen_type`, then a list of `name`, `what_to_copy` and `link`. The weekly scout
may propose a change to this file; a person decides.

## Errors

| Message | Meaning |
|---|---|
| `not a PNG, JPEG or GIF` | The file's first bytes are not an image |
| `claude exited N` | `claude` is missing, not signed in, or too old for stream-json |
| `the model reply was unusable` | The reply was not the JSON of five items; nothing is guessed. Run it again |
