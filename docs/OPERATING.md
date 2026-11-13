# Operating

The operating pieces: report-only views that show where the work stands.

## Inbox expiry

`teyla asks expire [--older-than DAYS] [--product P] [--json] [--apply] [--note TEXT]`

A question older than 14 days takes its default or is dropped. The default mode is a dry run: it lists each
candidate and the outcome it would get, and changes nothing. It reads local data only and makes no model call.

Candidates are open questions older than `--older-than` (default 14), oldest first. Reminders are left out: their
age is a due date. Muted asks of parked products are included and flagged `muted`.

The default is never guessed. The first rule that matches wins, and `default_source` names it:

1. `triage`: the cached triage default in `~/.teyla/state-triage.json`.
2. `recommended`: an option marked "(Recommended)".
3. `stated`: a sentence that states a default ("default:", "by default", "if you say nothing").
4. `design`: the first option of a design card (recommended first by contract).
5. `none`: no default. The outcome is `drop`.

Outcomes: `default`, `drop`, or `keep`. An ask that names a price, a key or a person, or is critical, is never
expired: it is listed as `keep`.

`--apply` closes the `default` and `drop` items in the done store, with the note `expired: default <text>
(<source>)` or `expired: dropped` (`--note` goes in front). It sends no answer to any session: `teyla answer` does
that. Undo with `teyla asks undo <id>...`.

`--json` prints `{version, older_than_days, dry_run, items, counts}`.
