# The screen atlas

Agents build the screens, so nobody holds the whole picture of an app. The atlas is that picture, drawn from code
(decision S19 in `decisions/2026-11-08-studio-2.md`). It answers three questions: which screens exist, how
many of them were captured, and which features no screen shows.

## Quick start

1. Write one `design/screens/<id>.yaml` per screen (format below). Start with the tab roots.
2. `teyla ux registry check <repo>` lists invalid entries and the coverage.
3. `teyla ux atlas <repo> --open` writes `design/atlas/atlas.html` and opens it.

Captures come from the tour (`teyla ux shots`, [MATRIX.md](MATRIX.md)). The atlas never captures anything itself.

## The registry: `design/screens/<id>.yaml`

The file name is the screen id (lowercase letters, digits, dots, dashes, underscores). Every key is optional, so an
older inventory entry (`job`, `primary_action`, `states`, `string_keys`, `catalog`; see [TASTE.md](TASTE.md)) stays valid.

| key | meaning |
|---|---|
| `id` | Only when the file name cannot be the id. Must stay unique. |
| `title` | The name people use. Default: the id. |
| `parent` | The screen this one opens from. Builds the tree. |
| `level` | `1` is a tab root. Default: the parent's level plus one, or `1` without a parent. |
| `platforms` | Where the screen exists: `ios`, `ipados`, `macos`, `web`, `android`. Default `[ios]`. Each one is expected to be captured. |
| `route` | The route id in `design/tour.yaml` that captures it. A screen without a route cannot be captured. |
| `links` | Where a screen leads: `{to, via, tested}`. `tested: true` means a UI test walks that edge. |
| `layout` | The layout contract (decision S18): one sentence each for `compact`, `regular`, `wide`. `assert` names the test that enforces it. |
| `features` | Sections of `docs/FEATURES.md` (by name, or `Surface / Name`), or an anchor or feature text from one of its rows. |
| `source` | Files that draw the screen, relative to the repo. |
| `job`, `primary_action`, `states`, `string_keys`, `catalog` | The inventory keys of [TASTE.md](TASTE.md). |

```yaml
title: Recipes
level: 1
platforms: [ios, macos]
route: recipes
job: Browse saved recipes and start a new one.
primary_action: Add recipe
states: [empty, loaded, error]
layout:
  compact: A single list.
  regular: A list with a detail pane.
  wide: A grid of cards.
  assert: testRecipesWideShowsGrid
links:
  - to: recipe
    via: tap a row
    tested: true
  - to: add-recipe
    via: tap Add
    tested: false
features: [Recipe list]
source: [App/Recipes/RecipeList.swift]
```

A template with comments is `templates/design/screen.yaml`. The registry is a small YAML subset (maps, lists, lists of
maps, inline lists); an entry that does not parse is an invalid entry that names its file.

## What counts as captured

A screen is expected once per platform it lists. It is captured on a platform when a PNG of its route exists, in any
language, look or state:

| where | what |
|---|---|
| `design/shots/<lang>-<look>/<route>.<state>.png` | the current iOS run (`look` is `light`, `dark` or `large`) |
| `design/shots/<platform>/<lang>-<look>/<route>.<state>.png` | the same for another platform |
| `design/shots/baseline/...` | the accepted run, same shapes; the current run wins when both exist |

"Captured / expected" counts screen and platform pairs: a screen on iOS and macOS is two. Per platform and look the check
prints how many pairs have that look. The banner of the atlas shows the same numbers.

## `teyla ux registry check [repo] [--json]`

Exit 1 only for an invalid entry: a parse error, a duplicate id, an unknown parent or link target, a parent loop,
a link to itself, a bad `level`, `platforms`, `layout` or `links` value, or a `route` that `design/tour.yaml` does not
define. Everything else is a warning: no layout contract for a size class, a `source` path or a `layout.assert` test
that does not exist in the code (a text search of the code files), a `features` entry that matches nothing,
a screen with no route, a tour route no screen names.

## `teyla ux atlas [repo] [--out DIR] [--lang L] [--open]`

Writes `atlas.html` and `atlas-img/` into `DIR` (default `<repo>/design/atlas/`). The atlas clears only `atlas-img/`, and only when its own marker file `.teyla-atlas` is inside; any other folder of that name makes it refuse with exit 2. Add that folder to the product's `.gitignore`
or commit it; the page is regenerated from code either way. `--lang` picks the language of the screenshots shown
(default: the first language of the tour). The page has no external request, so it works from `file://` and in an
air-gapped review.

- **Grid.** Screens grouped by level, each card with its screenshots per platform and look, or a dashed "not captured"
  box. Above them: the coverage banner and the gaps.
- **Map.** The navigation graph. Screens sit in columns by level; a parent is centred over its children. An arrow with a
  solid line is a tested link, a dashed arrow a declared one, a grey line a parent edge with no link. Drag to pan, wheel to
  zoom. A click opens the side panel: screenshots, job, primary action, the three layout sentences (and whether the
  `assert` test exists), links in and out, features, source files.
- **Filters.** By platform and by coverage, shared by both views.

If `docs/FEATURES.md` exists, every section with a table whose first column is "Feature" counts. A screen maps sections through
`features`. Sections no screen names are listed as a coverage gap, with the number of rows.

## Rules

- A new screen adds its registry entry in the same PR, like a feature adds its row ([decision S19]).
- Figma frames are generated from the atlas, never drawn by hand (STANDARD R20).
- The atlas shows what the registry says. A screen missing from the registry is invisible, and `registry check` cannot
  find it: keep the entry next to the screen.

[decision S19]: decisions/2026-11-08-studio-2.md
