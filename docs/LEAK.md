# The leak scanner

Status: shipped 2026-10-31.

`teyla leak` is the one scanner for what must not leave your machine: private terms, personal e-mail
addresses, home paths, secrets, and an image that carries a position. The hooks, `check.sh` and the agent
hook call it. Only `--published` uses the network (through `gh`); every other surface reads git objects and files. It is the scanner of Shield, Teyla's leak-prevention work.

Quick start:

```
teyla leak                       # this repo: tracked files, plus .env* files that are only on this machine
teyla leak --staged              # what the next commit would publish (read from the index)
teyla leak --outgoing            # commits and tags that origin's tracking refs lack
teyla leak --text body.md        # a PR body, before `gh pr create`
teyla leak --published           # what is already public for the owners of your remotes (needs gh)
```

Private terms live outside every repo, in `~/.config/teyla/private-terms.txt` (or the file `$TEYLA_PRIVATE_TERMS`
names). The file has two sections, described under [Private terms](#private-terms). The first-time setup is in
[CONTRIBUTING](../CONTRIBUTING.md).

## What it reads

| Surface | Command | Class |
|---|---|---|
| Tracked files in the working tree | `teyla leak [repo]` | publishable |
| The index, as blobs (`git show :path`), never the working tree | `--staged` | publishable |
| Commits the remote lacks: messages, author and committer, added lines, changed images and plists; annotated tags on them | `--outgoing [remote]` | publishable |
| An explicit range (the same range syntax as `scripts/leak_check.py --commits`) | `--commits RANGE` | publishable, or historical |
| A PR body, issue, release note or commit message | `--text FILE\|-` | publishable |
| `.env*` files and harness configs that are present but not tracked | default run | local-only |
| Every git repo under `code_root` | `--all` | as above, repo by repo |
| What is already public on GitHub for an owner | `--published [owner]` | historical |

Beyond text, it reads these structures. Screenshot pixels are never read.

- `*.plist` and `*.entitlements` with `plistlib` (binary plists too): every string is scanned.
- `*.xcstrings` with `json`: every string is scanned, except that Cyrillic in a localisation is not a finding.
- PNG `tEXt`, `zTXt` and `iTXt` chunks and JPEG comment and XMP segments: scanned with the text rules.
- PNG `eXIf` and JPEG EXIF: a GPS block (tag 0x8825) or an Artist tag (0x013B) is rule `image-metadata`, a blocker.
- Harness configs (`.claude/settings.json`, `.claude/settings.local.json`, `.mcp.json`, `.cursor/mcp.json`,
  `.vscode/tasks.json`, `.codex/config.toml`): a `command`, hook command, `args`, `url` or `base_url` that points
  outside the repo, or at a host that is not loopback, is rule `harness-config`, a blocker. A variable
  such as `$CLAUDE_PROJECT_DIR` or `${workspaceFolder}` counts as inside the repo.

## Rules and severities

| Rule | Matches | Severity |
|---|---|---|
| `term` | a private term (whole word; `-name-` counts); a `[teyla]` term only inside Teyla's repo | blocker |
| `email` | an address except `example.*`, noreply and `git@host` | blocker |
| `home` | `/Users/<x>/` or `/home/<x>/` for a real-looking `<x>` | blocker |
| `secret` | a key with a known shape (GitHub, Anthropic, AWS, Slack, JWT, PEM, and more) | blocker |
| `secret-generic` | a `key`, `token` or `password` assignment with a long, high-entropy value and no known prefix | triage |
| `harness-config`, `image-metadata` | see above | blocker |
| `gitleaks:<RuleID>` | gitleaks' default rules, when `gitleaks` is on the PATH | blocker |
| `cyrillic` | any character in U+0400 to U+04FF | lang |

A **blocker** gives exit 1. **Triage** is listed and never blocks: the aim is that nobody learns to type an
override. **Lang** is the language policy (`teyla lang` is its home) and never blocks.

An ignored `.env` is local-only and its blockers are listed as triage: the file is not published. An untracked
`.env*` that is not ignored keeps its blockers, because `git add -A` would publish it.

## Classes

- **publishable**: in the tree, the index, an outgoing commit or a text about to be sent.
- **historical**: in a commit that a remote-tracking ref already reaches (`--commits` on pushed history). The first
  line of the finding says `rotate first`: the credential is public, and deleting it from the tree does not help.
- **local-only**: present on this machine, not tracked.

## Output

Every match prints as its first two characters, an ellipsis and its length: `sk…43`. A private term prints only as
`term:<index>`, its position in the terms file (see [Private terms](#private-terms)), in every string: a path, a place, a note, an error and the JSON are
scrubbed, so a file named after a term prints as `term:0-notes.txt`. Its fingerprint does not depend on its text. A
finding has a fingerprint, the first 12 hex of `sha256(rule + path + match)`. For a gitleaks finding the match is
the sha256 of the line it sits on (gitleaks redacts the secret), and for image metadata it is the EXIF payload, so
swapping a fixture for a live value is a new finding. Findings with the same rule and fingerprint are one finding
with every place listed, so a key added in ten commits is one line.

`--json` prints `{"findings": [{rule, class, severity, path, line, masked, fingerprint, places}], "coverage":
{read, unread, notes}, "errors", "exit"}`. `--quiet` prints the number of blockers. Text output ends with the coverage:
the surfaces read, the ones not read and why, and notes.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | every requested surface was read and nothing blocks |
| 1 | at least one blocker (this wins over 2: fix it first) |
| 2 | a surface could not be read, with no blocker: an explicit `$TEYLA_PRIVATE_TERMS` file that is missing, a shallow clone for `--outgoing`, no such remote, a binary plist or harness config that does not parse, PNG text that inflates past the cap, a file skipped (see below), gitleaks failing, `--require-gitleaks` unmet, a malformed `.leak-allow`, a usage error |

A malformed `.leak-allow` does not stop the scan: the valid entries apply, blockers are reported, and the error
(the line number only, never the line) adds exit 2 when nothing blocks.

**One guarded reader.** No file is read whole without a cap. A file or blob over `--max-bytes` (default 4 MB), a
file that is not regular, and a file whose real path leaves the repo (a symlinked `.claude`) are listed as not read and
give exit 2; `--allow-partial` accepts that. A binary file over the cap with no structured reader is only counted in
a note: it would be skipped as binary at any size. A symlink is scanned as its target, and a target in a home
directory is rule `symlink-outside`. Git's `-diff` attribute and path quoting change nothing: paths come from `-z`
output, and Teyla reads the blobs and decides text from binary itself.

A missing scanner or an unread surface is never a pass. If no terms file exists at the default path and
`$TEYLA_PRIVATE_TERMS` is unset, the run notes that the term rule did not run and does not fail.

## gitleaks, the second engine

When `gitleaks` is installed, `teyla leak` runs it as a local process and merges its findings as
`gitleaks:<RuleID>`: `detect --no-git` over a staging copy of the tracked files (hard links, so build directories
are not read), `protect --staged` for `--staged` when the installed version has it, and `detect --log-opts` for a
range. It passes `--redact` and an explicit default config, so a repo cannot switch the engine off with its own
`.gitleaks.toml` or `.gitleaksignore`. Without it, one coverage note says so and the exit code does not change.
`--require-gitleaks` turns that note into exit 2, on every surface: `--text` runs `detect` over the text, and
`--staged` needs a gitleaks with `protect --staged`. A text over gitleaks' size limit is a coverage note, and exit 2
with the flag.

## The allow-list

`.leak-allow` and the terms file are read with a 256 KB cap; a larger one, or a symlinked `.leak-allow`, is exit 2.
It keeps its sections (`emails`, `paths`, `home`, `cyrillic`, `secrets`), one glob per line; they apply
to gitleaks findings too. A section can be followed by an optional `[exceptions]` block, one line per exception:

```
[exceptions]
term vendor/* upstream sample text, not ours until=2026-12-31
secret tests/fixtures/*.pem a fake key the test needs fp=<12 hex from the report>
```

The fields are `rule glob reason`, then `until=YYYY-MM-DD` and `fp=<12 hex>` in any order. The rule is an exact
rule name or `gitleaks:<RuleID>`; a pattern or an unknown name is an error. An exception never applies to a finding
whose matched line could not be read (it says `line unread`). An exception past its `until` date is ignored and reported as `expired exception`. An exception for a
secret rule whose glob matches every file is an error (exit 2): a whole file is never exempt from the secret
rules, only named files or one fingerprint. Editing `.leak-allow`, the terms file or the scanner is itself a
change to review as one that touches credentials.

## What is already public

```
teyla leak --published [owner] [--max-requests N] [--json] [--quiet] [--allow-network]
```

The other surfaces stop a leak on its way out. This one reads back what is already out. For each public repo of the
owner (a user or an org; with no owner, the owners of the GitHub remotes of the repos under `code_root`, read from
`git config`) it asks `gh` for:

| Text | Call | Cap |
|---|---|---|
| Description and homepage | `gh repo list <owner> --visibility public --json ...` | no extra call |
| README | `gh api repos/<o>/<r>/readme` (base64) | 1 call |
| Author and committer name and e-mail, and the message, of the default branch's last 100 commits | `gh api repos/<o>/<r>/commits?per_page=100` | 1 call |
| Titles and bodies of open, and of recently closed (90 days), issues and pull requests | `gh api repos/<o>/<r>/issues?state=...` | 200 items, 100 per page |
| Release names and notes | `gh api repos/<o>/<r>/releases?per_page=50` | 50 releases, 1 call |

Everything goes through the same rules and the same masking as every other surface, so a private term still prints as
`term:<index>` and an address as two characters, `…` and a length. Findings are class `historical`. The first line
of the text output is `already public: fix the source and, for a credential, rotate first`: editing the README or the
issue removes the text from the page, not from copies, so a credential is rotated before anything else. A commit identity
that repeats in 100 commits is one finding with its places listed. An `.leak-allow` exception applies to a finding by
rule and by the path `<owner>/<repo>/<surface>` (`README`, `commits`, `issue#12`, `pr#7`, `release:<tag>`,
`description`, `homepage`).

- **Public only.** A repo that `gh` lists as private is skipped and never fetched, and a note counts it. Forks are
  skipped too: their README, commits and issues are somebody else's text.
- **Budget.** Each `gh` call counts, and `--max-requests` (default 400) stops the audit. Hitting it adds one note
  (`request cap hit`, with the number of repos audited and not) and the exit code is the findings' own; when the cap is spent
  before anything was scanned, the surface is unread and the exit is 2. Nothing is cached: every run asks again. The
  list of repos is capped at 200.
- **Network.** One `gh` login, one host (`api.github.com`), [PRIVACY](PRIVACY.md) row 34. It sends only the owner and
  repo names. Safe mode refuses without `--allow-network` (exit 2).
- **Exit codes** are the usual ones: 1 a blocker, 2 `gh` missing or not signed in, a repo list or a surface that did
  not answer, or the refusal above.
- **Not covered:** issue and PR comments, gists, wikis, GitHub Pages, release assets, other branches, and the names of
  tags and branches. Repos the owner contributes to but does not own are out of scope.

**Weekly.** The Friday weekly routine runs `teyla leak --published --quiet` next to `teyla deps --all --quiet` and files
the output as `leak-published.md`. The run writes `~/.teyla/leak/published.json`; while it holds a blocker, the digest
carries one line, `N already-public finding(s)`, for 14 days. A wrapper from before this line is stale, and
`teyla routine install --if-stale` adds it. Teyla runs no CI on push or pull request. For someone without
the laptop routine, a manual workflow is the alternative. It has no `schedule` trigger. Add one only if it is no more
frequent than weekly:

```yaml
name: leak-published
on: workflow_dispatch          # by hand; a schedule, if any, no more often than weekly
permissions:
  contents: read
jobs:
  audit:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
        with: { repository: zaitsew/teyla, path: teyla }
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install ./teyla
      - run: teyla leak --published ${{ github.repository_owner }} --allow-network
        env:
          GH_TOKEN: ${{ github.token }}
```

`github.token` reads public data here, which is the point. Private terms live outside every repo, so a hosted run
applies the secret, e-mail and home-path rules only, and says in a note that the term rule did not run.

## Install

```
teyla leak install [repo] [--all] [--uninstall]
```

`teyla leak` takes a repo as its positional argument, so the two sub-commands are registered as `teyla leak-install`
and `teyla leak-terms`; `teyla leak install` and `teyla leak terms` (with `--suggest`, `list` or `move`) are rewritten to them before parsing. A repo
directory that is literally named `install` or `terms` needs `./install`.

- Writes `.githooks/pre-commit` (`teyla leak --staged --quiet`) and `.githooks/pre-push`
  (`teyla leak --outgoing "$1" --quiet`; git passes the remote name as `$1`): POSIX `sh`, executable. Sets
  `core.hooksPath` to `.githooks`. When the scan fails, the hook runs it again without `--quiet` so the masked
  findings print, then exits with the scanner's code: 1 for a blocker, 2 for a surface it could not read.
- A hook that is already there and is not ours keeps its content. Our call goes in at the top (after a shebang)
  between `# >>> teyla leak gate` and `# <<< teyla leak gate`. If `core.hooksPath` already names another directory
  inside the repo, the hooks go there; a path outside the repo is refused. Running it twice changes nothing.
- No `teyla` on PATH when the hook runs: one line, `teyla leak gate: teyla not found; install it or set TEYLA_LEAK=0
  for this command`, and exit 2. A missing scanner is a coverage gap, not a pass.
- `TEYLA_LEAK=0 git commit ...` skips the hook for that command and appends date, repo and hook to
  `~/.teyla/leak-skips.log` (`$TEYLA_HOME` moves it).
- `--uninstall` removes only our files or our delimited block, and unsets `core.hooksPath` only when the install set
  it (recorded in `.githooks/.teyla-leak-gate`). `--all` does this for every repo under `code_root`, one line each.
  Nothing is committed: review and commit the hooks directory in each repo. `core.hooksPath` is per clone, so each
  clone runs the install once.

## Private terms

### The file: two sections

The terms file holds two kinds of term.

- **Kind A, `[everywhere]`**: things that must never appear in any repo. The owner's e-mail addresses, hosts,
  personal names and tester accounts.
- **Kind B, `[teyla]`**: names that must never appear in Teyla's own public repo, because Teyla's docs never name
  the owner's products. Product and organisation names. They are all over each product's own repo, so
  there they are not a finding.

```
# kind A: lines before any header, or under [everywhere]
jdoe-handle
allow jdoe-handle in commit:*:author

[teyla]
# never in Teyla's repo: product and organisation names
some-product
some-org

[everywhere]
mail-host.example
```

- Lines before any header belong to `[everywhere]`, so a file with no headers behaves exactly as it always did.
- A header is `[everywhere]` or `[teyla]`, on a line of its own, any case. A header may repeat. Any other bracketed
  line is an error: exit 2, naming the line number and nothing else.
- `#` comments and `allow <term> in <glob>` lines work in both sections. An `allow` line names the term, not a
  section, so it applies wherever the term is checked.
- A term written in both sections is kind A: the stronger section wins.

**Index.** A term's index is its position among the distinct terms of both sections, counted from 0 in file order
(a repeated term counts once, at its first line). It is the same in every repo and every surface, and it is what
`term:<index>` prints. Moving a term between sections rewrites the file, so indices can shift; `teyla leak terms
move` prints the old and new index of each term it moves. A `fp=` in a `.leak-allow` exception for a `term`
finding depends on the index, so check it after a move.

**Is this repo Teyla's?** The scanner finds the repo root (the nearest directory with a `.git`, a file in a linked
worktree) and reads its `pyproject.toml`. The repo is Teyla's when `[project] name` is `teyla`. There is no marker
and no setting: a fork under another name is not Teyla's, and a directory outside every git repo is not either.

- `teyla leak [repo]` decides from `repo` (default: the current directory). `--all` decides repo by repo.
- `--text` and `scan_text` with no repo argument decide from the current directory. A PR body checked from inside
  Teyla's checkout gets both kinds; the same body checked from a product's checkout, or from anywhere else, gets
  kind A only.
- `scripts/leak_check.py`, which `check.sh` runs with no install, applies the same rule with the same file, so
  inside Teyla it checks both kinds.
- Output masking covers every term of either kind, in every repo, whether or not the term applies there: only the
  rule depends on the section. The fallback script's excerpts mask a match under 4 characters to `***`. A path that holds a `[teyla]` term prints as
  `term:<index>` even where the term is allowed.

### Sorting an existing file

Both commands print an index, a section and a masked form (first two characters, `…`, length; a term under 4
characters shows none: `*…2`). They never print a value, in `--json` either.

```
teyla leak terms list [--json]
teyla leak terms move <index>... --to teyla|everywhere [--json]
```

`list` prints one row per term: `term:0  everywhere  jd…11`, that is the index, the section and the masked form.
`move` prints one row per moved term, `term:1 -> term:2  everywhere` (old index, new index, section), and a count.

`list` reads the file in the order the scanner does. `move` takes indices as printed (`3` or `term:3`) and writes
each moved term once, at the end of the target section (the last block of that section; for `teyla`, a new
`[teyla]` block with a comment is added at the end of the file when there is none; for `everywhere`, a file with no
such lines gets it ahead of the first header). Every other line, comments and `allow` lines included, stays where it
is, and a term already in the target section stays put. The file is replaced atomically through a 0600 temporary file
in the same directory, so a loose mode is tightened; a symlinked file is refused. An index out of range, or no
`--to`, is exit 2 and the file is untouched.

### Suggestions

`teyla leak terms --suggest [--yes] [--json]` lists candidates for the terms file from facts this machine already
knows: `git config user.name` and `user.email` (global and this repo), the login name, the home directory's name, the
computer name (`scutil`, or the hostname), tester e-mails in this repo's `teyla.toml` `[productize]`, bundle-id
organisations in its `[release]`, and the server, domain, mail sender, tester and owner entries in
`~/.teyla/platform.toml`. It never reads another repo's content. Values already in the file, generic names
(`root`, `localhost`, ...) and anything under 4 characters are skipped.

Every candidate prints as its first two characters, `…`, its length, its section and its source; the full value
never reaches stdout, in `--json` either. Bundle-id organisations are product and organisation names and go under
`[teyla]`; everything else goes under `[everywhere]`. Without `--yes` nothing is written. With `--yes` the values are
appended to the terms file (`$TEYLA_PRIVATE_TERMS` or `~/.config/teyla/private-terms.txt`), created with the
directory at 0700 and the file at 0600, and loose permissions on the default location are tightened. A value goes
in the section in force at the end of the file when that is its own, and under a new header otherwise; the output
is the count added.

## Leak guard

`plugin/hooks/leak-guard.sh` is the agent's door to the scanner: a PreToolUse hook on Bash, Read, Edit and
Write. A command with none of its fixed tokens and no quoting, `$` or backtick passes at once, with no process
started. One with quoting is parsed word by word, so `g''h p''r` and `cred''entials` are what they spell.

- **Publications.** The title, body, notes, message, comment or description of `gh pr|issue|release|gist|repo`
  and `gh api` calls and of `git commit|tag|merge`, plus a `-F`/`--body-file` file, a heredoc, a `$(cat ...)`
  and a piped `cat` or `echo`, go to `teyla leak --text -`. Exit 1 is a refusal with the masked lines; so is
  exit 2, with its coverage note. The hook never prints the text it scanned.
- **Credential paths.** `~/.ssh/id_*` (not `.pub`), `~/.aws/credentials`, the private-terms list (and the file
  `$TEYLA_PRIVATE_TERMS` names), `~/.appstoreconnect/`, `~/.grok/config.toml`, `~/.codex/auth.json` and
  `config.toml`, `~/.claude/.credentials.json`, `~/.netrc`, `~/.docker/config.json`, and `*.pem` or `*.p8`
  outside the repo are not read, copied or edited. `ls`, `stat` and `test` on them pass. Prose that names a
  path (an `echo`, a commit message, a heredoc) is not a read.
- **Keychain and visibility.** `security find-generic-password|find-internet-password` with `-w` or `-g`,
  `security dump-keychain` and `gh repo edit --visibility public` are refused. `gh repo create --public` is not.
- **Failure.** A command with no token passes even when the hook errors (one warning line). A command with a
  token is refused when python3, the `teyla` package or the scanner is missing, crashes or times out, and when
  the text cannot be read (a `$VAR` or an unreadable `$( )` body, a pipe from an unknown program, a body
  file that does not exist yet, a `cd` into a variable, a program name that comes from an expansion, `$( )` or
  `${` in text fed through stdin). Files resolve in the directory the command runs in
  (`cd`, `git -C`, `env -C`); a link that ends at a credential is a credential.
- **Skip once.** Put `TEYLA_LEAK_GUARD=0` first in the command, as an assignment word before the executable
  (or in the hook's environment). Each skipped publication is appended to `$TEYLA_HOME/leak-skips.log`
  (time and kind, never the text). It lifts only the publication scan, never a credential, Keychain or
  visibility rule.

It is one door of four, not the wall: an encoded payload, a body built from a variable set in an earlier call,
a release asset and the Grep tool are outside it. Wiring for Codex and Grok is in [HARNESSES](HARNESSES.md).

## For code that calls it

`teyla.leak` offers `scan_text(text, cfg=None) -> list[Finding]`, `scan_repo(root)`, `scan_staged(root)`,
`scan_outgoing(root, remote)`, `scan_range(root, rng)` (each a `Result` of findings and coverage),
`exit_code(result, require_gitleaks=False, allow_partial=False)`, `render(result)` and `to_json(result, code)`. The rules are
`scripts/leak_check.py`, which `teyla.leak` imports; that script keeps its own CLI and exit codes, so the pre-push
hook and `check.sh` need no Teyla install.

## What it does not do

- It does not rewrite history and does not rotate a key. A historical finding says to rotate first; removing it
  from history is a separate, deliberate step.
- It does not read pixels. An address shown inside a screenshot needs OCR and a person.
- Apart from `--published`, it does not ask the network which commits or tags the remote has. `--outgoing` trusts the remote-tracking refs
  (run `git fetch` first when they may be stale), and it scans tags only on commits it scans.
- It does not scan other branches than the one checked out for `--outgoing`; use `--commits` for a range.
