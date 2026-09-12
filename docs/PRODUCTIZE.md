# Productizing: from an app you use to an app four people use

You built something small and it works. You use it every day. Someone watches over your
shoulder and asks for it, and you say yes — and then you discover that the distance
between "works for me" and "works for you" is not a feature. It is six unrelated pieces
of plumbing, none of them interesting, all of them load-bearing, and every one of them
cheaper to have done on day one than to retrofit on the evening somebody is waiting.

This document is the method: why solo-built apps resist sharing, what to build instead
from the first commit, what the shared platform provides once, how to productize an app
that already exists, and what changes when it grows.

Two commands go with it:

```bash
teyla platform      # the shared resources: what is set up, what is missing, the step for each
teyla productize    # per product: who it serves, who it should serve, what is in the way
```

---

## 1. Why solo-built apps resist sharing

Audit four apps built by one person for one person and the same six findings come back.
None of them is a mistake. Each is the locally correct decision, taken by someone with no
second user, and each becomes a wall the moment there is one.

**One shared key instead of accounts.** The backend checks a single bearer token from an
environment variable. Holding the string *is* being you. There is nothing to give a second
person that is not also permission to be the first person, and nothing to revoke that does
not lock everybody out.

**No `user_id` anywhere.** Tables are flat and global: cards, entries, reviews, history.
Two people on one backend share one dataset — one deck, one history, one set of settings.
This is the expensive one, because the fix is a migration, an auth change, and a rewrite of
every query, all at once, on live data you care about.

**The backend runs on the builder's laptop.** A launchd job, a local port, a SQLite file
under the repo. It is reachable from that machine and, if you are lucky, that Wi-Fi. It
sleeps when the lid closes and travels when you do. A second person is not blocked by a
missing feature; they are blocked by your laptop being in a bag.

**No distribution path off that machine.** The app builds and runs in Xcode. The extension
loads unpacked in developer mode. The Android build is an APK you sideload with a cable.
Every one of these is "works on the developer's machine" wearing a different hat, and each
requires the developer's presence to install once and again on every update.

**Your model key on someone else's device.** The app calls a paid API with a key you own,
with no per-user meter and no cap. At one user that is a line item you recognise. At four
it is an unbounded bill attached to behaviour you cannot see, and the honest fix is not
trust — it is a meter.

**No onboarding doc.** The README is a build guide: clone, install toolchain, generate the
project, run. It is written for you. The person you are handing the app to needs to know
what it is for, what to tap first, what it costs them, and where their data lives — and
none of that is anywhere.

Notice what is *not* on this list: features, quality, polish. The apps were fine. Sharing
is a plumbing problem, and plumbing is the part solo work never forces you to do.

---

## 2. Build for N from day one

None of the following slows down a solo build. All of them are days of work later.

**Identity is the platform's, not the app's.** Use the identity provider you set up once
for everything (`[identity]` in the platform manifest). Do not invent a key scheme; a
shared key is not a simpler account system, it is an account system with one account and
no way to add a second.

**Identity: the accounts hub.** The strongest shape identity can take is one Supabase-Auth
project shared by every product — an accounts hub, not a login screen reinvented per app.
One sign-in system, one user table, and one admin panel where the owner sets plans and
per-user budgets across every product at once, with a Swift kit and a TS kit so a new
product wires itself into it in an afternoon instead of building its own. Declare it as
`identity = "accounts-hub"`; R1 treats it as the strongest option — first in the list, on
equal footing with a bespoke `supabase-auth` setup, never a lesser or exotic choice next
to it.

**`user_id` and row-level security from migration 0001.** Even with exactly one row in the
users table. The cost while you are alone is one column and one policy per table. The cost
of adding it later is a migration against data you cannot afford to lose, plus every query
in the codebase, plus an auth change, in one release. Deny by default, so a missing policy
fails closed rather than leaking.

**No backend on a laptop.** Data, accounts and short server-side functions go to the
managed identity/data provider. Work that must keep running — a poller, a queue worker, a
scheduler — goes on the one shared server (`templates/platform/`). Neither costs more than
the laptop did; both are reachable at 3am when your laptop is closed.

**Model calls metered or brought by the user.** Either each person supplies their own key
(zero cost to you, some friction to them) or your key is proxied behind a per-user
allowance that returns a hard error when spent. Both are fine. An unmetered shared key is
not, which is why `cost_cap` is a requirement below and not a suggestion.

**Distribution from week one, before you need it.** Upload a TestFlight build the week the
app first launches, even to a group of one. Make the web app an installable PWA the day
there is a web app. The first upload is the slow one: certificates, a beta review, a
privacy page, an account-deletion path. Do it while nobody is waiting.

**Config out of code.** Every host, key name and identifier in `.env.example` and in
`secrets = [...]`, never hardcoded in a client. A value you can only change by editing
Swift is a value the person running the app cannot change at all.

**An onboarding doc before the first invite.** `docs/GETTING-STARTED.md`, addressed to a
person who is not you: what it is, what they need, the first five minutes, what it costs
them, where their data lives, how to report a problem. `teyla scaffold --kind app` writes
the stub; filling it in takes twenty minutes and is the difference between "here is a
link" and "here, I made you a thing."

**A check that says a second person got in.** In `teyla.toml`:

```toml
[[check]]
name = "a second user completes onboarding"
how = "invite someone who has never seen it, watch them get to the first result"
status = "untested"
```

Until that check is `ok`, the app is not shared. It is shareable, which is a different
word, and `teyla routines` will keep saying so.

---

## 3. The shared platform: set up once, reused by every product

The whole point is that these are bought once. The second product costs a directory and a
DNS record; the seventh costs the same.

| resource | why | rough cost/month | who sets it up | where the value lives |
|---|---|---|---|---|
| Always-on server | processes that must keep running, off your laptop | $6–12 | you (account + token), then a script | `[server]` in the manifest; token in the secrets file |
| Domain + DNS | one name per product, `<product>.<domain>`; certificates issue themselves | ~$1 | you (registrar) | `[domain]`; API token in the secrets file |
| Identity + data | accounts, per-user rows, RLS, server-side functions | $0 → $25 when it must not pause | you (org), agents per project | `[identity]`; access token in the secrets file |
| Mail sender | sign-in codes that reach inboxes other than your own | $0 on a free tier | you (account + domain verify) | `[mail]`; API key in the secrets file |
| Apple API key | TestFlight and the App Store without a password or the GUI | $99/yr | you, once | `[apple]`; the `.p8` at mode 600, never printed |
| Play Console | Android beyond a PWA | $25 once | you, once | `[android]`; keystore backed up — it cannot be regenerated |
| Model provider | one project key per product, budget-capped | usage | you (key), agents wire it | `[llm]`; key in the secrets file |
| Secrets file | one mode-0600 file instead of values scattered across dashboards | — | you (create it) | `[secrets].file` |

The manifest is `~/.teyla/platform.toml`. It holds identifiers and the *names* of
environment variables and never a secret value:

```bash
teyla platform init --owner "Your Name"   # write it from the template
teyla platform env-example                # the secrets skeleton, names only
teyla platform                            # the table
```

```
resource  state    what to do
secrets   ok       ~/.config/teyla/platform.env 0600; 4/5 names present
server    MISSING  provision it: bash .../provision-droplet.sh --yes (needs DIGITALOCEAN_ACCESS_TOKEN),
                   then paste the IP as host = in ~/.teyla/platform.toml
domain    ok       example.com resolves
identity  ok       supabase present, org <id>
mail      MISSING  create the key at https://resend.com/api-keys → paste as RESEND_API_KEY= in
                   ~/.config/teyla/platform.env
apple     ok       3 ids, 1 key(s), ~/ops/bin/testflight
android   MISSING  open a Play Console account ($25 once) → play_console = true
llm       ok       openai, OPENAI_API_KEY set
```

Every missing row names the URL where the thing is created and the file and key where its
value goes. That is deliberate: a to-do that does not say how is a to-do nobody does. The
command exits 1 while anything is missing, so it can gate a weekly routine.

The server itself is five scripts and a runbook in `templates/platform/`: provision a box,
harden it, run one reverse proxy, and add a product by dropping a directory into `/srv`.
Each product ships three fragments in `deploy/droplet/` — a compose service, a site block,
an env example — and `add-product.sh <name> <port>` renders them. Adding the second product
does not touch the first.

---

## 4. Productizing an app that already exists

```bash
teyla productize                 # every repo under code_root
teyla productize ~/repos/thing   # or one
teyla productize --owner-steps   # one numbered list of what only you can do
```

Declare, in the repo's `teyla.toml`, who it serves and who it should serve:

```toml
[productize]
users = "owner"
target = "family"
platforms = ["ios", "web"]
identity = "supabase-auth"
tenancy = "user_id+rls"
backend = "supabase:<ref>"
llm = "proxy-metered"
first_run = "sign-in+skip"
sample_data = "labelled"
onboarding_doc = "docs/GETTING-STARTED.md"
secrets = ["OPENAI_API_KEY"]
cost_cap = "$5 per user against the house key, then bring your own"

[productize.distribution]
web = "pwa"
ios = "testflight-internal"

[[productize.blocker]]
what = "external TestFlight group"
who = "owner"
how = "App Store Connect → TestFlight → add an external group, submit for beta review"
```

Nine requirements are checked against the target:

| id | requirement | fails when |
|---|---|---|
| R1 | identity | `none` or `shared-key` — unless tenancy is `per-device` |
| R2 | tenancy | `single` |
| R3 | backend | `local-mac` |
| R4 | distribution | any declared platform has none, `xcode`, or `apk-sideload` |
| R5 | onboarding_doc | unset, or the file is not in the repo |
| R6 | secrets | a name in `secrets` is in no `.env.example` (no file anywhere: a warning) |
| R7 | cost_cap | empty while your key pays for other people's use |
| R8 | mail | target is `public` and the platform has no mail sender |
| R9 | first_run / sample_data | target is `family` or `public`, and `first_run` is `none` (or unset), or `sample_data` is `unlabelled` (or unset) |

A `public` target raises the bar rather than adding rules: accounts must be real accounts,
iOS/macOS must be external TestFlight or the App Store, Android must be Play, an extension
must be in the store, and sign-in mail must work for strangers. A `family` or `testers`
target is deliberately easier — an internal TestFlight group and a PWA genuinely are enough
for four people, and pretending otherwise is how "share it with my family" becomes a
quarter of work. R9 is narrower than the rest of the table on purpose: it checks `family`
and `public` only, not `testers` — a handful of named people who already know they are
looking at a preview are not the audience the first screen is for.

### The first screen

The owner's rule, set after testing his own apps: every product opens on a sign in / sign
up screen. Where the product is usable without an account, that screen has an explicit
skip (an ×, "continue without an account"); where it is not, there is no skip. After
sign-in comes a short onboarding. Demo or sample data is never shown as if it were the
user's own: it is labelled as an example and can be removed in one tap.

Why: a tester who lands on someone else's sample trip does not know what the app is. The
first screen is the one chance to say, before anything else, whose data this is and how to
get your own — skip it and every screenshot, every walkthrough, every second person who
opens the app has to guess.

Two values carry the rule. `first_run` is `sign-in` (mandatory, no skip), `sign-in+skip`
(the app is genuinely usable without an account, so the screen offers a way past it), or
`none` — which is a legitimate value for a solo tool but never for a `family` or `public`
target. `sample_data` is `none` (nothing canned ships at all), `labelled` (canned content
is marked as an example and clears in one tap), or `unlabelled` — canned content that reads
as the user's own, which is the exact state R9 exists to catch.

```
cellar    owner→family  7/7 met
    [owner] internal TestFlight group — App Store Connect → add two Apple IDs
lang      owner→family  1/7 met  unmet: R1 identity=shared-key, R2 tenancy=single,
                                        R3 backend=local-mac, R4 ios=none,
                                        R5 onboarding_doc unset, R7 cost_cap unset (llm=app-key)
    [agent] no per-user rows — add user_id + RLS, backfill existing rows to the owner
```

Blockers are grouped by who can actually clear them. `--owner-steps` collapses everything —
across products and the platform — into one numbered list, platform first, because one
mail sender unblocks three products and one TestFlight group unblocks one.

### Four case studies, one paragraph each

**A training app** had already done the expensive part: `user_id` and deny-by-default RLS
from the first migration, real accounts, per-user onboarding, and a metered allowance
against the owner's model key. Nothing needed writing. What stood in the way was entirely
operational — two tester emails in a TestFlight group, and a short setup page for a person
who is not the author, because the existing one said "you" and meant one specific person.
This is what building for N from day one buys: productizing is an afternoon of admin
instead of a migration.

**A language app** was the opposite and the most instructive. One shared bearer key, no
users table, no `user_id` on any of six tables, the learner's own name in an environment
variable, a backend on the author's laptop behind no proxy, and an extension that loads
unpacked. Every finding in §1 in one repo. The path out is a migration adding a users table
and a `user_id` column with the existing rows backfilled to the author, auth resolving a
token to a person instead of comparing one string, the per-user name moving from env to the
user row, a host that is not a laptop, and a zipped extension with install instructions.
That is a week, and it would have been an hour spread across the first month.

**A trip app** was multi-client and further along than it looked: capability tokens rather
than accounts, so anyone with a link can already read or edit, and a genuine installable
PWA that covers Android with no store at all. Its wall was not tenancy but delivery — the
built-in mailer sends sign-in codes only to addresses that already belong to the project,
so nobody else can complete a sign-in, and iOS deep links do not verify because the pages
are served from a host that returns the wrong content type for the association file. Both
are owner steps taking minutes: a mail sender, and a domain in front of the pages.

**A cellar app** stores everything on the device and has no accounts by design — which is a
legitimate answer, not a gap, and why `per-device` tenancy exempts a product from the
identity requirement. Two people can each run their own copy today; what they cannot do is
share one dataset, and that is a real feature (sync) rather than plumbing. Its actual
blockers were an internal TestFlight group, a note explaining how to supply a model key,
and a getting-started page. Distinguishing "this app does not need accounts" from "this app
forgot accounts" is exactly the judgement the exemption encodes.

---

## 5. Scaling later, and not before

Stay on one server until per-product metering says otherwise. The cost of a second box is
not the money, it is that everything which was one thing is now two: two sets of upgrades,
two firewalls, two places a certificate can expire. Split when one product's resource use
is actually crowding another, and use the metering to prove it rather than the feeling.

What changes around twenty users, roughly in the order it bites:

- **Mail becomes mandatory.** Built-in mailers cap at a few messages an hour and deliver
  only to addresses that belong to the project. This is the first thing that breaks and the
  cheapest to fix.
- **The data plan stops being free.** Paid tiers exist mostly so the project does not pause
  when idle and so backups are daily. Pay it before you need the backup, not after.
- **Error tracking becomes real.** With one user, the bug report is you remembering. With
  twenty it is silence. Self-host on the shared box or use a free SaaS tier; either beats
  finding out by accident.
- **Distribution outgrows internal testing.** External TestFlight is a one-time beta review;
  Play needs a console account and, for a personal one, a fourteen-day closed test before
  production. Both have waiting periods, which is the argument for starting them early.
- **Model cost stops being a rounding error.** Per-user allowances that were theatre at four
  users are the actual control at twenty. If they were never built, this is when you build
  them, under pressure.
- **Support becomes a routine.** Add it to `teyla.toml` as a check with a cadence, so
  "nobody has reported a bug" is distinguishable from "nobody could find where to report."

The one rule that does not change: a product with no second user has no scaling problem.
Get one person in first. Everything above is the answer to a question you will not have
until then.
