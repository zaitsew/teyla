# UX

Teyla holds one UX and UI standard for every product, and a check that audits a product
against its mechanical part. Each product keeps its own design system. Teyla does not choose
colours or fonts.

| What | Where |
|---|---|
| The standard: screen rules, tokens rule, UI copy rules, review process, definition of done, a 10-point checklist | `templates/design/STANDARD.md` |
| The per-product template: tokens, voice, screen inventory, what is absent | `templates/design/DESIGN.md` |
| The audit | `teyla ux check` |
| The review loop, the drift matrix, the judge, the copy lane and the brand kit: concept, decisions and roadmap | [STUDIO.md](STUDIO.md) |

## Start a product

Copy `templates/design/DESIGN.md` to the product's root as `DESIGN.md` (or into `docs/`). Fill
in the tokens, the voice section, the screen inventory and the list of what is deliberately
absent. `teyla ux check` warns while the file is missing or still holds `{{` placeholders.

## Run the check

```
teyla ux check                  # the git repo of the current directory
teyla ux check atlas cellar      # repos under code_root, or paths
teyla ux check --all --json     # every repo under code_root
teyla ux check --strict         # exit 1 when a repo has a FIX
```

It reads files only, with no network, and takes a second or two. It covers SwiftUI, Jetpack
Compose and web code (tsx, jsx, css, scss, vue, svelte).

| Count | Meaning |
|---|---|
| font, colour, spacing | Values typed into a view instead of taken from a token, and the five files with the most |
| crowded | SwiftUI views with more than four `Button`, `NavigationLink` and `onTapGesture` |
| copy | UI strings with "Please" or "!", and button labels over three words |
| design | `DESIGN.md` missing, or unfilled |

Each repo gets OK, WARN or FIX. A FIX means ignoring the tokens, or piling taps onto screens,
is the norm in that repo. The thresholds are in the docstring of `src/teyla/ux_check.py`. The
check does not read tests, previews, generated files, build output or token files.

A count is a pointer to look, not proof. The check cannot tell whether a screen has an obvious
primary action. The owner's review on the device does.

## Review a screen

1. Build two genuinely different variants of the screen.
2. The owner reviews both on the phone, or the real device.
3. One round of comments.
4. Apply only the accepted cuts.
5. Put before and after screenshots and a cut list (what was removed) in the PR.
6. Run `teyla ux check` before opening the PR.

The full rules, the definition of done and the ten-point checklist are in
`templates/design/STANDARD.md`.
