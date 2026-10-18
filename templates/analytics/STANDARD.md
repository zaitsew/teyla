# Analytics standard

One standard for every product: what to measure, with which tool, and when to add the next
tool. The short version: count from the data the product already stores; add an SDK only when
a question cannot be answered without one.

## Why this order

- Most products start with one user, the owner. An analytics SDK there measures one person,
  costs a privacy-policy and store-label change, and answers nothing that the product's own
  data does not.
- Each third-party SDK is one more data processor in the privacy policy, one more line in the
  App Privacy label and the Play Data safety form, and one more thing to keep up to date.
- The product's own store already holds the real counters: rows, trips, sessions, metered AI
  calls. `./check.sh usage` prints them, and `teyla products` puts every product in one table.

## The ladder — the `users` key decides the tier

`teyla.toml` `[productize] users` is the trigger (`owner | family | testers | public`). Move
up one tier when `users` changes. Never skip a tier.

| tier | `users` | measure with | crashes | add nothing else |
|---|---|---|---|---|
| 0 | `owner` | `./check.sh usage` from the product's own store | the platform's built-in reports | no SDK, no web tag |
| 1 | `family`, `testers` | tier 0, plus per-person counts (weekly active, retained after 7 days) from the backend | built-in reports; the own diagnostics pipeline when a tester's crash needs detail | no SDK |
| 2 | `public` | tier 1, plus the store's analytics (App Store Connect, Play Console) and one web analytics tool on public pages | built-in reports, plus Sentry (EU) for web and backend | a product-analytics SDK only with an open question (below) |
| 3 | paid plan live | tier 2, plus revenue from the billing source (Stripe, StoreKit) | as tier 2 | RevenueCat only when two or more apps sell StoreKit subscriptions |

**An open question** is a written funnel question that the product's own data cannot answer.
Examples: "where do new users drop out of onboarding?", "does landing variant B convert
better?". Write it in `docs/ANALYTICS.md` with the decision it feeds. The SDK comes out again
when the question is closed and nothing else needs it.

## The tools — one per job

| job | tool | why this one | cost |
|---|---|---|---|
| own counters | `./check.sh usage` → `teyla products` | no vendor, no data leaves | free |
| app store funnel and crashes (Apple) | App Store Connect Analytics, Xcode Organizer | built in; only users who share diagnostics | free |
| app store funnel and crashes (Android) | Play Console statistics and Android vitals | built in | free |
| crash detail from testers | the product's own MetricKit / ApplicationExitInfo pipeline into its backend (a `client-diagnostics` function and table) | data stays in our Supabase; opt-out in Settings | free |
| errors, web and backend | Sentry, EU region, chosen at organization creation | one tool for web, Deno, Node, Python | free to 5K errors a month, 1 seat; Team $29/month |
| web pages (marketing, landing) | Vercel Web Analytics on Vercel; Cloudflare Web Analytics elsewhere | cookieless, no banner | Vercel Hobby free to 50K events a month; Cloudflare free |
| product analytics (tier 2 with an open question) | PostHog Cloud EU (Frankfurt) | iOS, Android, web, Python and Node SDKs; funnels, flags, experiments; an API for the weekly readout | free to 1M events a month; then per event. Set the billing limit to $0 |
| AI usage and cost across products | the shared accounts / metering service's usage table, when there is one | already logs every metered call by product, task and model | free |

**Never:** IDFA, App Tracking Transparency prompts, advertising SDKs, Firebase Analytics,
Google Analytics in apps, session replay or heatmaps (Clarity, PostHog recordings) in a product
that shows personal data. A second product-analytics vendor next to PostHog needs an eval that
shows PostHog cannot do the job.

## Rules for events, when there is an SDK

1. **Allowlist, not autocapture.** Autocapture, automatic page views and session recording are
   off. Every event name and every property key is listed in one schema file in the repo, and
   the client drops what is not on it (a `PROP_ALLOWLIST` set checked before every send).
2. **No content.** Properties are enums, counts, durations, booleans and ids. Never free text:
   no trip names, notes, messages, prompts, AI output, places, people's names, URLs with tokens.
3. **Anonymous by default.** The distinct id is a random install id, or the account id when
   the person is signed in. Never an email or a phone number. Deleting the account deletes the
   person in PostHog too (a call in the account-deletion path).
4. **Cookieless on the web.** `persistence: "memory"` (or PostHog's cookieless mode) and a
   first-party `/ingest` proxy, so no consent banner is needed. Adding a cookie needs a banner
   first.
5. **One taxonomy.** `object_verb`, snake_case, past tense. The core funnel is the same in every
   product:

   | event | when |
   |---|---|
   | `app_opened` | first foreground of a session |
   | `signed_up` | an account is created |
   | `onboarding_completed` | the last onboarding step is done |
   | `activated` | the product's core action for the first time (the product defines it in `docs/ANALYTICS.md`) |
   | `core_action` | each time the core action happens, with `kind` as an enum |
   | `paywall_viewed`, `purchase_completed` | tier 3 only |
   | `shared` | a share link or invite is sent |

   Landing tests keep the analyst skill's web funnel: `page_view`, `cta_view`, `cta_click`,
   `form_start`, `form_submit`. Product-specific events add a prefix: `trip_created`, not
   `created`.
6. **Standard properties:** `product`, `platform` (`ios | macos | android | web`),
   `app_version`, `tier`. Nothing else is sent on every event.

## The paperwork moves with the code

The PR that adds a tool also changes, in the same PR:

- the privacy policy: the processor's name, its region, what is sent, the retention period;
- `PrivacyInfo.xcprivacy` and the App Privacy answers (Product Interaction / Crash Data,
  "not linked to identity" when anonymous, "not used for tracking");
- the Play Data safety form;
- `docs/ANALYTICS.md`: the tier, the tools, the open questions, the event list;
- `.env.example`: the key names (`POSTHOG_KEY`, `POSTHOG_HOST`, `SENTRY_DSN`), dark by
  default, so a fork or a CI run sends nothing.

A product whose policy says "no analytics" keeps that sentence true. Adding an SDK there is a
product decision for the owner, not a technical one.

## The weekly readout

`teyla products` runs every `./check.sh usage` and prints one table. Each probe prints
`key=value` lines and nothing else:

- tier 0: counts of the core objects and `last_write_days_ago`;
- tier 1 and up: `wau=` (people active in the last 7 days), `new_7d=`, `retained_7d=`
  (active this week and the week before);
- tier 2 and up: one line per open question, from PostHog's API (`onboarding_completion=0.42`);
- AI products: `ai_calls_7d=` and `ai_cost_eur_7d=` from the metering table.

A probe that needs a secret reads it from the Keychain or `~/.config/<product>/`, never from
the repo, and prints `probe=needs_key` when the secret is missing. Zero is a finding, not an
error.
