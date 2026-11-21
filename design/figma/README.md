# Teyla in Figma, from specs

The Figma file "Teyla — Surfaces (0.58)" is a snapshot of the code: nobody edits it by hand. Every surface is one
JSON spec in `screens/<area>/<id>.json`, drawn with the composites in `components/`. The renderer is not in this
repo: it is a spec-to-Figma generator kept in a sibling app repo (`Design/figma/bin/figma` there), which takes this
folder with `--product`. Previews need only node and Chrome.

## Quick start

```
export FIGMA_BIN=<the generator checkout>/Design/figma/bin/figma
$FIGMA_BIN check --strict --product design/figma                  # specs parse, tokens and SF Symbols exist, lint clean
$FIGMA_BIN preview design/figma/screens --png --product design/figma
open design/figma/build/preview/mac.today.png
$FIGMA_BIN cover --preview --product design/figma                  # page 1: cover and foundations, as HTML
```

To draw: open the Figma file, run the generator's bridge plugin in it and its bridge server (with
`BRIDGE_FILES=<this repo>` so the captures load), then `setup`, `render --all`, `cover`, `captures` and `wire`, each
with `--product design/figma`. `build/` is gitignored.

## The folder

| File | What it holds |
|---|---|
| `product.json` | name, file name, the prototype's start (`iphone.home`), page names, captures (`docs/img`), where the version is |
| `tokens.mjs` | the tokens, read from `brand/tokens.json` (the one source): light values for the variables, `dark` for the cover's second column; tints, iOS system colours, Mac window chrome and the CLI's ANSI roles beside them |
| `areas.json` | the five sections of page 2: `mac`, `iphone`, `review-form`, `web`, `cli` |
| `components/core.mjs` | the shared chrome (below) |
| `cover.mjs` | page 1 (cover, foundations: every colour light and dark, ANSI roles, type, space, radius, mark) and page 3 |
| `dsl.mjs` | `V`, `H`, `Z`, `T`, `I`, `U`: short constructors for composites |

All content is made up: products are "Atlas", "Pebble" and "Quill", counts are invented. No real repo, person or path.

## A spec

```json
{ "id": "mac.today", "title": "Today", "area": "mac", "presentation": "tab",
  "device": { "w": 1280, "h": 800 },
  "source": ["apps/mac/Teyla/UI/TodayView.swift:12"],
  "root": { "t": "use", "c": "macWindow", "p": { "selected": "today", "kids": [ ... ] } } }
```

`id` is `<area>.<surface>`; links point at ids. `device` sets the frame (default 402 x 874, the iPhone). Colours and
text styles are token names from `tokens.mjs`: colours `background`, `surface`, `border`, `text`, `text-secondary`,
`primary`, `needs-you`, `saving`, `danger`, ... (`"primary@0.14"` for a tint); text styles `mac-page-title`,
`mac-section`, `mac-card-title`, `mac-body`, `mac-caption`, `mac-number`, `mac-code` on the Mac (Typo in
`apps/mac/Teyla/UI/Tokens.swift`), `ios-large-title`, `ios-page-title`, `ios-section`, `ios-card-title`, `ios-text`,
`ios-body`, `ios-caption`, `ios-number`, `ios-code`, `ios-tab` on the iPhone, `term` in a terminal, `web-title`,
`web-head`, `web-body`, `web-small` on the web, and the brand levels `brief`, `lead`, `body`, `caption`.
The node format (`v`, `h`, `z`, `text`, `icon`, `img`, `spacer`, `use`) is the generator's; its README documents it.

## Composites (`components/core.mjs`)

| Name | Props |
|---|---|
| `macWindow` | the window at the spec's device: `selected` (today, home, decisions, products, growth, money, operations, playbook), `badges` `{ id: n }`, `store` (the Store build: no Today, no second section), `live` (up-to-date, stale, offline, updating), `linked` (route ids whose spec exists: the row links to `mac.<id>`), `kids`, `gap` |
| `iosScreen` | status bar, navigation bar, page, tab bar: `title`, `large` (default true), `back`, `trailing`, `tab` (home, decisions, products, growth, more; `null` hides the bar), `badges`, `linked` (tab ids: links to `iphone.<id>`), `kids`, `gap` |
| `iosStatusBar`, `iosNavBar`, `iosTabBar` | the same parts on their own |
| `terminal` | `title`, `theme` (light, dark), `prompt` (default `~ %`), `lines`: a string, `""` (empty line), `{ "cmd": "teyla today" }`, or a list of segments; a segment is a string, `{ "v", "role", "bold" }` with role primary, needs-you, saving, danger or text-secondary, or `{ "mark": true }` (the banner glyph) |
| `browser` | `url`, `kids`, `fill`; the window takes the spec's device (default 1440 x 900) |
| `card` | `platform` (mac, ios), `kids`, `gap`, `pad`, `link` |
| `pill` | `text`, `tone` (needs-you, saving, danger, primary, neutral) |
| `tile` | a stat tile: `label`, `value`, `detail`, `tone`, `platform`, `link` |
| `circles` | weekly circles: `done`, `total`, `size` |
| `activityGrid` | the activity graph: `weeks`, `cell`, `seed` |
| `brandMark` | the mark: `size` |
| `dark` | draws its `kids` (composites included) in the dark values: the file has one variable mode |

An area adds its own composites in `components/<area>.mjs`; a name may be defined once across the folder.

`components/mac.mjs` (Mac app, all prefixed `mac`): `macBtn`, `macChip`, `macField`, `macSegment`, `macFold`, `macPageHeader`, `macSection`, `macEmpty`, `macError`, `macAsk` (the ask card and its states), `macProductIcon`, `macSpark`, `macHero`, `macBuilt`, `macQuiet`, `macRowGroup`, `macRow`, `macSheet`, `macPopover`, `macQuickNote`, `macCommandBar`, `macBare`, `macQr`.

`components/review.mjs` (review capture form, prefixed `review`): `reviewPicture` (the frozen picture with a black privacy box and the mark), `reviewIos`, `reviewMac`, `reviewWeb`, `reviewAndroid` (each takes one state: `step` point, comment or done; `mark` none, spot or area; `text`, `listening`, `sending`, `failed`, `outcome` sent or saved, `notice`, `links`), `reviewLauncher`, `reviewWebNotice`. The form is unbranded, so it is drawn in each platform's defaults.

`components/web.mjs` (web, prefixed `web`, `site`, `readme`): `webPage` (the dashboard's top bar and 960 column), `webStart` and `webSpend` (each with a `state`), `webStat`, `webStrip`, `webEmpty`, `webBtn`, `webTag`, `siteHome` (teyla.dev at any width and in the dark values, the one breakpoint is 704 px), `readmeHero`.
