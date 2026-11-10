# The design cycle

One decision at a time. Research first. The owner picks from two or three options, recommended first.

## Why

On 2026-11-10 the owner rejected three design directions for a product as raw: design for its own sake,
with no thought for how to make the product truly convenient. He asked for a different process. Taste
changes (UX and UI, copy, interactions, swipes) are split into components and settled step by step with
him: the design system apart from the main menu, for example. Before any option reaches him, the AI
researches: guidelines, practitioner posts, how similar and popular apps do it, usage statistics. It forms
hypotheses and gathers state-of-the-art solutions. It shows the recommended one first. He wants Teyla to
run this. He also asked that results be measured in test builds, so he does not have to collect data.
His verbatim words are in the product's intent file: `cat "$(teyla intent path <product>)"`.

## The map

A redesign is a decision map: 8 to 12 decisions in dependency order, structure before look. One decision is
one card. Nothing is built for a later decision before the earlier one is picked. A decision is a user's job
inside a whole journey, not a component. After every structural pick, run two journeys again on the build:
an ordinary day and a trip. Low-taste choices are not cards: take the guideline default and list it in the PR.

## The eight steps

1. **Evidence.** Agents write `dossier.md` with five parts: the owner's words and earlier picks, usage,
   guidelines, how 6 to 10 products solve it, practitioner reports. Label every item `guideline`,
   `observation` or `hypothesis`. A popular app or a post is never evidence by itself. Timebox: one hour.
2. **Hypotheses.** Two to four. One sentence each, with the observation that would refute it.
3. **Options.** Two or three, never more. The recommended one is first, with a one-line why. Each says what
   the user does differently, what it removes or moves, the evidence and the cost. The current behaviour is
   an option when it is viable. Options differ in how the job is done, not in colour.
4. **Filter.** Run `teyla ux check`, `teyla ux judge --filter VARIANTS` and a critique from another provider.
   An option that cannot run with real data and a real save is not shown.
5. **Shown in context.** Structure: a switch in the test build, on real data. Look: a live switch over the
   same screens for every option. Copy: a board of real strings. Never a toy flow.
6. **The pick.** One card, 250 words at most, 15 minutes of the owner's time. He picks, or says "none" with
   one sentence. The pick is stored with his sentence, verbatim.
7. **The rule.** The pick opens a `taste` rule proposal with a scope. He confirms it once. Agents never do.
8. **Build and measure.** Only the picked option goes into the default. Measure the same job before and
   after. A change that does not get faster is reverted.

## Files

All under the product repo's `design/decisions/`. A filled sample is in `templates/design/decisions/`.

- `map.yaml`: `decisions:`, each with `id`, `title`, `journey`, `needs: [ids]`, and
  `status: open | researching | options | picked | built`.
- `<id>/dossier.md`: five `##` headings (exact names in the sample). Parts 2 to 5 list items as
  `- guideline: ...`, `- observation: ...` or `- hypothesis: ...`.
- `<id>/options.yaml`: `options:` with two or three entries. The first has `recommended: true` and `why`.
  Each has `id`, `summary`, `user_does`, `removes_or_moves`, `evidence`, `cost`.
- `<id>/pick.yaml`: `option` (an option id or `none`), `sentence`, `date`, `scope: screen | product | all`,
  and `supersedes` when it replaces an earlier pick.

## Commands

```
teyla design map <product>              scaffold map.yaml, or validate it (unknown needs, cycles)
teyla design next <product>             the first decision whose needs are picked and which is not
teyla design dossier <product> <id>     scaffold the five parts
teyla design options <product> <id>     check the dossier and the options; open the card in `teyla asks`
teyla design pick <product> <id> <option|none> --sentence "..."   store the pick; propose the rule
teyla design built <product> <id>       refused until the decision is picked
teyla design status <product>           the map with each decision's state
```

`options` refuses without a full dossier, with a fourth option, or when the first is not recommended.
`teyla answer <card-id> <option> <his reason>` on the card writes the same `pick.yaml`.
A picked decision is reopened only by the owner, or by measured evidence against it (`pick --supersede`).
