# App Store tooling

`app-store.py` writes Teyla's App Store Connect record from files in this repository. One record
(`com.zaitsew.teyla`) holds the iPhone and the Mac version. Python 3 standard library only. The API key,
the token and the HTTP calls come from `~/ops/bin/testflight`; nothing secret is printed.

## Quick start

1. Create the record once in the App Store Connect website (Apps, +, New App). The API cannot.
2. `apps/store/app-store.py push --dry-run` prints every request it would send.
3. `TEYLA_REVIEW_PHONE=... apps/store/app-store.py push`, then `--platform macos push`.
4. Upload screenshots, then submit a processed build:
   `apps/store/app-store.py screenshots DIR` and `apps/store/app-store.py submit --build N`.
5. `apps/store/app-store.py status` shows what the record holds.

## Commands

Add `--platform macos` (default `ios`) to work on the macOS version of the record.

| Command | What it does |
|---|---|
| `status` | Read-only. Version and state, categories, age rating, text and screenshot counts, attached build, review detail, territories, submissions. |
| `push [--dry-run]` | Checks the listing, then writes categories, age rating (every answer None or No), content rights, free price, availability (China mainland off), the version text and the App Review detail. Idempotent: it PATCHes what exists. The macOS push creates the macOS version if the record has none and leaves the app-level answers to the iOS push. |
| `screenshots DIR [--dry-run]` | Uploads `DIR/iphone69/en-US/*.png` (1320x2868) for iOS, or `DIR/mac/en-US/*.png` (2880x1800) for macOS. A set is replaced only when the files differ. Wrong sizes are refused. |
| `submit --build N [--dry-run]` | Attaches the processed build `N` and sends the version to App Review. After a rejection, press "Resubmit to App Review" on the web page. |

## Listing files

`listing/<ios|macos>/en-US/<field>.txt`, one plain text file per field: `name`, `subtitle`, `promotional_text`,
`description`, `keywords`, `whats_new`, `review_notes`, `support_url`, `privacy_url`, and an optional
`marketing_url`. Name, subtitle and privacy URL are app-level: the iOS files are the ones that are sent.

Before any request, `push` and `submit` refuse to run when a file is missing, over its limit (name 30,
subtitle 30, promotional text 170, keywords 100), names a model provider (OpenAI, ChatGPT, Claude, Anthropic,
Gemini, Grok, Codex) in a listing field, still has a `TODO(owner)`, or the review notes lack a section a
reviewer asks for. The tests run the same check.

## Environment

| Variable | Use |
|---|---|
| `TEYLA_REVIEW_PHONE` | The reviewer's phone number. Unset: the number in App Store Connect stays as it is. Never invented, never printed. |
| `TEYLA_REVIEW_FIRST_NAME`, `TEYLA_REVIEW_LAST_NAME`, `TEYLA_REVIEW_EMAIL` | The App Review contact. Unset: the Beta App Review record's value is used. |
| `TEYLA_COPYRIGHT` | The copyright line, for example `2026 Name`. Unset: the field stays as it is. |

China mainland is excluded from the first submission (POLICY section 15); the reason is beside
`EXCLUDED_TERRITORIES` in the script. Re-including it is the owner's call.
