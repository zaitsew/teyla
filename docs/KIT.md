# Brand kit, store shots, product reel and posts

`teyla kit`, `teyla reel product` and `teyla post` make one product's visuals and posts from files the product
already has. The concept is `docs/STUDIO.md` 5.6 and decision S10. Nothing here publishes: the owner approves and
posts by hand.

## Quick start

```
teyla kit init <repo>          # brand/kit.toml, the folders, name and tokens filled from DESIGN.md
$EDITOR <repo>/brand/kit.toml  # taglines, the 60-word character sheet, references, channels
teyla kit check <repo>         # FIX lines until the kit is whole
teyla kit shots <repo>         # store screenshots from design/shots and docs/store/captions.json
teyla reel product <repo> --input demo.mov --copy copy.json
teyla post draft <repo> --channel x --event "Version 1.2 adds a weekly view"
```

`kit shots` and `reel product` need Pillow, and `reel product` needs ffmpeg:
`uv tool install --force --python 3.12 --with pillow git+https://github.com/zaitsew/teyla` and `brew install ffmpeg`.
Without Pillow the command prints that line and stops.

## The kit: `brand/kit.toml`

One file, one canonical character per product. `templates/brand/kit.toml` is the template; `{{...}}` marks
what you fill.

| section | holds |
|---|---|
| `[product]` | `name`, `promise` (one line: what it does for whom) |
| `[tagline]` | `en`, `es`, `ru`, each written in its language, never translated |
| `[tokens]` | `path`: the design-token source the visuals take colours from |
| `[shots]` | `background`, `text`, `accent`: the frame around a store screenshot |
| `[mascot]` | `name`, `sheet` (about 60 words, 40 to 80 accepted), `refs` (`brand/mascot/ref-*.png`), `model`, and `[mascot.settings]` (locked: aspect ratio, temperature, quality, `refs_max`) |
| `[icon]` | `source`: the 1024 px source of every store icon |
| `[voice]` | `chart`: a directory with `en.md`, `es.md`, `ru.md` (`templates/voice/VOICE.md`) |
| `[channels.<name>]` | `media`, `ratio`, `max_chars`, `per_week` for `x`, `instagram`, `tiktok`, `threads`, `youtube` |
| `[banned]` | `words`: no tagline, post or character sheet may use them (`*` ends a stem) |
| `[[provenance]]` | one entry per file under `brand/` that a person or a model made: `asset`, `made_by` (`model: <id>` or `human: <name>`), `prompt`, `references`, `date` |
| `[[comparison]]` | written by `kit compare`: date, scene, models, poses, cost, folder, `picked` (you fill it) |

### What `teyla kit check` fails

`FIX` makes the exit status 1; `WARN` does not.

- A `{{` placeholder is left, a tagline is empty, or `[tokens].path` or the icon source does not exist.
- The mascot has no name, a sheet outside 40 to 80 words, no reference image, a reference that is not on disk, an
  unknown model or no locked settings.
- A voice chart is missing a language or has no front matter (checked with the same loader as `teyla voice check`).
- A channel is unknown, or `[banned].words` is empty, or the kit's own text uses a banned word.
- A file under `brand/` (images, video, audio, fonts, PDFs) has no `[[provenance]]` entry, or an entry has no
  `made_by`, no date, or no prompt for a model.
- There is more than one character: a `[[mascot]]` list, a `[mascot_*]` or `[character*]` table, or a second
  reference folder under `brand/mascot/`.
- `WARN`: no comparison recorded for the locked model, fewer than three sample posts in `brand/posts/samples/`,
  provenance for a file that is gone, an unknown key.

Files cut from other assets need no provenance of their own: `brand/out/store/`, `brand/out/reel/` and
`brand/out/compare/`. `brand/out/.gitignore` keeps those three out of git.

## Store screenshots: `teyla kit shots`

```
teyla kit shots <repo> [--lang en,es] [--look light|dark|large] [--sizes iphone-6.9,iphone-6.5,ipad-13]
                [--captions FILE] [--shots-dir DIR] [--font PATH] [--dry]
```

It frames the matrix captures `design/shots/<lang>-<look>/<route>.<state>.png` (`docs/STUDIO.md` 5.2) with the
captions of `docs/store/captions.json` and writes `brand/out/store/<lang>/<size>/NN-<screen>.png`. Sizes are
1320x2868, 1284x2778 and 2064x2752. The captions file is `{"<route>.<state>": {"en": "...", "es": "..."}}` or
`{"en": {"<route>.<state>": "..."}}`; keys that start with `_` are notes. A language with a caption but no
capture is reported and gets no files: a store set is whole or not written. `--dry` lists what would be written.

## Mascot images: `kit image` and `kit compare`

These two commands are the only ones that cost money. Both print the price first.

```
teyla kit image <repo> "<scene>" [--model nano-banana-2.1|gpt-image-2] [--dry] [--yes] [--allow-network]
teyla kit compare <repo> "<scene>" [--models a,b] [--poses 10] [--yes] [--allow-network]
```

- `image` builds the prompt from the character sheet, the scene and the reference images, prints the price and
  stops with exit 2 unless `--yes` is given. It writes `brand/out/mascot/<date>-<slug>.png`, a `.txt` with the
  model, price, references and prompt, and appends the `[[provenance]]` entry. `--dry` prints the prompt.
- `compare` runs one scene in up to ten poses on up to two models and writes a contact sheet,
  `brand/out/compare/<date>-<slug>/contact.png`, and a `[[comparison]]` record. Without `--yes` it prints the plan and
  a `prices:` line and exits 0. Pick the model, then set `picked` and lock `mascot.model`.
- Prices: Nano Banana 2.1 is $0.0336 an image (exact). gpt-image-2 is billed by output tokens, so the figure is an
  estimate (about $0.0317 a medium image) and is printed with a `~`.
- Keys: `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) and `OPENAI_API_KEY` in the environment, else the macOS Keychain
  items `gemini-api-key` and `openai-api-key`. A key is never printed or written.
- The Gemini API model id is `gemini-3.1-flash-image`. It was not checked against a live call; set
  `TEYLA_KIT_GEMINI_MODEL` (or `api_model` in `[mascot.settings]`) if the API names it otherwise.
- Safe mode refuses both commands; `--allow-network` allows one call by hand. `docs/PRIVACY.md` rows 27 and 28 list
  what is sent: the prompt and the reference images.

## Product reel: `teyla reel product`

```
teyla reel product <repo> [--input movie.mov] [--copy copy.json] [--control caption] [--lang en,es,ru]
                   [--formats vertical,square] [--voice [--script voiceover.json]] [--yes] [-o DIR] [--dry]
```

It cuts a recording of the app itself (a simulator recording, `xcrun simctl io booted recordVideo demo.mov`, or
a phone capture) with captions. Without `--input` it takes the newest file in `brand/recordings/`. Per language it
writes `brand/out/reel/<lang>/product-vertical.mp4` (1080x1920), `product-square.mp4` (1080x1080) and
`captions.srt`.

- Captions: the rows of a copy table whose `control` is `caption` (the lane E format: rows with
  `key, control, state, budget, en, es, ru`), or a plain file `{"en": ["line", ...]}` where a line may be
  `{"text": "...", "start": 0.5, "end": 3.0}`. Untimed captions share the video's length equally.
- Every caption passes `teyla reel` redaction (secrets, private terms, addresses, paths); one that does not stops
  the run before anything is rendered. Pillow draws each caption into a transparent PNG and ffmpeg overlays it.
- `--voice` reads the script aloud with the OpenAI speech API (`tts-1`, $15 per million characters; `tts-1-hd`
  $30). The script is `--script` (`{"en": "text"}`) or the captions in order. The price is printed first; the
  command exits 2 without `--yes`. A voice-over longer than the recording holds the last frame.
- Exit 1: Pillow or ffmpeg is missing, ffmpeg failed, or one language failed. `--dry` prints the plan.

## Posts: `teyla post`

```
teyla post draft <repo> --channel x|instagram|tiktok|threads|youtube [--event "<what shipped>"]
                 [--text TEXT | --file FILE] [--lang en|es|ru] [--slug S] [--dry]
teyla post pack  <repo> [--event "<what shipped>"] [--week YYYY-Www] [--channels x,instagram,threads]
```

`draft` takes the post from `--text` or `--file`. Without them, and in English only, it builds a scaffold from the
event, the kit's promise and its tagline: a starting point to rewrite. It runs the same checks as
`teyla voice check` against `brand/voice/<lang>.md`, then the channel's own limit (x 280, threads 500, instagram
2200, tiktok 2200, youtube 5000). TikTok and YouTube also check the first sentence as a 15-second hook, and a
YouTube title is that sentence, at most 100 characters. A draft that fails is printed with its findings and not
written (exit 1). A pass writes `brand/posts/queue/<date>-<channel>-<slug>.md` (`-es` or `-ru` is added), with front
matter and `status: draft`.

`pack` writes `brand/posts/packs/<year>-W<week>.md`, the weekly flagship pack: one reel, one screenshot set and
three posts, as a checklist. Items done on disk are ticked when the file is written, and a tick you made by hand
stays. There is no posting API: the owner reads the pack and posts from the queue by hand.

## Open decisions this lane took

- `compare` without `--yes` exits 0 (it is a plan); `image` without `--yes` exits 2 (it asked for a charge).
- A failing post draft is not written; its text is printed so it can be fixed.
- The scaffold is English only; Spanish and Russian posts come from a brief, never a translation.
- gpt-image-2 has no flat price, so its figure is an estimate and says so.
