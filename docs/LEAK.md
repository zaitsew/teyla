# The leak scanner

Status: shipped 2026-10-31.

`teyla leak` is the one scanner for what must not leave your machine: private terms, personal e-mail
addresses, home paths, secrets, and an image that carries a position. The hooks, `check.sh` and the agent
hook call it. It makes no network call. It is the scanner of Shield, Teyla's leak-prevention work.

Quick start:

```
teyla leak                       # this repo: tracked files, plus .env* files that are only on this machine
teyla leak --staged              # what the next commit would publish (read from the index)
teyla leak --outgoing            # commits and tags that origin's tracking refs lack
teyla leak --text body.md        # a PR body, before `gh pr create`
```

Private terms live outside every repo, in `~/.config/teyla/private-terms.txt` (or the file `$TEYLA_PRIVATE_TERMS`
names). The format and the rest of the first-time setup are in [CONTRIBUTING](../CONTRIBUTING.md).

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
| `term` | a private term (whole word; `-name-` counts) | blocker |
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
`term:<index>`, its position in the terms file, in every string: a path, a place, a note, an error and the JSON are
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
  file that does not exist yet, a `cd` into a variable). Files resolve in the directory the command runs in
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
- It does not ask the network which commits or tags the remote has. `--outgoing` trusts the remote-tracking refs
  (run `git fetch` first when they may be stale), and it scans tags only on commits it scans.
- It does not scan other branches than the one checked out for `--outgoing`; use `--commits` for a range.
