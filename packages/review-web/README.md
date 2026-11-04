# @teyla/review-web

Feedback capture for a web product's test builds. A tester opens review mode, points at the element that is wrong, writes what is wrong, and the page sends one capture to the shared review channel. It is the web twin of `packages/review-ios`; the format is `capture.json` v1 ([docs/REVIEW.md](../../docs/REVIEW.md)), the same fields as iOS, with `app.configuration` set to `test_host`.

## Quick start

1. Vendor it: from the product's repo root, `~/repos/teyla/packages/review-web/scripts/teyla-review-sync-web`, then `npm install --save-exact modern-screenshot@4.7.0` (the script prints the line).
2. Ask the owner for a channel key for the product: `teyla review channel key add <product>`. Put `VITE_TEYLA_REVIEW=1`, `VITE_TEYLA_REVIEW_URL=https://review.fabriquefutur.com` and `VITE_TEYLA_REVIEW_KEY=<key>` in the env of the test build only (a CI secret or `.env.test`, never a committed file).
3. In the app's entry file call `init` once: `import { init } from "./vendor/teyla-review-web/index.ts"; void init({ product: "my-app", hosts: ["test.my-app.example"], version, build })`.
4. Optional: put `data-review-anchor="screen.element"` on elements worth pointing at, `data-review-screen="screen"` on each screen's root, and `data-review-private` on anything that shows another person's data.
5. Optional: call `present()` from a settings row (and pass `button: false` to hide the floating button). Then run `teyla review store-check <dist>` on the production build: it must exit 0.

Works the same in React, Vue, Svelte or a plain HTML page built with Vite: `init` is a plain function and the overlay is a Shadow DOM element that owns its own markup, so no framework is needed. The product's tsconfig keeps `allowImportingTsExtensions` and the `vite/client` types.

## Three locks, all required

| Lock | What it does |
|---|---|
| Build flag | `import.meta.env.VITE_TEYLA_REVIEW === "1"` guards a dynamic `import("./overlay.ts")`. Vite replaces the value at build time and Rollup drops the dead branch, so a build without the flag has no overlay chunk, no `modern-screenshot`, no marker `TEYLA_REVIEW_WEB_ACTIVE` and no channel key. |
| Host allow-list | `hosts` lists the hostnames that may run review mode: an exact name or `*.base.example` (at least two labels after the star). Anything else, including a bare `*`, a scheme, a port or a path, is rejected and the overlay stays off. A test build copied to another host stays dark. |
| Dynamic import | The marker and the key live only in the lazily imported chunk, so `teyla review store-check <dist>` finds nothing in a flag-off dist. `tests/test_review_web.py` (repo root) builds a fixture both ways with Vite and checks it: flag off, no marker, no key, no URL; flag on, the marker and the key are in the lazy chunk only. |

Another bundler: replace `import.meta.env.VITE_TEYLA_REVIEW` and the two channel variables at build time (esbuild: `--define:import.meta.env.VITE_TEYLA_REVIEW='"1"'`). That route is not tested here. A value passed to `init` at run time cannot remove the overlay code from the bundle, so the build flag is the only switch.

## Entry points

- `init(options)`: starts review mode when the three locks agree. Returns a handle, or `null` when review is off. Never throws.
- `present()`: opens review mode from a settings row. Does nothing when review is off.
- `setScreen(id)`: names the current screen when markup cannot (the twin of `.reviewScreen`).
- Options: `product` (slug; the key is bound to it), `hosts`, `name`, `version`, `build`, `commit`, `language` (`en`, `ru`, `es`), `strings` (overrides), `requiresHealthConsent`, `speech`, `button`, `channel` (`{url, key}` instead of the env variables).

## What a capture holds

`capture.png` is the page as it was, rendered with `modern-screenshot` 4.7.0. If that fails or returns a blank image, the package asks the browser to share the current tab (`getDisplayMedia`) and uses one frame of it; the tester sees the browser's own permission prompt. A blank image is detected before anything is sent (`BLANK_LIMIT` 0.995 of pixels empty, as on iOS).

`capture.json` carries the fields of the iOS capture: `app` (bundle id is the page's hostname, name, version, build, commit, `product`, `configuration` `test_host`), `environment` (browser, OS, locale, appearance, window size), `screen`, `tap` or `region`, `element` and `anchors` (from the `data-review-*` attributes, bounds in viewport CSS pixels), `comment`, `screenshot` (size, scale, sha256) and `microphone` (`false`).

## Privacy

The picture shows the page as the tester saw it, so it can show another person's data. Anything marked `data-review-private` is painted black in the PNG before the form shows it, and before it is hashed, saved or sent; every `input[type=password]`, card field (`autocomplete="cc-*"`) and one-time-code field is masked without a mark. A tap or area that touches a masked region records no `element`, and an anchor that overlaps one loses its `strings`. Nothing leaves the browser until the tester has accepted a first-send notice that says what is sent, who receives it and how long it is kept. The comment is never logged. The package sends no audio: dictation is off by default; with `speech: true` and a browser that has the Web Speech API, the Dictate button fills the comment field with text. Some browsers (Chrome) send that audio to their own vendor's servers for recognition, which is why `speech` is off by default: turn it on only for testers who know that. There is no analytics, no tracking and no third-party code except `modern-screenshot`, which runs in the page and makes no network call. The only network call the package makes is the PUT to the channel (picture, then JSON, `Authorization: Bearer <key>`, no cookies, no referrer).

The channel key is a secret of a test build. It is bound to the product, can only add captures and cannot read, list or delete. Treat it like any build-time secret, and keep the test build behind the host allow-list.

## When it cannot send

A capture that cannot be sent (offline, 429, 5xx) waits in IndexedDB (at most 20 captures and 40 MiB, kept up to 14 days) and goes again when the page starts, when the browser reports `online` and when the tab becomes visible. A capture is deleted from the queue only after the channel answers 200 for both files. 400, 401, 403, 413 and 422 are final for that capture and it is not offered again. If IndexedDB cannot be written (a private window, a full disk) the form stays on screen with a Retry button, so the text the tester wrote is not lost.

## Layout and checks

```
src/        the package (index.ts is the only file a flag-off build keeps)
fixture/    a tiny Vite app that the tests build both ways
tests/      node:test unit tests (gate, masking, capture fields, queue, channel, picture, form, overlay)
scripts/    build-fixture.ts, emit-sample-capture.ts, teyla-review-sync-web
```

`cd packages/review-web && npm ci && npm run check` runs the type check and the 70-odd unit tests; `./check.sh` at the repo root does the same and then runs `tests/test_review_web.py`, which builds the fixture with Vite and runs the store check on it.
