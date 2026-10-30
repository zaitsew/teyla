# Reference screens

The screens a new screen is judged against. Per screen type, up to three named reference screens, what to
copy from each, and a link. A reference is a named screen, not a library: "just because an app is successful
doesn't mean the UI is great" (docs/STUDIO.md §3), so each entry says which part to copy and leaves the rest.

How a product uses it:

1. Copy the files of the screen types you ship from `templates/design/references/<screen-type>.yaml` to
   `design/references/` in the product. The format is in `docs/TASTE.md`. Edit them: drop an entry that does
   not fit, add the product's own best screen.
2. Save a screenshot of your screen and one of the reference, then run
   `teyla ux judge ours.png reference.png --repo <product>` (docs/JUDGE.md). The share of a product's screens
   that beat their reference is its score; the judge never gates a merge.
3. When the owner names a screen from another app in a review, add it here or to the product's file.

Each "what to copy" line is a pattern, not a layout. Copy the idea, then draw it with the product's tokens
and the platform's own controls (R6). An entry marked **to confirm** comes from an award text or a second-hand
report: open the app, find the exact screen, and replace the line before relying on it.

Seeded 2026-10-30 from the research in docs/STUDIO.md §3. Re-check each link when a new iOS ships (R6 and the
standard's retest rule): iOS 27 returned search to the tab bar and changed toolbars.

## onboarding

| Reference | What to copy | Link |
|---|---|---|
| Structured | A model pre-fills a simple timeline, so the first screen is not empty. Named in Apple's 2026 Design Awards finalist text | https://apps.apple.com/us/app/structured-daily-planner-todo/id1499198946 |
| Moonlitt (**to confirm**) | Apple's 2026 Design Awards text calls its onboarding easy. Open the first-run screens and copy the one step that does the most with the fewest taps | https://apps.apple.com/us/app/moonlitt-moon-phase-tracker/id6444718902 |
| Finch (**to confirm**) | A companion character that people keep opening. Study how the first run introduces it before copying anything | https://finchcare.com/ |

## list

| Reference | What to copy | Link |
|---|---|---|
| Things | The add control is dragged to the place the new item will go. Colour is reserved for meaning | https://culturedcode.com/things/ |
| Flighty | One departure-board line per item: the fact first, a status colour that always carries a text badge | https://flighty.com/ |

## detail

| Reference | What to copy | Link |
|---|---|---|
| Flighty | About fifteen time-and-place states shown plainly, and a next action anchored to a time ("Leave for airport by…") | https://flighty.com/ |
| grug (**to confirm**) | The 2026 Design Awards winner for delight: one daily item as a whole screen, in a distinctive drawn style. Copy the focus, not the scribble | https://apps.apple.com/us/app/grug/id6751649802 |

## settings

| Reference | What to copy | Link |
|---|---|---|
| Tiimo | A switch to remove the companion. A user left because the character "is all over the app" and wanted it off. Offer the same for anything decorative | https://www.tiimoapp.com/ |

## chat

| Reference | What to copy | Link |
|---|---|---|
| ChatGPT voice | A transcript drawer for the spoken exchange, so the conversation can be read after it was heard | https://openai.com/chatgpt/ |
| Finch | A companion character people keep opening. Keep it one tap away and not on every screen (the lesson of Tiimo's critics) | https://finchcare.com/ |

## voice

| Reference | What to copy | Link |
|---|---|---|
| ChatGPT voice | One pulsing orb is the whole screen. Speaking interrupts the answer. The transcript lives in a drawer, not on the main view | https://openai.com/chatgpt/ |

## timeline

| Reference | What to copy | Link |
|---|---|---|
| Structured | One timeline for tasks, events and habits. Downtime is planned as carefully as work. A 2026 Apple Design Awards finalist | https://apps.apple.com/us/app/structured-daily-planner-todo/id1499198946 |
| Tiimo | The same single timeline, with a companion character at the centre of the app. iPhone App of the Year 2025 | https://www.tiimoapp.com/ |
| Sunsama | Copy the planning ritual (a short guided sequence that ends in a day plan), not the phone UI | https://www.sunsama.com/ |
