---
lang: en
max_sentence_words: 20
max_post_chars:
  x_post: 280
  x_thread_tweet: 270
  substack_intro: 900
  video_hook_15s: 220
  linkedin_update: 900
emoji_max: 1
hashtags_max: 0
exclamations_max: 0
banned:
  - delve
  - comprehensive
  - robust
  - seamless*
  - leverag*
  - unlock*
  - game-changer
  - cutting-edge
  - it's important to note
  - i hope this helps
preferred:
  - "{{a word we like}}"
---
# Voice chart: {{product}} ({{language}})

One chart per language, in that language. Put the shared brief in `BRIEF.md`, copy this file to
`en.md`, `es.md` and `ru.md`, set `lang`, and write each from the brief. Never translate one chart
into another. The front matter above is the schema `teyla voice check <draft> --chart <dir>` enforces:

- `max_sentence_words`: the longest sentence. `max_post_chars`: characters per format (an X link counts 23).
- `emoji_max`, `hashtags_max`, `exclamations_max`: counts per draft. A missing key means no limit.
- `banned`: words and phrases, whole-word and case-insensitive; a trailing `*` matches any ending.
- `preferred`: words the chart wants; shown by the check, not enforced.

Delete the guidance lines when you are done. UI strings follow `DESIGN.md`, not this file.

## Brief
- What {{product}} is, in one sentence:
- Who it is for, per language:
- The one thing a reader should do after reading:
- Words we use for our own things (one word per thing, never rotated):

## Traits
Pick 3 or 4. Each is "We are X, not Y", with one do and one don't from real copy.

| We are | Not | Do | Don't |
|---|---|---|---|
| {{trait 1}} | {{opposite 1}} | "{{example}}" | "{{example}}" |
| {{trait 2}} | {{opposite 2}} | "{{example}}" | "{{example}}" |
| {{trait 3}} | {{opposite 3}} | "{{example}}" | "{{example}}" |

## Tone by channel
The traits stay the same. The register moves.

| Channel | Length | Tone | Rules |
|---|---|---|---|
| X / Twitter | {{max chars}} | {{tone}} | {{hook in the first line, hashtags, links}} |
| Instagram / TikTok script | {{seconds}} | {{tone}} | {{hook in 3 seconds, on-screen text, call to action}} |
| LinkedIn | {{words}} | {{tone}} | {{first-person or brand voice, how to open}} |
| App Store text | per store limits | {{tone}} | No model-provider names. Say what the app does in the first line. |
| Email | {{words}} | {{tone}} | {{subject length, one link, one ask}} |

## Languages
Write each language from the same brief, with a native-level writer or model.

### English
- Differs in: {{contractions, humor, formality, spelling variant (US or UK)}}
- Reference: plain-language guidance (plainlanguage.gov) and ASD-STE100 for short sentences.

### Spanish
- Differs in: {{tu or usted, Spain or Latin America, inclusive forms, opening marks}}
- Reference: the RAE/ASALE "Guia panhispanica de lenguaje claro". Pick one regional variety per campaign.

### Russian
- Differs in: {{ty or vy, how direct to be, how much to explain, handling of foreign terms}}
- Reference: Maxim Ilyakhov's "info-style" and the Glavred checker (glvrd.ru) for filler and stock
  phrases. Facts first, no pressure.

## Samples
Six per language, all passing `teyla voice check`: an X post, a thread opener, a reply, a Substack
intro, a 15-second video hook, a LinkedIn update. Add them when the chart is done.

## Before posting
- [ ] `teyla voice check <draft> --chart <dir> --format <format>` passes. Add `--model` for an editor's read.
- [ ] The first line holds the point. One idea per post, one ask.
- [ ] Every claim has a number, a link or a screenshot.
- [ ] The text is written in its language from the brief, not translated.
- [ ] No private data, no unreleased feature, no model-provider name in store text.
- [ ] Read it aloud once. Cut every sentence you stumble on.
