# Design: {{product}}

This is the product's own design system. It follows the shared standard in Teyla's
`templates/design/STANDARD.md` and fills in what is specific here. Copy it to `DESIGN.md` or
`docs/DESIGN.md` and delete the guidance lines. `teyla ux check` warns while any `{{` is left.

## Tokens
Where they live: {{path to the tokens file, one per platform}}. Views use these names only.

| Token | Name in code | Value |
|---|---|---|
| Type: title / body / caption | {{names}} | {{sizes and weights}} |
| Colour roles: background, surface, text, text-secondary, accent, danger | {{names}} | {{light and dark values}} |
| Spacing steps | {{names}} | {{for example 4, 8, 12, 16, 24, 32}} |
| Radius, shadow, motion | {{names}} | {{values}} |

## Voice (register b)
UI copy only. Social and marketing text follows the voice chart (`VOICE.md`).
- The product sounds: {{3 adjectives, for example calm, direct, warm}}
- Address: {{you or we; formal or informal, per language}}
- Glossary, one word per thing, never rotated: {{trip = trip, not journey or plan}}
- Buttons: verb plus object, at most 3 words. No "Please". No "!".
- Errors: what happened, then what to do.

## Screen inventory
One row per screen. The primary action is one verb and one object.

| Screen | Job (one sentence) | Primary action | Empty / loading / error | Last reviewed on device |
|---|---|---|---|---|
| {{screen}} | {{job}} | {{verb object}} | {{yes / yes / yes}} | {{date}} |

## Deliberately absent
What this product chooses not to have, so nobody adds it back by habit. One line each, with
the reason.
- {{for example: no streaks or badges. They push the person back; the product should not.}}
- {{for example: no settings screen for X. The default is right for everyone.}}

## Platforms
Primary: {{platform}}. Others and their trigger: see `teyla.toml` and the platforms policy.
Mac builds are adapted to the Mac, never a stretched phone screen.
