# teyla you

What your own sessions say about you, and which manual chores an AI could take over. Everything is computed
from files already on your machine and stays there.

```
teyla you [--json] [--refresh]
teyla you chore KEY open|done|tried|untried
```

The result is cached in `~/.teyla/you.json` (mode 0600) for the day. `teyla console` shows it in the Playbook
section. It reaches the phone only when `[you] relay = true`, and then only as the quote of the day and the number
of open chores. Nothing in this command is sent anywhere, except the optional ranking below (PRIVACY row 38).

## What it shows

**Quote of the day.** A verbatim line of 30 to 140 characters from your long prompts (`teyla intent`) or your
corrections. The pick is by rules: lines with decision verbs (want, never, stop, ship, fix) and a length of 50 to
110 characters score higher, questions score lower. Ties break on a hash of the text, and the quote is stable
within a day.

A line is dropped when:

- a machine wrote it: a delegated task, a pasted app request, a cross-session message, anything starting with `<`;
- the private-terms list or the leak rules match it (names, e-mails, home paths, secrets);
- it holds a link, code, a path, a phone number of nine digits or more, or a street address;
- it touches money or personal documents (passport, tax, salary, bank, contract, medical, and so on).

When no private-terms list is loaded, the quotes are still produced and the output says that names are not
screened out. Quote text is never written into a repository.

`[you] rank = true` lets Claude Haiku order the screened candidates once a day. The model sees only lines that
already passed the screen, and its reply must be a list of valid numbers or it is dropped. Off by default; closed
in safe mode. Only `teyla you` runs it: the console's Playbook section reads the cache or rebuilds by rules, and never asks a model.

**Insights.** Counts with their evidence: long prompts per week, median prompt length, share of prompts typed at
night (22:00 to 06:00), language split, products ranked by prompts, themes that recur across prompts. `teyla
intent` keeps only prompts of 400 characters or more, so every figure says what it does not see.

**Repeats after a rule.** The headline of the Playbook, "Unresolved contradictions". For each rule file with a
creation date (its `created:` field, else the date git first saw the file), it counts corrections that match the
rule's words and are newer than the rule. A rule counts when at least two corrections follow it. This is a count of
repeats after a rule. Two rules that contradict each other are not detected: comparing the text of two rules
cannot be done reliably, so the label says so.

**Postcard.** An old line of yours (at least 21 days old) about a product, next to what git shows for that
repository since: commits and tags. One per ISO week. Skipped when git cannot confirm anything.

**Delegation.** The chores found in your asks and corrections, by one rule-based classifier (`chores.py`, the same
one `teyla asks` uses to fold repeats). Each row has the count, the last date, the products, the honest hand-off
path, who must still act, a status (`open` or `done`, set by you), and "not verified on this machine" until you
mark the path tried.

| Chore | What can be handed off | What stays human |
|---|---|---|
| developer.apple.com | A role-based App Store Connect API key covers identifiers, certificates and profiles. | A separate technical account cannot replace the Account Holder. Scraping the portal is banned by Apple's terms. 2FA stays human. |
| App Store Connect | The same key covers uploads, builds, metadata and review status through `testflight`. | Agreements and banking stay with the Account Holder. |
| Play Console | A service account with the Google Play Developer API covers uploads and release status. | Policy forms and the first setup are web-only. |
| DNS record | A Cloudflare API token scoped to one zone (DNS edit). | Registrar changes. |
| gcloud sign-in | A service account for the one project. | Creating it, once. |
| Chrome sign-in | A dedicated automation profile, signed in once. | Passwords and 2FA codes: an agent never types them. |
| API keys and secrets | One secret store: you paste each secret once, an agent reads it by name. | Pasting the secret. |
| View in TestFlight | Nothing. Apple shows a new tester nothing until they tap the invitation e-mail. | The tap, once per app. |

`teyla you chore app_store_connect tried` records that the path worked on this machine, with the date. `open` and
`done` set the status. The keys are listed in `src/teyla/chores.py`.

## Files

| File | Holds |
|---|---|
| `~/.teyla/you.json` | The last result, mode 0600. Delete it to rebuild. |
| `~/.teyla/you-chores.json` | Your marks per chore: status and the date a path was tried. |
