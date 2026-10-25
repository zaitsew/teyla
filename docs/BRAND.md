# Teyla brand

Teyla reads your Claude Code and Codex sessions on your Mac, shows what they cost and what's
waiting on you, and fixes the waste. The brand is a calm control room for one person: quiet
until something needs them, and then exact about what.

## The mark: Cursor

A block T whose right arm is a separate amber block, the cursor a terminal shows while it waits
for input. The T is Teyla; the amber block is what waits on you.

- **Colours.** The T is `primary`. The block is amber: `#C9740A` on light, `#F2B04B` on dark and
  on the app icon's indigo body. In one colour, both parts take the same colour.
- **Wordmark.** "Teyla" in the block cut: stroke 9, cut ends, square joins. Its cap top and
  baseline line up with the T's bar and stem. The wordmark is drawn as paths; never set it in a
  font.
- **Small sizes.** The mark holds at 16 px: a solid T and one 2.5 by 4 px block. Below 16 px,
  use the T alone.
- **Clear space.** Keep the width of the amber block free on every side.
- **Terminal.** The CLI's two-character mark is a bold `T` in `primary`, then `█` in `needs-you`.

## Files

| file | what it is |
|---|---|
| `brand/mark.svg`, `brand/mark-dark.svg` | the mark for light and dark backgrounds |
| `brand/lockup.svg`, `brand/lockup-dark.svg` | mark and wordmark |
| `brand/icon.svg` | the macOS icon artwork: 1024 canvas, 824 body at 100, 185 corner |
| `brand/tokens.json` | colours, contrast, ANSI 256, type, space and radius: the single source |
| `brand/board.html`, `brand/board.png` | the three concepts compared at every size |
| `brand/concept-{1,2,3}/` | Lanes, Meter and Cursor, kept as alternatives |
| `brand/build.py` | the one place the shapes are described |

To change the mark, edit `brand/build.py` (`CHOSEN` picks the concept), then run:

```bash
python3 brand/build.py                  # SVGs and the board
swift apps/mac/Tools/make_icon.swift    # Mac app icon, every size, and the plugin icon
```

Three places mirror `brand/tokens.json`: the colours in `apps/mac/Teyla/UI/Tokens.swift`, the
terminal palette in `src/teyla/brand.py`, and this page. `tests/test_brand.py` fails when the
Swift or Python values differ from the JSON.

## Colour

| role | light | dark | use |
|---|---|---|---|
| primary (indigo) | `#3A4AA8` | `#9AA7F2` | the mark, links, the selected state |
| needs you (amber) | `#A65400` | `#F2B04B` | something waits on the person |
| saving (green) | `#13734A` | `#4CC98A` | money saved |
| danger | `#B42318` | `#F87166` | something is broken |
| text / secondary | `#14161D` / `#585E6D` | `#ECEDF2` / `#A2A7B5` | body text, captions |
| background / surface | `#F7F7F9` / `#FFFFFF` | `#0E1015` / `#171A21` | window, cards |

Every text colour passes WCAG AA (4.5:1) on both background and surface. The lowest is
needs-you on the light background, at 5.1:1. Amber and green carry meaning; neither is
decoration.

In the terminal, `src/teyla/brand.py` picks ANSI 256 colours for a light or dark background
(`TEYLA_THEME`, then `COLORFGBG`) and falls back to the 16 basic colours otherwise. `NO_COLOR`,
`TERM=dumb` and output that is not a terminal get plain text.

## Type

The system stack, nothing to bundle: SF Pro, then Inter, for UI; SF Mono, then Menlo, for code
and the terminal. Four sizes: 28 semibold for the brief and titles, 16 medium for lead lines,
13 for body text, 11 for captions.

## Voice: five rules

1. **Calm.** Report, do not alarm. "2 sessions wait on you", not "Action required!". No
   exclamation marks, no red unless something is broken.
2. **Exact.** Name the thing: the product, the session, the file, the age. "notes-app asked
   3 h ago", not "a session needs attention".
3. **Numbers over adjectives.** "$6.10 saved this week", "p90 12 s, was 40 s". Never "much
   cheaper" or "way faster".
4. **No hype.** No "AI-powered", "supercharge", "magic", "10x", "seamless". Say what it does and
   what it costs.
5. **Plain English.** Short sentences in the active voice, at most 20 words. A button is a verb
   and an object: "Answer ask", "Move to Haiku".
