# The security contract

Status: shipped 2026-10-31.

A product declares what it must keep in a `[security]` section of its `teyla.toml`.
`teyla shield check <repo>` reads the repo for what files can prove, and reads dated evidence rows for
what they cannot. Evidence expires. A permanent checked box is theatre; a stale receipt is a STALE line.

```
teyla shield check ~/repos/thing             # one repo against its tier
teyla shield check ~/repos/thing --release   # the step before an upload: STALE blocks too
teyla shield check ~/repos/thing --json      # the same, for a script
teyla shield check ~/repos/thing --identity  # also ask GitHub whether the active gh identity can push and merge
teyla shield                                 # one table for every repo that has a [security] section
```

Exit 0: no FIX (and no STALE with `--release`). Exit 1: a FIX, or a STALE with `--release`.
Exit 2: the repo has no `[security]` section; the command prints the template to paste. The same text is
in `templates/repo/teyla.toml`, so a scaffolded repo starts with it.

## The section

```toml
[security]
tier = "public"                         # owner | family | testers | public
data = ["account", "location"]          # account location health messages payments files | ["none"]
trifecta = ["private-data", "outbound"] # the legs this product's agent surface has
secrets = "runtime-env"                 # runtime-env | keychain | hub | none
hosts = "docs/PRIVACY.md"               # the outbound-host table
mcp = { auth = "bearer", url_key = false, rate_limit = true, static_tools = true }
rls = "migrations+ab-test"              # none | migrations | migrations+ab-test
release = ["leak", "hosts", "deps", "rls-test<30d", "privacy-manifest"]

[[security.evidence]]
what = "rls-test"
commit = "abc1234"
date = 2026-10-31
how = "deno task test:tenancy (anonymous, A, B on every table and RPC)"
max_age_days = 30                       # optional; default 30
```

- `tier` is optional. It defaults to `[productize] users`, and to `owner` when that is missing. An explicit
  tier wins, and a tier below `users` prints a NOTE.
- `trifecta` lists which of private data, untrusted content and an outbound channel the agent surface has.
  All three at once is a FIX: cut a leg, or record an `executor-split` evidence row that says how a
  separate executor validates what the research step proposed.
- `secrets` of `repo` or `client` is a FIX.
- `mcp` describes the product's MCP server, if it has one. `static_tools` is recorded for the probe.
- `release` adds requirements to the `--release` run. A suffix such as `<30d` tightens that evidence limit
  for the run. Names are the requirement names below.
- An evidence row needs all four of `what`, `commit`, `date` and `how`. The commit is 7 to 40 hex characters and,
  in a git checkout, a commit the repo has. A row dated in the future, missing a field or naming a commit the repo
  does not have is a FIX on `contract`, and does not count as evidence.

## Requirements by tier

| Tier | Requirements |
|---|---|
| owner | contract, leak, hooks, hosts, lockfile, secrets, trifecta; rls when the repo has migrations; mcp when declared |
| family, testers | owner, then rls-test, privacy-manifest, no-token-in-defaults, mcp; probe when an `mcp` section exists |
| public | family, then deps and credential-separation |
| any tier, `--release` | family and above add release-notes; every name in `release` is added |

## What reads what

| Requirement | Source | OK when |
|---|---|---|
| contract | the section | tier, data classes, legs, rls and evidence rows are well formed; `data` is declared |
| leak | repo | the leak scanner exits 0 (the `leak` command when this Teyla has it, else Teyla's own `scripts/leak_check.py`); the repo's copy is never run; no scanner is a FIX |
| hooks | repo | `.githooks/pre-commit` and `pre-push` are executable and `core.hooksPath` is `.githooks` |
| hosts | repo | the `hosts` file has a table; where Teyla has a `hosts` command it must also exit 0 |
| lockfile | repo | each npm, Deno, SwiftPM, Python, Ruby, Go or Cargo manifest has its lockfile |
| rls | repo | migrations replayed in file-name order leave every public table with row level security on (`disable`, `drop`, `rename` and quoted names are followed); other schemas are skipped |
| privacy-manifest | repo | an Xcode project exists and `PrivacyInfo.xcprivacy` does too (n/a without Xcode) |
| no-token-in-defaults | repo | no Swift or Kotlin line writes a token, secret, password or API-key name to UserDefaults or SharedPreferences |
| secrets | repo | the declared place is not repo or client, `.env` is ignored, no `.env`, `*.p8`, `*.pem` or `id_rsa` is tracked |
| mcp | section | `url_key` is not true; `auth` is not none above `owner`; a public server rate-limits |
| trifecta | section | fewer than three legs, or an `executor-split` row inside its limit |
| release-notes | repo | `docs/APP-STORE.md`, `docs/PLAY-STORE.md` or `store/REVIEW-NOTES.md` has a `DATA` paragraph of real text: no `TODO`, not the template's example product, not a stub |
| rls-test | evidence `rls-test` | a row inside its limit (n/a without migrations) |
| deps | evidence `deps` | a row inside its limit; the dependency audit will record it |
| probe | evidence `mcp-probe` | a row inside its limit |
| credential-separation | evidence `credential-separation` | a row inside its limit |

Every subprocess runs from a neutral directory, and Python ones in isolated mode, so a repo cannot shadow
Teyla or supply the scanner. The checks are static greps and file tests. `no-token-in-defaults` misses a key built at run time, and
`rls` does not read the live database; the `rls-test` row is what proves tenancy.

## FIX, STALE and NOTE

- **FIX**: the fact is wrong or the evidence is missing. Always exits 1.
- **STALE**: the evidence exists and is older than its limit. Exits 1 with `--release`, 0 otherwise.
- **NOTE**: reported, never blocking. Credential separation is a NOTE: it is the owner's step list
  (SHIELD §5.7), and no lane can do it. While it is missing or stale, the first line of every output reads
  `not enforced on this machine: credential separation (see SHIELD §5.7)`.
  Without `--identity` the row is read from evidence only. With `--identity` it is the live answer
  (next section), and a `FIX` there blocks like any other.

## The identity check

`teyla shield check <repo> --identity` is the only part of the contract that uses the network. It runs
read-only `gh api` GETs (row 34 of PRIVACY.md) for the login, the repo's `permissions` and default
branch, its rulesets and the default branch's protection, and prints one `credential-separation` row:

- `FIX`: the active identity can push and merge (admin on the repo, or no ruleset or protection it
  cannot bypass guards the default branch). The text ends `see SHIELD §9.4`.
- `OK`: a worker that can push a branch but not merge (a ruleset it cannot bypass restricts updates or
  needs an approval, or branch protection does), or that has no push right on the repo at all (it
  pushes to a fork). The `[[security.evidence]]` row to paste is printed under the summary.
- `NOTE`: it could not tell: `gh` missing or not signed in, no GitHub remote, no access to the repo,
  or safe mode without `--allow-network`.

The repo asked about is the `upstream` remote, else `origin`, or `--github-repo OWNER/NAME`. No token is
ever printed; error text from `gh` is scrubbed of anything shaped like one. Without the flag the command
makes no network call, as before. The checklist for the owner is SHIELD §9.4.

## Evidence

Add a row when you run the proof, with the commit it ran against and the command. Then run the check
again; the age on the line is days since `date`. The default limit is 30 days. A row with `max_age_days`
sets its own limit, and a `release` entry such as `rls-test<14d` lowers it for a `--release` run. When
several rows share a `what`, the newest counts.

## The release step

Run `teyla shield check <repo> --release` before an upload. Fix every FIX, rerun every STALE proof,
then upload. For a family, testers or public product, the review notes carry a `DATA` paragraph; start
from `templates/store/REVIEW-NOTES.md`.

## The table

`teyla shield` lists every repo under `code_root` that has a `[security]` section. Each column is a
requirement (`-` when the tier does not need it), and the last column is the age of the oldest evidence
row. It runs the leak scan of each repo, so it takes as long as those scans do. It exits 1 when any
repo has a FIX.
