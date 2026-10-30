# UX and UI standard

One standard for every product. Each product keeps its own design system (`DESIGN.md`, its
tokens). This file says what every screen must do, whatever the style. `teyla ux check` audits
the mechanical part. The rest is judged in review, on the device, against the rubric in Part 5.

The short version: a screen does one thing, shows it first, and says it in few words.

## How this file works

- **At most 20 active rules.** A rule is a `### R<n>.` heading in Part 1 or Part 2. A new rule
  displaces one: move the weakest to "Retired or advisory" in the same PR. `teyla ux check`
  fails a standard with more than 20 active rules.
- **Every rule carries a date and a scope line**, directly under its heading:
  `Since <date> · Scope: <where it applies> · Check: <how it is checked>`.
  A rule with no date cannot be retested.
- **Rules copied from a WWDC session or a platform release are retested after each iOS
  release.** Set `Source:` on the rule. iOS 27 reversed parts of iOS 26 within a year; a rule
  that nobody retests becomes folklore. When a retest fails, retire the rule.
- **A rule that holds for every product** arrives here by hand, in a Teyla PR, from a product's
  confirmed rules (`design/rules/`). A product's own taste stays in its repo.
- **Advisory** material (heuristics, tests, tips) lives in "Retired or advisory" and is not
  counted. Check column values: `ux check` (counted, FIX or WARN), `review` (judged on the
  device or by the rubric).

## Where the rules come from

- **Apple Human Interface Guidelines**: clarity, deference (content over chrome), depth;
  44 pt tap targets; system controls and Dynamic Type before custom ones; the Writing page
  for UI text.
- **Material 3**: a type scale and a colour role system, not loose values; 48 dp touch targets;
  one primary action, shown as the most prominent control.
- **Nielsen's ten usability heuristics**: visibility of system status, match with the real
  world, error prevention, recognition over recall, minimalist design, help users recover
  from errors, consistency.
- **Refactoring UI** (Wathan, Schoger): hierarchy comes from size, weight and colour used
  sparingly; start with too much white space; limit the choices on the scale.
- **Linear and Things**: restraint as a product feature. Few controls, one accent colour,
  quiet chrome, fast.

Where these disagree, the platform's guideline wins for controls and the product's tokens win
for style.

## Part 1. Screen rules

### R1. One primary action, obvious in five seconds
Since 2026-10-16 · Scope: every screen · Check: review (rubric item 1)

Every screen has one primary action. Style it once: the most prominent control. Everything else
is secondary (plain or outline) or tertiary (text only). A second primary action means two
screens, or one screen and a menu. If a stranger cannot find the action in five seconds, cut;
do not add a hint.

### R2. At most three levels of type size per screen
Since 2026-10-16 · Scope: every screen · Check: review (rubric item 3); `ux check` does not count it

Title, body, caption. A fourth size is a sign that the screen holds two screens. Express
hierarchy with weight and colour first. Use the platform's text styles so Dynamic Type works.
This is a warning in review, not a ban.

### R3. Content before chrome
Since 2026-10-16 · Scope: every screen · Check: review (rubric item 4)

What the person came for goes first and gets the space. Navigation, toolbars, banners and
badges stay small and quiet: at most one banner, one badge cluster or one floating control per
screen. A divider, a shadow or a gradient needs a job.

### R4. Every list has four states
Since 2026-10-16 · Scope: every list and feed · Check: review

Has items, empty, loading, failed. Design all four before the first. Loading is a skeleton or
a progress indicator in place, never a blank screen. Error keeps the old content visible when
it still helps and offers one retry.

### R5. Progressive disclosure: about four tap targets, the rest one step away
Since 2026-10-16 · Scope: SwiftUI views (counted), other platforms (review) · Check: `ux check` WARN (more than 4 in one View)

Show the common case. Rare actions go into a menu, a detail screen or a sheet; settings go on
the settings screen. One screen, one job: if the title needs "and", split it. The count is a
prompt to look, never a FIX.

### R6. Consistency and platform fit
Since 2026-10-16 · Scope: every screen · Check: review (rubric item 2)

The same thing looks and behaves the same way everywhere. Use system controls (navigation, tab
bar, sheet, share, picker) where they exist. A Mac app is built for the Mac: pointer-sized
controls, windows, menus, keyboard shortcuts, and a window that can always be reopened. It is
never a stretched phone screen. A custom tab bar or toolbar gets none of a new OS release's
behaviour and is retested after it.

### R7. Accessibility is part of done
Since 2026-10-16 · Scope: every screen · Check: review; the capture matrix's accessibility walk

Tap targets are at least 44 pt (Apple) or 48 dp (Material). Contrast, Dynamic Type up to the
largest size and VoiceOver or TalkBack labels hold in light and dark.

### R8. Feedback and forgiveness
Since 2026-10-16 · Scope: every action · Check: review

Every action shows its result within 100 ms: a state change, a haptic, a toast. A destructive
action is undoable, or asks once with the object named ("Delete 3 notes"). Prevent the error
before you explain it: disable what cannot work and keep what the person typed.

## Part 2. Tokens rule

### R9. Views contain no raw font sizes, colours or spacing
Since 2026-10-16 · Scope: all view code, every platform · Check: `ux check` (WARN, FIX on density)

Views use the product's tokens. Fonts are named text styles (no `.system(size: 17)`, no
`fontSize = 17.sp`, no `font-size: 17px`). Colours are named roles with light and dark values
(no `Color(red:)`, hex or `rgb()` in a view). Spacing is a scale of 4 or 8 based steps (no
`.padding(13)`). Radii, shadows and durations are tokens too. Tokens live in one place per
platform (`*Tokens*`, `*Theme*` or `DesignSystem*`), which `ux check` does not read. A new value
is added to the tokens in the same PR, with a name.

## Part 3. UI copy rules (register b)

UI copy is register (b) of the writing policy (`POLICY.md`, section "Writing and reporting").
The product's `DESIGN.md` glossary and voice chart set its words and tone.

### R10. A button is a verb and an object, at most 3 words
Since 2026-10-16 · Scope: every button label · Check: `ux check` (length); the copy judge (the verb)

"Add note", "Send invite", "Save changes". Not "OK", not "Submit", not "Click here to continue".
Apple: a verb on every button.

### R11. No "Please", no exclamation marks, no "oops" or "uh-oh"
Since 2026-10-16 (Apple words added 2026-10-30) · Scope: all UI copy · Check: `ux check`

Say what to do: "Enter a valid email". Not in success messages, empty states or onboarding.
Apple: an error is not a joke, and it does not apologise for being an error.

### R12. An error says what happened and what to do, without "we"
Since 2026-10-16 (no "we": 2026-10-30) · Scope: every error string · Check: `ux check` (where the call shows an error); the copy judge

"Could not save. Check your connection and try again." Not "Something went wrong", not an
error code alone, not "We could not save". The system did it, not a "we".

### R13. An empty state names the next step
Since 2026-10-30 · Scope: every empty list or feed · Check: `ux check` (length where detectable); the copy judge · Source: Apple HIG Writing

Two sentences at most: what goes here, and the one action that fills it.

### R14. No possessive "Your" before a noun in a label or title
Since 2026-10-30 · Scope: titles, tabs, section headers, buttons · Check: `ux check` (a label of three words or fewer starting with "Your") · Source: Apple HIG Writing

"Favorites", not "Your Favorites". The screen is already theirs. A full sentence may say "Your
trip is saved".

### R15. Numbers instead of adjectives
Since 2026-10-16 · Scope: all UI copy · Check: review

"3 days left", not "almost out of time". "Synced 2 min ago", not "recently synced".

### R16. The same word for the same thing, in every language
Since 2026-10-16 · Scope: all UI copy · Check: review; the copy judge against the glossary

If it is a "trip" in one place it is a "trip" in all. The product's `DESIGN.md` keeps the
glossary, one word per concept in each language. Copy is written per language from the same
brief, never translated word for word. Localization stays in its own files.

### R17. Short: sentence case, one idea, say it once
Since 2026-10-16 · Scope: all UI copy · Check: review; the budgets below

At most 20 words a sentence, active voice. Do not put the same fact in a title, a subtitle
and a hint.

### Per-control length budgets

A budget is a ceiling for one control, not a target. `teyla ux check` counts the ones whose
control it can tell from the code; the copy judge reads the rest.

| Control | Budget | `ux check` counts it when |
|---|---|---|
| Button label | 3 words | a SwiftUI `Button("...")`, or an Android string named `btn_`, `button_`, `cta_`, `action_` |
| Screen title | 5 words | a SwiftUI `.navigationTitle("...")` |
| Empty state | 2 sentences | the string sits in an empty-state call (`ContentUnavailableView`, or an `empty...` name) |
| Error | 2 sentences | the string sits in an error call (a name with `error` or `failed`) |
| Onboarding step | 25 words | never: the code does not show which text is a step; judged in review |

## Part 4. The review process

### R18. Two variants, reviewed on the device, one round
Since 2026-10-16 · Scope: every new or reworked screen · Check: review (the PR)

Design is reviewed by the owner on the device, because a screen that looks right in a
screenshot can still be wrong in the hand.

1. **Two variants.** Two genuinely different ones, not two colour schemes of one idea. They
   differ in structure: what is the primary action, what is removed, what is one step away.
2. **Owner review on the phone** (or the real device: Mac, watch). Screenshots alone are not
   a review.
3. **One round of comments.** The owner picks and comments once. The agent does not keep
   iterating on its own taste.
4. **Apply only the accepted cuts.** No "while I was there" additions.
5. **Screenshots in the PR**, before and after, for each changed screen, in light and dark.
6. **A cut list**: what was removed, one line each. An empty cut list is a PR that added things.
7. Run `teyla ux check` before opening the PR.

### R19. Every change is a decision with a scope
Since 2026-10-30 · Scope: every UX comment from the owner · Check: review (the PR links the decision)

A comment becomes a fix, a rule or a reject, with a reason. A rule is proposed, never promoted
by the agent; the owner confirms it. A scoped decision (one screen, one component, the product)
never widens on its own.

## Part 5. The review rubric

The five items below judge a screen, by a person or by `teyla ux judge`. Each is scored 0, 1 or
2. An item the picture cannot show is "not assessed", never guessed. The rubric never gates a
merge on its own; the diff and the owner do.

| Item | 0 | 1 | 2 |
|---|---|---|---|
| 1. Task hierarchy | The primary action is hidden, absent or competes with another | Found, but only after reading or after a second look | Found at a glance; everything else is clearly secondary |
| 2. Native conventions | Custom controls where system ones exist, or a placement that breaks the platform (R6) | System controls with one odd placement or behaviour | The platform's own controls and placements throughout |
| 3. Readability | Text clipped, truncated or below contrast, or four or more type sizes | Readable, with one weak spot (a size too many, thin contrast) | Three sizes or fewer, clear contrast, nothing truncated at the largest size |
| 4. Layout coherence | Overlaps, uneven spacing, elements off the grid | Aligned, with one stray gap or edge | One grid, steps from the scale, nothing drifting |
| 5. Copy and brand fit | Breaks R10 to R17, a term outside the glossary, or the wrong voice | Follows the rules, with a flat or off-voice line | Follows the rules and the voice chart; every term is in the glossary |

A screen is done when it scores no 0, at least 8 of 10, and the owner has seen it on the
device and accepted it. It is also listed in the product's screen inventory, works at the
largest Dynamic Type or font size and in dark mode, and `ux check` adds no literals.

## Part 6. The ten-point checklist (run before asking for review)

Answer each with yes or no. Fix every no, or say why in the PR.

1. Can I name the one primary action, and is it the most prominent control?
2. Would a stranger find it in five seconds?
3. Are there at most three type sizes on this screen?
4. Did I remove something? Is it on the cut list?
5. Does content come before chrome?
6. Do the empty, loading and error states exist, and does the empty state name the next step?
7. Are there about four tap targets or fewer, with the rest behind a menu, a sheet or a detail screen?
8. Are there zero raw font sizes, colours and spacing values in my diff?
9. Does every button start with a verb, in 3 words or fewer, with no "Please", no "!" and no "oops"?
10. Did I run `teyla ux check`, attach before and after screenshots, and build two variants?

## What the audit cannot see

`teyla ux check` counts literals, tap targets and copy patterns. It cannot tell whether the
primary action is obvious, whether the hierarchy reads, or whether a screen is the right
screen. A green check means the mechanical rules hold. The owner's review on the device is the
test of the design.

## Retired or advisory

Not counted toward the 20. Advice and tests that help, and rules that were cut to make room.

- **Offline is a state, not an error.** Say what still works. (advisory, since 2026-10-16)
- **Defaults beat options.** Every setting nobody changes is a decision pushed onto the user.
  (advisory, since 2026-10-16)
- **Do not repeat the screen title** in the navigation bar and again in the body.
  (advisory, since 2026-10-16)
- **The five-second test.** Show the screen for five seconds, then ask what it is for and what
  to tap. (advisory, since 2026-10-16)
- **Undo beats confirm.** Prefer an undo toast to a dialog when the action is cheap to reverse.
  (advisory, since 2026-10-30)
