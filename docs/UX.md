# UX

Teyla holds one UX and UI standard for every product, and a check that audits a product
against its mechanical part. Each product keeps its own design system. Teyla does not choose
colours or fonts.

| What | Where |
|---|---|
| The standard: at most 20 dated, scoped rules (screens, tokens, UI copy, review), per-control length budgets, the five-item review rubric, a 10-point checklist | `templates/design/STANDARD.md` |
| The per-product template, under 100 lines: tokens, components, glossary, screens, rules from review, what is absent | `templates/design/DESIGN.md` |
| The audit | `teyla ux check` |
| The review loop, the drift matrix, the judge, the copy lane and the brand kit: concept, decisions and roadmap | [STUDIO.md](STUDIO.md) |

## Start a product

Copy `templates/design/DESIGN.md` to the product's root as `DESIGN.md` (or into `docs/`). Fill
in the tokens (source file, how they are generated), the component list with file paths, the
glossary (one word per concept, a column per language), the voice line and what is absent.
`teyla ux check` warns while the file is missing or still holds `{{` placeholders, and fails a
file over 100 lines: history goes to `docs/decisions/`, the owner's taste to `design/`.

The "Screens" and "Rules from review" sections sit between marker comments
(`<!-- teyla:screens -->`, `<!-- teyla:rules -->`). The taste ledger ([STUDIO.md](STUDIO.md),
section 5.1) renders them from `design/screens/*.yaml` and `design/rules/*.yaml`; do not edit
between the markers by hand.

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
| crowded | SwiftUI views with more than four `Button`, `NavigationLink` and `onTapGesture`. A warning, never a FIX |
| copy | UI strings that break the copy rules (below) |
| design | `DESIGN.md` missing, unfilled (WARN) or over 100 lines (FIX) |
| standard | The repo's `STANDARD.md`: more than 20 active rules (FIX), a rule with no date and scope line (WARN) |

Each repo gets OK, WARN or FIX. A FIX means ignoring the tokens, or writing copy against the
rules, is the norm in that repo, or that a design file or standard has grown past its limit.
The thresholds are in the docstring of `src/teyla/ux_check.py`. The check does not read
tests, previews, generated files, build output or token files.

### The copy findings

| Finding | Counted when |
|---|---|
| "Please", "!" | any UI string has it |
| "oops", "whoops", "uh-oh" | any UI string has it (Apple's Writing page) |
| "Your" before a noun | a label of three words or fewer that starts with "Your" and is not a sentence |
| Button over 3 words | a SwiftUI `Button("...")`, or an Android string named `btn_`, `button_`, `cta_`, `action_` |
| Title over 5 words | a SwiftUI `.navigationTitle("...")` |
| "we" in an error | a `Text` on a line that names an error (`error`, `failed`), or a string whose resource name or key does |
| Error or empty state over 2 sentences | the same contexts; an empty state is `ContentUnavailableView` or an `emptyState`-style name |

The check only counts a budget where the code shows the control. A line that names both an
error and an empty state, or neither, has no context and is skipped, never guessed. Not
counted, judged in review and by the copy judge: the onboarding step budget (25 words), a verb
on every button, "an empty state names the next step".

"More than three type sizes" is not counted from code. It is rule R2 of the standard, judged
in review (rubric item 3), as a warning.

### The standard

`templates/design/STANDARD.md` holds at most 20 active rules. A rule is a `### R<n>.` heading
with `Since <date> · Scope: ... · Check: ...` under it. Rules cut to make room, and advice,
go under "Retired or advisory", which is not counted. Rules copied from one WWDC or platform
release are retested after each iOS release. The review rubric (task hierarchy, native
conventions, readability, layout coherence, copy and brand fit, each 0 to 2) is Part 5 of the
standard; `teyla ux judge` scores against the same table.

A count is a pointer to look, not proof. The check cannot tell whether a screen has an obvious
primary action. The owner's review on the device does.

## Review a screen

1. Build two genuinely different variants of the screen.
2. The owner reviews both on the phone, or the real device.
3. One round of comments.
4. Apply only the accepted cuts.
5. Put before and after screenshots and a cut list (what was removed) in the PR.
6. Run `teyla ux check` before opening the PR.

The full rules, the budgets, the rubric and the ten-point checklist are in
`templates/design/STANDARD.md`.
