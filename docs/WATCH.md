# Watch

`teyla watch` records App Store changes each week. It creates no playbook cards and changes no repository.

## Quick start

```sh
mkdir -p docs
cp /path/to/teyla/templates/playbook/watch.example.toml docs/watch.toml
# Edit the product name, storefronts and watch rows.
teyla watch --repo example --dry
teyla watch --repo example
```

Without `--repo`, Watch reads `docs/watch.toml` in every repository under Teyla's `code_root`.
Repeat `--repo NAME` to select repositories. Names are directory names under `code_root`.
A missing selected file or invalid list stops the command before any request.
Each product allows 12 rows: at most eight `job` rows and four `craft` rows. `platform` rows also count toward 12.
Rows without `app_store_id` make no request. The `url` field is for teardown lanes only.

`--frontier` adds `<playbook_root>/watch/frontier.toml`. It has at most eight rows, each with `ring = "frontier"`.
It has no `[product]` table and uses the US storefront.
`playbook_root` comes from Teyla config and defaults to `~/ops/playbook`.
`TEYLA_PLAYBOOK_ROOT` overrides it.

## What it records

Apple Lookup supplies version, release notes, description, screenshots, price and release date.
The first run records a baseline. Later runs compare it with the last successful response for each app and storefront.
Changes include version, notes, description, screenshot count and order, and price or currency.
A description diff has at most 20 lines. Identical changes across storefronts appear once, with those storefronts named.

Review RSS supplies up to three quotes per app per ISO week, shared across storefronts and repeated runs.
Quotes have at least 12 words. Watch prefers two to four stars and different ratings.
They are observations to read, never instructions or automatic recommendations.

Output lives under `~/.teyla/watch/` (`TEYLA_HOME` relocates Teyla state):

- `state/<app_id>-<cc>.json`: the last successful Lookup response fields.
- `<week>.md`: at most 30 lines per product; “No relevant change” is valid.
- `<week>.json`: full weekly observations, including changes omitted from the short Markdown report.
- `log.jsonl`: one appended record per completed run.

A repeated run preserves earlier changes and quotes for that week. A failed request leaves its previous baseline intact.
Failures appear in the report and return exit code 1. An empty watch list returns 0.
`--json` prints structured output. `--week YYYY-Www` labels the current observations; Apple supplies no historical snapshot.

## What leaves the Mac

Only Apple requests leave the Mac: one Lookup request and one public review RSS request per app and storefront.
Apple receives the app id, country code, IP address and `teyla-watch/<version>` user agent.
No session, repository content, watch-list reason or personal data is sent.
No listing page, screenshot, `url` field, model or paid source is fetched.
Requests use HTTPS, a 15-second timeout and a 4 MB response cap.
Redirects must stay on Apple's Lookup or customer-review endpoints.

`--dry` lists requests and fetches or writes nothing. Safe mode blocks requests unless you pass `--allow-network` by hand.
The weekly routine calls Watch for product lists beside the design scout. Frontier remains an explicit `--frontier` run. Installing or changing that routine still uses `teyla routine install`.
