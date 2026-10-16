# UX and UI standard

One standard for every product. Each product keeps its own design system (`DESIGN.md`, its
tokens). This file says what every screen must do, whatever the style. `teyla ux check` audits
the mechanical part. The rest is judged in review, on the device.

The short version: a screen does one thing, shows it first, and says it in few words.

## Where the rules come from

- **Apple Human Interface Guidelines**: clarity, deference (content over chrome), depth;
  44 pt tap targets; system controls and Dynamic Type before custom ones.
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

### 1. One primary action, obvious in five seconds

Every screen has one primary action. A person who has never seen it should find that action in
five seconds, without reading help.

- Style the primary action once: the most prominent control on the screen. Everything else is
  secondary (plain or outline) or tertiary (text only).
- A second primary action means two screens, or one screen and a menu.
- Test it: show the screen to someone for five seconds, then ask what it is for and what to
  tap. If the answer is wrong, cut, do not add a hint.

### 2. At most three levels of type size per screen

Title, body, caption. A fourth size is a sign that the screen holds two screens.

- Express hierarchy with weight and colour before you add a size.
- Sizes come from the product's type scale, never typed into a view (Part 2).
- Use the platform's text styles so Dynamic Type and font scaling work.

### 3. Content before chrome

What the person came for goes first and gets the space. Navigation, toolbars, banners and
badges are chrome. They stay small and quiet.

- No more than one banner, one badge cluster or one floating control per screen.
- No decoration without information. A divider, a shadow or a gradient needs a job.
- Do not repeat the screen title in the navigation bar and again in the body.

### 4. Empty, loading and error states for every list

A list has four states: has items, empty, loading, failed. Design all four before the first.

- **Empty**: one sentence saying what goes here, and the one action that fills it.
- **Loading**: a skeleton or a progress indicator in place. Never a blank screen. Never a
  spinner over content that is already there.
- **Error**: what happened, what to do, one retry control. Keep the old content visible when
  it still helps.
- Offline is a state, not an error. Say what still works.

### 5. Progressive disclosure instead of more buttons

Show the common case. Put the rest one step away.

- Four or fewer tap targets compete on a screen. The `crowded` check counts more than four
  `Button`, `NavigationLink` and `onTapGesture` in one view. It is a prompt to look, not a
  ban.
- Rare actions go into a menu, a detail screen or a sheet. Settings go on the settings screen.
- Defaults beat options. Every setting that nobody changes is a decision you pushed onto the
  user.
- One screen, one job. If the title needs "and", split it.

### 6. Consistency and platform fit

- The same thing looks and behaves the same way everywhere. One name per thing.
- Use system controls (navigation, tab bar, sheet, share, picker) where they exist.
- A Mac app is built for the Mac: pointer-sized controls, windows, menus, keyboard shortcuts,
  and a window that can always be reopened. It is never a stretched phone screen.
- Tap targets are at least 44 pt (Apple) or 48 dp (Material).
- Contrast, Dynamic Type and VoiceOver or TalkBack labels are part of done, not polish.

### 7. Feedback and forgiveness

- Every action shows its result within 100 ms: a state change, a haptic, a toast.
- A destructive action is undoable, or asks once with the object named ("Delete 3 notes").
- Prevent the error before you explain it: disable what cannot work, validate while typing,
  keep what the person typed.

## Part 2. Tokens rule

Views contain no raw font sizes, colours or spacing. They use the product's tokens.

- **Fonts**: named text styles from the product's type scale. No `.system(size: 17)`, no
  `fontSize = 17.sp`, no `font-size: 17px` in a view.
- **Colours**: named roles (background, surface, text, text-secondary, accent, danger). No
  `Color(red:)`, `Color(0xFF...)`, hex or `rgb()` in a view. Light and dark come from the role,
  not from the view.
- **Spacing**: a scale of 4 or 8 based steps (for example 4, 8, 12, 16, 24, 32). No
  `.padding(13)`.
- **Radii, shadows, durations**: tokens too.
- Tokens live in one place per platform (a file named `*Tokens*`, `*Theme*` or
  `DesignSystem*`). `teyla ux check` does not read those files and does read everything else.
- A new value is added to the tokens, in the same PR, with a name. It is not typed into a view.

## Part 3. UI copy rules (register b)

UI copy is register (b) of the writing policy (`POLICY.md`, section "Writing and
reporting"). The product's `DESIGN.md` voice section sets its tone. These rules hold for
all of them:

- **A button is a verb and an object, at most 3 words.** "Add note", "Send invite",
  "Save changes". Not "OK", not "Submit", not "Click here to continue".
- **No "Please".** Say what to do: "Enter a valid email".
- **No exclamation marks.** Not in success messages, not in empty states, not in onboarding.
- **An error says what happened and what to do.** "Could not save. Check your connection and
  try again." Not "Something went wrong" and not an error code alone.
- **Numbers instead of adjectives.** "3 days left", not "almost out of time". "Synced 2 min
  ago", not "recently synced".
- **The same word for the same thing.** If it is a "trip" in one place it is a "trip" in all.
  The product's `DESIGN.md` keeps the glossary.
- **Sentence case.** One idea per sentence, at most 20 words. Active voice.
- **Say it once.** Do not put the same fact in a title, a subtitle and a hint.
- **Localization stays in its own files.** Copy is written per language from the same brief,
  never translated word for word.

`teyla ux check` counts "Please", "!" and button labels over 3 words. It cannot judge the rest.

## Part 4. The review process

Design is reviewed by the owner on the device, because a screen that looks right in a
screenshot can still be wrong in the hand.

For any new or reworked screen:

1. **Two variants.** Build two genuinely different ones, not two colour schemes of one idea.
   One may be the current screen with things cut. They differ in structure: what is the
   primary action, what is removed, what is one step away.
2. **Owner review on the phone** (or the real device: Mac, watch). Ship both behind a debug
   switch or as two builds. Screenshots alone are not a review.
3. **One round of comments.** The owner picks and comments once. The agent does not keep
   iterating on its own taste.
4. **Apply only the accepted cuts.** Anything the owner did not accept stays out. No
   "while I was there" additions.
5. **Screenshots in the PR**, before and after, for each changed screen, in light and dark.
6. **A cut list in every UX PR**: what was removed, in one line each. A UX PR with an empty
   cut list is a PR that added things. Say why that was needed, or rework it.
7. Run `teyla ux check` before opening the PR and paste the line for the repo.

## Part 5. Definition of done for a screen

A screen is done when all of these hold:

- It has one primary action, and a new person finds it in five seconds.
- It uses at most three type sizes, all from the type scale.
- It has designed empty, loading and error states (and offline, where it applies).
- It uses tokens only. `teyla ux check` adds no literals.
- Its copy follows Part 3, and every term is in the product's glossary.
- It works at the largest Dynamic Type or font size and in dark mode, with labels for
  VoiceOver or TalkBack.
- The owner has seen it on the device and accepted it.
- It is listed in the product's screen inventory (`DESIGN.md`).

## Part 6. The ten-point checklist (run before asking for review)

Answer each with yes or no. Fix every no, or say why in the PR.

1. Can I name the one primary action, and is it the most prominent control?
2. Would a stranger find it in five seconds?
3. Are there at most three type sizes on this screen?
4. Did I remove something? Is it on the cut list?
5. Does content come before chrome (at most one banner, badge cluster or floating control)?
6. Do the empty, loading and error states exist and read well?
7. Are there at most four tap targets, or is the rest behind a menu, a sheet or a detail screen?
8. Are there zero raw font sizes, colours and spacing values in my diff?
9. Does every button read verb plus object in 3 words or fewer, with no "Please" and no "!"?
10. Did I run `teyla ux check`, attach before and after screenshots, and build two variants?

## What the audit cannot see

`teyla ux check` counts literals, tap targets and copy patterns. It cannot tell whether the
primary action is obvious, whether the hierarchy reads, or whether a screen is the right
screen. A green check means the mechanical rules hold. The owner's review on the device is the
test of the design.
