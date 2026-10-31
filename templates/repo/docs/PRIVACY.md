# Privacy: every call that leaves your machine

{{name}} makes the calls in the tables below and no others. Each row names the trigger, the host,
what is sent, whether it runs without the user asking, and how to turn it off. "Default on" means it
runs with a stock install and no flag.

Replace the three example rows with the real ones. The example hosts (`example.com`, `example.org`,
`example.net`) are placeholders that `teyla hosts` ignores.

## Calls this product makes

| # | Trigger | Host | What is sent | Default on | Turn it off |
|---|---|---|---|---|---|
| 1 | Example: the app checks for a new version at launch | `example.com` | Example: the app version and the OS version. No user data. | Yes | Example: the "Check for updates" setting |
| 2 | Example: the user opens a shared item | `example.org` | Example: the item id from the link the user tapped. | No (needs a tap) | Example: do not open shared links |
| 3 | Example: crash reports, only after the user agrees | `example.net` | Example: the stack trace and the app version. No text the user wrote. | No (opt-in) | Example: "Send crash reports" in settings |

## Calls that carry user content to a model provider

Add a row here for every provider (a model, speech or image API). The Consent column says what the user
agrees to, and where in the app they agree. An empty Consent cell on a provider row is a FIX.

| # | Trigger | Host | What is sent | Default on | Consent | Turn it off |
|---|---|---|---|---|---|---|

## How to keep this true

Run `teyla hosts .` in this repo. It lists every host the code can reach, by file and line, and compares
the list with this file and with `[privacy] hosts` in `teyla.toml`:

- A host that no row covers is a FIX. Add a row: what is sent, when, and how to turn it off.
  `teyla hosts . --write` appends the rows for you, with "what is sent" left as TODO for a person.
- A row that no code reaches is a WARN (a stale row). Delete it, or say in the row why the scan cannot see it.
- A host built at run time (a URL assembled from variables) is not found. Document it by hand.

`./check.sh` runs `teyla hosts . --quiet` before anything else, so a new host fails the first-run check
until it has a row. A row may use a wildcard suffix in the Host column, such as `*.example.com`.
