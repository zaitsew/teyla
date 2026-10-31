# Outbound hosts

Status: shipped 2026-10-31. `teyla hosts` lists every host a repo's code can reach, by file and line, and
compares the list with the repo's privacy table. It is the static half of the outbound inventory (decision
SH9 in [SHIELD.md](SHIELD.md)). It reads files and prints; it makes no network call and runs no repo code.

```
teyla hosts                       # the repo you are in
teyla hosts myrepo --json         # a repo under code_root, as JSON
teyla hosts --all --quiet         # every repo; only FIX and coverage-gap lines
teyla hosts . --write             # append a row per undocumented host to docs/PRIVACY.md
```

Exit 0 is clean, 1 is any FIX, 2 is a coverage gap (the repo has no `docs/PRIVACY.md` and no
`[privacy] hosts`; the hosts found are listed anyway).

## What is read

| Where | What is extracted |
|---|---|
| Swift, TypeScript / JavaScript, Kotlin | `http(s)://` and `ws(s)://` hosts in string literals; comments are skipped. Also `.host = "x"`, `hostname: "x"`, `.host("x")` |
| Python | the same, from string constants and f-strings; docstrings and comments are skipped. Also `HTTPSConnection("x")` |
| `Info.plist` | `NSExceptionDomains` keys, `NSAllowsArbitraryLoads`, and any URL value (an update feed, for example) |
| `next.config.*` | `images.domains` and `remotePatterns[].hostname` (`**.x.com` reads as `*.x.com`) |
| `supabase/config.toml`, `vercel.json` | every URL value |
| `deno.json`, `import_map.json` | every URL value (remote imports) |
| Android `network_security_config.xml` | `<domain>` entries and `cleartextTrafficPermitted="true"` |
| `.env.example` | values that are URLs (listed as env-provided) |

A name the code reads from the environment (`process.env.X_URL`, `Deno.env.get("X_URL")`,
`os.environ["X_URL"]`, `System.getenv`) is listed as env-provided. Its value is outside the repo, so it has no verdict.

## What is skipped

`node_modules`, `.build`, `Pods`, `dist`, `build`, `.venv`, hidden directories, lockfiles, minified and binary
files, files over 1 MB, symlinks, and tests (`tests/`, `__tests__/`, `fixtures/`, `*Tests/`, `*.test.*`,
`test_*.py`). The coverage line names the skipped roots, so a reader sees what was not looked at.

Some hosts are never listed as findings:

- Placeholders: `example.com`, `example.org`, `example.net` and their subdomains, `example.test`, `localhost`,
  `*.local`, `*.localhost`, `*.invalid`.
- XML namespaces such as `www.w3.org`.
- Loopback, private-range, link-local and `*.internal` hosts. These are listed under `local`, never a FIX.

## The privacy table

`docs/PRIVACY.md` holds markdown tables with a `Host` column (a `Where` column also works). Teyla's own
[PRIVACY.md](PRIVACY.md) is the model, and `templates/repo/docs/PRIVACY.md` is the template that
`teyla scaffold` writes. A row covers a host that is in its Host cell, exactly or by a wildcard suffix
(`*.supabase.co` covers `abc.supabase.co`). `[privacy] hosts = ["api.acme.test", "*.cdn.acme.test"]` in
`teyla.toml` is an alternative, or an addition, to the table.

## Verdicts

| Verdict | Meaning |
|---|---|
| FIX `undocumented` | A host no row and no `[privacy] hosts` entry covers. Fix: add a row (what is sent, when, how to turn it off) |
| FIX `consent` | A model or speech provider host whose Consent cell is empty, in a table that has a Consent column. Skipped when `[security] data = []` |
| WARN `stale` | A documented host that no code reaches |
| WARN `todo` | A row that still says `TODO (a person fills this)` |
| WARN `cleartext` | An `http://` URL to a non-local host, an ATS arbitrary-loads setting, or an Android cleartext exception |

A row that is true but invisible to a scan (a tool or an SDK reaches the host) says `(not in code ...)` in
the row, and is never stale. A row whose Host cell holds a token that is not a host (`mascot.model`) is not
reported as stale either.

`--write` appends a row per undocumented host to the first table with a Host column, creating the file from
the template when it is missing. It writes `TODO (a person fills this)` for what is sent and never deletes or
edits a row.

## Limits

- A URL built at run time (`"https://" + host`, `` `https://${x}/` ``) is missed. The coverage line counts them as "computed".
- A host held in a data file, a server-side setting or a dashboard is not in the repo. `.env.example` helps only if it has a URL.
- HTML, CSS and templates are not read, so a third-party script tag or font link is not found.
- A grep is documentation, not control. `teyla hosts` shows that the table matches the code today. It does not stop a call.
- Runtime control comes later: a `fetch` wrapper and a debug `URLSession` check that refuse a host the table does not name (SHIELD.md section 5.4).

`./check.sh` from `teyla scaffold` runs `teyla hosts . --quiet` before it sources `.env`, so static inspection
never executes repository-controlled configuration.
