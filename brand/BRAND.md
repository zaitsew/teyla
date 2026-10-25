# Teyla brand

Status: proposal. Three mark concepts share one wordmark and one token set. The owner picks a
mark; the app icon and the UI tokens follow in a separate PR.

Teyla reads your Claude Code and Codex sessions on your Mac, shows what they cost and what's
waiting on you, and fixes the waste. The brand is a calm control room for one person: quiet
until something needs them, and then exact about what.

## Files

- `board.html`, `board.png`: every concept at 16, 32, 64, 256 and 1024 px, on light and dark,
  as a macOS app icon, in a terminal banner and in a README hero.
- `concept-{1,2,3}/`: `mark.svg`, `mark-dark.svg`, `lockup.svg`, `lockup-dark.svg`, `icon.svg`
  (1024 canvas, 824 body, 185 corner, as in `apps/mac/Tools/make_icon.swift`).
- `tokens.json`: colours for light and dark, contrast ratios, ANSI 256 indices, type, space,
  radius.
- `build.py`: the one place the shapes are described. Edit it, then run
  `python3 brand/build.py` to rewrite the SVGs and the board.

## The concepts

1. **Lanes.** Three session bars. The middle one is shorter and ends in an amber dot: the one
   that waits on you.
2. **Meter.** An open dial with the needle resting low. A small amber dot sits in its opening.
3. **Cursor.** A block T whose right arm is an amber cursor: the terminal waiting for input.
   Recommended.

Amber means "waiting on you" in every concept and everywhere else. Green means money saved.
Neither colour is decoration.

## Colour and type

| role | light | dark |
|---|---|---|
| primary (indigo) | `#3A4AA8` | `#9AA7F2` |
| needs you (amber) | `#A65400` | `#F2B04B` |
| saving (green) | `#13734A` | `#4CC98A` |
| text / secondary | `#14161D` / `#585E6D` | `#ECEDF2` / `#A2A7B5` |
| background / surface | `#F7F7F9` / `#FFFFFF` | `#0E1015` / `#171A21` |

Every text colour passes WCAG AA (4.5:1) on both background and surface. The lowest is
needs-you on the light background, at 5.1:1. Type is the system stack: SF Pro, then Inter, for
UI; SF Mono, then Menlo, for code and the terminal. The wordmark is drawn as paths and needs no
font.

## Voice: five rules

1. **Calm.** Report, do not alarm. "2 sessions wait on you", not "Action required!". No
   exclamation marks, no red unless something is broken.
2. **Exact.** Name the thing: the product, the session, the file, the age. "notes-app asked 3 h ago",
   not "a session needs attention".
3. **Numbers over adjectives.** "$6.10 saved this week", "p90 12 s, was 40 s". Never "much
   cheaper" or "way faster".
4. **No hype.** No "AI-powered", "supercharge", "magic", "10x", "seamless". Say what it does and
   what it costs.
5. **Plain English.** Short sentences in the active voice, at most 20 words. A button is a verb
   and an object: "Answer ask", "Move to Haiku".
