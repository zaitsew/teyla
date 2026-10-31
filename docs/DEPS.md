# Dependency check

Status: shipped 2026-10-31. Lane G of the Shield sprint (decision SH10). `teyla deps` reads the lockfiles of a
repo and asks the free OSV API which of the pinned versions have a known vulnerability. It matches the installed
version, not the package name, so a fixed release is never reported.

```
teyla deps                    # the repo in the current directory
teyla deps myrepo             # a repo under code_root, or a path
teyla deps --all              # every repo under code_root, a summary table, the worst exit code
teyla deps --dry              # what would be sent (counts); sends and writes nothing
teyla deps --json --no-cache  # machine-readable; ask OSV again
```

## Lockfiles it reads

| File | Ecosystem | Note |
|---|---|---|
| `package-lock.json`, `npm-shrinkwrap.json` | npm | v1 `dependencies` and v2/v3 `packages` |
| `pnpm-lock.yaml` | npm | the `packages:` keys of lockfile v5 to v9 |
| `yarn.lock` | npm | classic and Berry |
| `deno.lock` | npm | `jsr` packages are skipped: OSV has no JSR ecosystem |
| `Package.resolved` | SwiftURL | HTTPS pins with a version; branch and revision pins are skipped |
| `uv.lock`, `poetry.lock` | PyPI | registry packages only |
| `requirements*.txt` | PyPI | `==` pins only; the unpinned count is a note |
| `Gemfile.lock` | RubyGems | the `GEM` section |
| `go.sum` | Go | module and version, `/go.mod` lines ignored |

Directories named `node_modules`, `Pods`, `vendor`, `build` and the like, and hidden directories, are not
entered. The search goes five levels down.

## What it reports

One line per vulnerable package version: severity, the OSV id (with the CVE when there is one), and the fixed
version. A package with several flaws shows the worst one and `(+N more)`. Records of one flaw under several ids
(GHSA, PYSEC, CVE) count once.

```
acme-app: 412 package(s) checked in 2 lockfile(s), 2 vulnerable, 1 FIX
  FIX critical left-pad 1.3.0  GHSA-aaaa-bbbb-cccc / CVE-2026-0001  fixed in 1.3.1
             bump left-pad to 1.3.1 in package-lock.json
      low      acme-utils 2.0.0  GHSA-dddd-eeee-ffff  no fix known
```

Severity is the CVSS v3 base score computed from the vector (9.0 and up critical, 7.0 and up high, 4.0 and up
medium, below that low). A record with no v3 vector falls back to its `database_specific.severity`. No severity
at all is `unknown`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | nothing found that needs action |
| 1 | a HIGH or CRITICAL has a fixed version (a FIX). Lower severities and unfixed flaws are listed and never block |
| 2 | a manifest with no lockfile (`package.json`, `pyproject.toml`, `Package.swift`, `Gemfile`, `go.mod`), or OSV could not be reached, or safe mode refused the call, or OSV did not answer for some packages ("not covered", also with `--quiet`) |

`--all` returns the highest code of any repo. A manifest with no dependencies is not a gap. In `--quiet` mode only
FIX lines and gaps are printed, and a safe-mode refusal prints nothing and exits 0 (the weekly routine never
passes `--allow-network`).

## What is sent, and the cache

Package names, ecosystems and versions go to `api.osv.dev`: a `POST /v1/querybatch` with at most 1000 queries
(follow-up pages are fetched, at most 10; a rejected batch is split in halves to isolate the bad query),
then a `GET /v1/vulns/<id>` for each id not already cached. Never a path, a repo name or a lockfile name
(a SwiftPM URL is cut to `host/path`: userinfo, query and fragment are dropped, and a lockfile that carries userinfo gets a "credential in lockfile" note without the value)
([PRIVACY](PRIVACY.md) row 32). Safe mode refuses the call without `--allow-network`, and `--dry` sends nothing.

Answers are cached for 24 hours in `~/.teyla/deps/cache.json` (mode 0600), per package version and per
vulnerability id. `--no-cache` ignores the cache and writes a fresh one.

## The weekly routine

The Friday weekly wrapper runs `teyla deps --all --quiet` and files the output as `deps.md`. The run writes
`~/.teyla/deps/summary.json`; while it holds a FIX, the digest carries one line with the count for 14 days.

## Limits

- OSV lags the advisories: a flaw published an hour ago may not be there yet. A clean result is not a proof.
- Only the pinned versions in a lockfile are checked. A transitive package that no lockfile pins is not seen.
- SwiftPM coverage in OSV is thin, and only packages hosted at an HTTPS URL are asked. Many Swift packages return nothing.
- It does not know whether the vulnerable code path is reachable. A FIX is "a fixed version exists", not "you are exploitable".
- Version order is tolerant, not exact: unusual version schemes can pick a different fixed version than the advisory names.
- `bun.lock`, `pdm.lock`, `Pipfile.lock` and `Cargo.lock` are not read.
