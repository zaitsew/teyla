"""`teyla kit` — a product's brand kit as a folder: `brand/kit.toml`, the mascot, the icon, the voice charts.

    teyla kit init [repo] [--force]
    teyla kit check [repo] [--json]
    teyla kit shots [repo] [--lang en,es] [--look light|dark|large] [--sizes S,...] [--captions FILE] [--font PATH] [--dry]
    teyla kit image <repo> "<scene>" [--model M] [--yes] [--dry]
    teyla kit compare <repo> "<scene>" [--models a,b] [--poses 10] [--yes]

`init` copies `templates/brand/kit.toml` to `brand/kit.toml`, fills what `DESIGN.md` already says (the
product's name and its token source) and creates the folders. `check` fails a kit with a placeholder left, a
missing piece, an asset under `brand/` without a provenance entry, a banned word in the kit's own text, or two
characters. `shots` frames the matrix captures into the store sizes. `image` and `compare` are the only paid
commands: they print the price first and refuse without `--yes`. Docs: docs/KIT.md; the concept: docs/STUDIO.md 5.6.

Repos are chosen as in `teyla docs check`: none means the git root of the current directory, a bare name is looked
up under `code_root`, a path is used as it is.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

from . import genai, kitdraw, voice

KIT = "brand/kit.toml"
FIX, WARN = "FIX", "WARN"
VOICE_DIR = "brand/voice"

# Channel defaults: the limit the channel enforces, used when the kit names none.
CHANNELS = {
    "x": dict(max_chars=280, media=("none", "image", "video")),
    "instagram": dict(max_chars=2200, media=("image", "video")),
    "tiktok": dict(max_chars=2200, media=("video",)),
    "threads": dict(max_chars=500, media=("none", "image", "video")),
    "youtube": dict(max_chars=5000, media=("video",)),
}

STORE_SIZES = {"iphone-6.9": (1320, 2868), "iphone-6.5": (1284, 2778), "ipad-13": (2064, 2752)}
LOOKS = ("light", "dark", "large")

ASSET_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".pdf", ".mp4", ".mov", ".mp3", ".wav", ".m4a", ".ttf", ".otf"}
# Files these commands cut from other assets. They carry no provenance entry of their own: the captures,
# the recording and the comparison record are where they come from.
DERIVED = ("brand/out/store/", "brand/out/reel/", "brand/out/compare/")

SHEET_WORDS = (40, 80)          # "a 60-word character sheet"
POSES = ("standing and facing the viewer", "waving", "walking", "sitting", "jumping with joy", "looking up",
         "holding a blank sign", "thinking with a hand on the chin", "celebrating", "sleeping")
MAX_COMPARE_MODELS, MAX_COMPARE_POSES = 2, 10

# Top-level keys the kit knows. A key that starts with mascot or character and is not `mascot` is a second character.
KNOWN_KEYS = {"version", "product", "tagline", "tokens", "shots", "mascot", "icon", "voice", "channels", "banned",
              "provenance", "comparison"}


class KitError(Exception):
    """The kit cannot be read or a command cannot run; the message says what to fix."""


# --- the repo and the file ---------------------------------------------------------------------

def resolve_repo(arg: str | None) -> Path:
    from . import docs_check
    try:
        return docs_check.resolve([arg] if arg else [], False)[0].resolve()
    except FileNotFoundError as e:
        raise KitError(str(e)) from None


def load(repo: Path) -> dict:
    p = repo / KIT
    if not p.is_file():
        raise KitError(f"no {KIT} in {repo}: run `teyla kit init {repo.name}`")
    try:
        return tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise KitError(f"{p}: {e}") from None


def _toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _append(repo: Path, block: str) -> None:
    p = repo / KIT
    text = p.read_text(encoding="utf-8") if p.is_file() else ""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text + ("" if text.endswith("\n") or not text else "\n") + "\n" + block.rstrip("\n") + "\n", encoding="utf-8")


def append_provenance(repo: Path, asset: str, made_by: str, prompt: str, references: list[str], date: str) -> None:
    """One `[[provenance]]` entry at the end of the kit: who or which model made `asset`, from what."""
    _append(repo, "[[provenance]]\n"
                  f"asset = {_toml_str(asset)}\nmade_by = {_toml_str(made_by)}\nprompt = {_toml_str(' '.join(prompt.split()))}\n"
                  f"references = [{', '.join(_toml_str(r) for r in references)}]\ndate = {_toml_str(date)}")


def append_comparison(repo: Path, record: dict) -> None:
    """The bounded comparison, recorded in the kit; `picked` stays empty until the owner chooses."""
    _append(repo, "[[comparison]]\n"
                  f"date = {_toml_str(record['date'])}\nscene = {_toml_str(record['scene'])}\n"
                  f"models = [{', '.join(_toml_str(m) for m in record['models'])}]\nposes = {record['poses']}\n"
                  f"cost_usd = {record['cost_usd']:.4f}\nfolder = {_toml_str(record['folder'])}\npicked = \"\"")


# --- init -----------------------------------------------------------------------------------------

def design_hints(repo: Path) -> dict:
    """What DESIGN.md already says that the kit needs: the product's name and its token source."""
    out: dict = {}
    for cand in (repo / "DESIGN.md", repo / "docs" / "DESIGN.md"):
        if not cand.is_file():
            continue
        text = cand.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"(?m)^#\s*Design:\s*(.+?)\s*$", text)
        if m and "{{" not in m.group(1):
            out["name"] = m.group(1)
        m = re.search(r"(?m)^Source:\s*`([^`]+)`", text)
        if m and "{{" not in m.group(1):
            raw = m.group(1).strip()
            path = raw.split("*")[0].rstrip("/") if "*" in raw else raw
            path = path if (repo / path).exists() else str(Path(path).parent)
            if path and path != "." and (repo / path).exists():
                out["tokens"] = path
        break
    return out


def init(repo: Path, force: bool = False) -> tuple[list[str], dict]:
    """Create `brand/kit.toml` and the folders. Returns (paths created, what was filled)."""
    from . import templates_dir
    dest = repo / KIT
    if dest.exists() and not force:
        raise KitError(f"{KIT} exists; --force replaces it")
    text = (templates_dir() / "brand" / "kit.toml").read_text(encoding="utf-8")
    hints = design_hints(repo)
    filled: dict = {}
    if "name" in hints:
        text = text.replace('"{{product}}"', _toml_str(hints["name"]))
        filled["product.name"] = hints["name"]
    if "tokens" in hints:
        text = text.replace('"{{design/tokens}}"', _toml_str(hints["tokens"]))
        filled["tokens.path"] = hints["tokens"]
    refs = sorted(p.relative_to(repo).as_posix() for p in (repo / "brand" / "mascot").glob("ref-*.png")) \
        if (repo / "brand" / "mascot").is_dir() else []
    if refs:
        text = text.replace("refs = []", "refs = [" + ", ".join(_toml_str(r) for r in refs) + "]")
        filled["mascot.refs"] = f"{len(refs)} found"
    made = []
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    made.append(KIT)
    for d in ("brand/mascot", "brand/icon", VOICE_DIR, "brand/posts/queue", "brand/posts/samples"):
        p = repo / d
        if not p.is_dir():
            p.mkdir(parents=True)
            (p / ".gitkeep").write_text("", encoding="utf-8")
            made.append(d + "/")
    gi = repo / "brand" / "out" / ".gitignore"
    if not gi.exists():
        gi.parent.mkdir(parents=True, exist_ok=True)
        gi.write_text("# cut from the captures and recordings; the mascot images stay\nstore/\nreel/\ncompare/\n", encoding="utf-8")
        made.append("brand/out/.gitignore")
    return made, filled


# --- check ----------------------------------------------------------------------------------------

def assets(repo: Path) -> list[str]:
    """Repo-relative paths of the files under brand/ that need a provenance entry."""
    out = []
    base = repo / "brand"
    if not base.is_dir():
        return out
    for p in sorted(base.rglob("*")):
        rel = p.relative_to(repo).as_posix()
        if not p.is_file() or p.suffix.lower() not in ASSET_EXT or any(part.startswith(".") for part in p.relative_to(base).parts):
            continue
        if rel.startswith("brand/posts/") or any(rel.startswith(d) for d in DERIVED):
            continue
        out.append(rel)
    return out


def _placeholders(node, path="") -> list[str]:
    if isinstance(node, str):
        return [path] if "{{" in node else []
    if isinstance(node, dict):
        return [x for k, v in node.items() for x in _placeholders(v, f"{path}.{k}" if path else k)]
    if isinstance(node, list):
        return [x for i, v in enumerate(node) for x in _placeholders(v, f"{path}[{i}]")]
    return []


def _kit_texts(kit: dict) -> list[tuple[str, str]]:
    out = [("product.promise", str((kit.get("product") or {}).get("promise") or "")),
           ("mascot.sheet", str((kit.get("mascot") or {}).get("sheet") or "") if isinstance(kit.get("mascot"), dict) else "")]
    out += [(f"tagline.{k}", str(v)) for k, v in (kit.get("tagline") or {}).items()]
    return out


def check(repo: Path) -> dict:
    """{repo, verdict, findings[]}: every finding has check, severity, message, fix."""
    findings: list[dict] = []

    def add(sev, name, message, fix):
        findings.append(dict(check=name, severity=sev, message=message, fix=fix))

    try:
        kit = load(repo)
    except KitError as e:
        add(FIX, "kit", str(e), f"teyla kit init {repo.name}")
        return _report(repo, findings)

    left = _placeholders(kit)
    if left:
        add(FIX, "placeholders", "still a `{{...}}` placeholder: " + ", ".join(left[:8]) + (" ..." if len(left) > 8 else ""),
            f"fill each value in {KIT}")
    prod = kit.get("product") if isinstance(kit.get("product"), dict) else {}
    for key in ("name", "promise"):
        if not str(prod.get(key) or "").strip():
            add(FIX, "product", f"product.{key} is empty", f"write product.{key} in {KIT}")
    tag = kit.get("tagline") if isinstance(kit.get("tagline"), dict) else {}
    missing = [l for l in voice.LANGS if not str(tag.get(l) or "").strip()]
    if missing:
        add(FIX, "tagline", "no tagline in " + ", ".join(missing), "write one tagline per language, each from the brief, none translated")

    # tokens and icon
    tok = str((kit.get("tokens") or {}).get("path") or "")
    if not tok:
        add(FIX, "tokens", "tokens.path is empty", "point tokens.path at the DTCG token source")
    elif "{{" not in tok and not (repo / tok).exists():
        add(FIX, "tokens", f"tokens.path {tok} does not exist", "fix the path or generate the tokens")
    icon = str((kit.get("icon") or {}).get("source") or "")
    if not icon:
        add(FIX, "icon", "icon.source is empty", "point icon.source at the 1024 px source file")
    elif not (repo / icon).is_file():
        add(FIX, "icon", f"icon.source {icon} does not exist", "add the icon source under brand/icon/")

    _check_mascot(repo, kit, add)

    # voice charts
    chart = str((kit.get("voice") or {}).get("chart") or "")
    if not chart:
        add(FIX, "voice", "voice.chart is empty", f"set voice.chart = \"{VOICE_DIR}\"")
    elif not (repo / chart).is_dir():
        add(FIX, "voice", f"voice.chart {chart} is not a directory", "write en.md, es.md and ru.md there from templates/voice/VOICE.md")
    else:
        for l in voice.LANGS:
            f = repo / chart / f"{l}.md"
            if not f.is_file():
                add(FIX, "voice", f"{chart}/{l}.md is missing", "write the chart in that language, from the brief, never translated")
                continue
            try:
                voice.load_chart(f)
            except voice.ChartError as e:
                add(FIX, "voice", f"{chart}/{l}.md: {e}", "fix the front matter (templates/voice/VOICE.md is the schema)")

    # channels
    chans = kit.get("channels") if isinstance(kit.get("channels"), dict) else {}
    if not chans:
        add(FIX, "channels", "no [channels.*] table", "add one table per channel: x, instagram, tiktok, threads or youtube")
    for name, c in chans.items():
        if name not in CHANNELS:
            add(FIX, "channels", f"unknown channel {name!r}", "use x, instagram, tiktok, threads or youtube")
            continue
        c = c if isinstance(c, dict) else {}
        if not isinstance(c.get("max_chars"), int) or isinstance(c.get("max_chars"), bool) or c["max_chars"] < 1:
            add(WARN, "channels", f"channels.{name}.max_chars is not set", f"set it (the channel's limit is {CHANNELS[name]['max_chars']})")
        if c.get("media") not in CHANNELS[name]["media"]:
            add(WARN, "channels", f"channels.{name}.media is {c.get('media')!r}", "use one of " + ", ".join(CHANNELS[name]["media"]))

    # banned list, and the kit's own text against it
    banned = (kit.get("banned") or {}).get("words") if isinstance(kit.get("banned"), dict) else None
    if not isinstance(banned, list) or not [w for w in banned if str(w).strip()]:
        add(FIX, "banned", "the banned list is empty", "list the words the product never uses under [banned] words")
    else:
        for where, text in _kit_texts(kit):
            for h in voice.banned_hits(text, [str(w) for w in banned]):
                add(FIX, "banned", f"{where} uses the banned word \"{h['phrase']}\"", "reword it")

    for key in kit:
        if key not in KNOWN_KEYS and not re.match(r"(?:mascot|character)", key):
            add(WARN, "kit", f"unknown key {key!r}", "remove it or fix the spelling")

    _check_provenance(repo, kit, add)

    samples = repo / "brand" / "posts" / "samples"
    n = len(list(samples.glob("*.md"))) if samples.is_dir() else 0
    if n < 3:
        add(WARN, "samples", f"{n} sample post(s) in brand/posts/samples/", "add three posts that sound like the product (docs/STUDIO.md S10)")
    return _report(repo, findings)


def _check_mascot(repo: Path, kit: dict, add) -> None:
    extra = [k for k in kit if k != "mascot" and re.match(r"(?:mascot|character)", k)]
    m = kit.get("mascot")
    if isinstance(m, list) or extra:
        add(FIX, "characters", "more than one character: " + (", ".join(extra) if extra else "[[mascot]] is a list"),
            "keep one canonical character; the others become its scenes or go")
        if not isinstance(m, dict):
            return
    if not isinstance(m, dict):
        add(FIX, "mascot", "no [mascot] table", "add one: name, sheet, refs, model, settings")
        return
    if not str(m.get("name") or "").strip():
        add(FIX, "mascot", "mascot.name is empty", "name the character")
    words = len(str(m.get("sheet") or "").split())
    if not (SHEET_WORDS[0] <= words <= SHEET_WORDS[1]):
        add(FIX, "mascot", f"the character sheet is {words} words, not about 60 ({SHEET_WORDS[0]} to {SHEET_WORDS[1]})",
            "write what an image model needs to keep the character the same")
    refs = m.get("refs") if isinstance(m.get("refs"), list) else []
    if not refs:
        add(FIX, "mascot", "mascot.refs lists no reference image", "add brand/mascot/ref-*.png and list them")
    for r in refs:
        if not (repo / str(r)).is_file():
            add(FIX, "mascot", f"reference image {r} does not exist", "add the file or drop it from mascot.refs")
        elif not re.fullmatch(r"brand/mascot/ref-[^/]+\.(?:png|jpe?g|webp)", str(r)):
            add(WARN, "mascot", f"reference image {r} is not named brand/mascot/ref-*", "rename it")
    folder = repo / "brand" / "mascot"
    unlisted = sorted(p.relative_to(repo).as_posix() for p in folder.glob("ref-*") if p.relative_to(repo).as_posix() not in refs) \
        if folder.is_dir() else []
    if unlisted:
        add(WARN, "mascot", "reference images not in mascot.refs: " + ", " .join(unlisted[:4]), "list them or remove them")
    others = sorted(d.name for d in folder.iterdir() if d.is_dir() and any(d.glob("ref-*"))) if folder.is_dir() else []
    if others:
        add(FIX, "characters", "reference images in a second folder: " + ", ".join(others), "one character, one folder")
    model = m.get("model")
    if model not in genai.IMAGE_MODELS:
        add(FIX, "mascot", f"mascot.model is {model!r}", "lock one of " + ", ".join(genai.IMAGE_MODELS))
    if not isinstance(m.get("settings"), dict) or not m["settings"]:
        add(FIX, "mascot", "the model settings are not locked", "add [mascot.settings] (aspect_ratio, temperature, ...)")
    if model in genai.IMAGE_MODELS and not kit.get("comparison"):
        add(WARN, "mascot", "no comparison is recorded for the locked model",
            "run `teyla kit compare` once before the lock (ten poses, two models), then pick")


def _check_provenance(repo: Path, kit: dict, add) -> None:
    entries = kit.get("provenance") if isinstance(kit.get("provenance"), list) else []
    seen: dict[str, dict] = {}
    for i, e in enumerate(entries, 1):
        if not isinstance(e, dict) or not str(e.get("asset") or "").strip():
            add(FIX, "provenance", f"provenance entry {i} names no asset", "set `asset`")
            continue
        a = e["asset"]
        seen[a] = e
        made = str(e.get("made_by") or "")
        if not re.match(r"(?:model|human):\s*\S", made):
            add(FIX, "provenance", f"{a}: made_by must read `model: <name>` or `human: <name>`", f"fix the entry for {a}")
        if made.startswith("model:") and not str(e.get("prompt") or "").strip():
            add(FIX, "provenance", f"{a}: a model made it, but the prompt is empty", "record the prompt")
        if not isinstance(e.get("references"), list):
            add(FIX, "provenance", f"{a}: `references` is not a list", "use references = [] when there are none")
        try:
            _dt.date.fromisoformat(str(e.get("date")))
        except ValueError:
            add(FIX, "provenance", f"{a}: date {e.get('date')!r} is not YYYY-MM-DD", "write the date")
        if not (repo / a).is_file():
            add(WARN, "provenance", f"{a}: the file is gone", "remove the entry if the asset was deleted on purpose")
    for a in assets(repo):
        if a not in seen:
            add(FIX, "provenance", f"{a}: no provenance entry", f"add a [[provenance]] entry for {a}: who or which model made it, the prompt, the references, the date")


def _report(repo: Path, findings: list[dict]) -> dict:
    verdict = FIX if any(f["severity"] == FIX for f in findings) else WARN if findings else "OK"
    return dict(repo=repo.name, path=str(repo), verdict=verdict, findings=findings)


def render_check(rep: dict) -> str:
    if not rep["findings"]:
        return f"{rep['repo']}: kit ok"
    L = [f"{rep['repo']}: kit {rep['verdict']}"]
    for f in rep["findings"]:
        L.append(f"  {f['severity']:<4} {f['check']:<12} {f['message']}")
        L.append(f"       fix: {f['fix']}")
    nfix = sum(f["severity"] == FIX for f in rep["findings"])
    L.append(f"{nfix} FIX, {len(rep['findings']) - nfix} WARN")
    return "\n".join(L)


# --- store screenshots ------------------------------------------------------------------------------

def load_captions(path: Path) -> dict[str, list[tuple[str, str]]]:
    """{lang: [(screen, caption)]} in the file's order, from `docs/store/captions.json`. Two shapes:
    {"<route>.<state>": {"en": "...", "es": "..."}} or {"en": {"<route>.<state>": "..."}}. Keys that start
    with an underscore are notes."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise KitError(f"cannot read the captions {path}: {e}") from None
    if not isinstance(data, dict):
        raise KitError(f"{path}: expected a JSON object")
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    out: dict[str, list[tuple[str, str]]] = {}
    if data and all(k in voice.LANGS and isinstance(v, dict) for k, v in data.items()):
        for lang, rows in data.items():
            out[lang] = [(s, str(t)) for s, t in rows.items() if str(t).strip()]
        return out
    for screen, per in data.items():
        if not isinstance(per, dict):
            raise KitError(f"{path}: {screen!r} must map a language to a caption")
        for lang, text in per.items():
            if lang in voice.LANGS and str(text).strip():
                out.setdefault(lang, []).append((screen, str(text)))
    return out


def _slug(s: str, fallback: str = "x") -> str:
    out = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return out[:48].strip("-") or fallback


def render_store_shot(shot_path: Path, caption: str, size: tuple, style: dict, font_path: str | None = None):
    """One framed store screenshot as an RGB Pillow image: a caption band on top, the capture in a plain
    rounded frame below it."""
    Image, ImageDraw, _ = kitdraw.pillow()
    W, H = size
    bg, fg, accent = (kitdraw.hex_rgb(style.get(k, d), c) for k, d, c in
                      (("background", "#1F2937", (31, 41, 55)), ("text", "#FFFFFF", (255, 255, 255)), ("accent", "#7C9CFF", (124, 156, 255))))
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)
    getfont = kitdraw.find_font(font_path or style.get("font") or None)
    margin = int(W * 0.08)
    band = int(H * 0.19)
    font, lines, fsize = kitdraw.fit_text(draw, caption, getfont, W - 2 * margin, 3, int(W * 0.075), int(W * 0.04))
    lh = int(fsize * 1.2)
    y = max(int(H * 0.02), (band - lh * len(lines)) // 2)
    for line in lines[:3]:
        draw.text(((W - draw.textlength(line, font=font)) / 2, y), line, font=font, fill=fg)
        y += lh
    with Image.open(shot_path) as raw:
        sw, sh = raw.size
        top = band + int(H * 0.02)
        area_w, area_h = W - 2 * margin, H - top - int(H * 0.04)
        scale = min(area_w / sw, area_h / sh)
        w, h = max(1, int(sw * scale)), max(1, int(sh * scale))
        screen = kitdraw.rounded_screen(Image, ImageDraw, raw, (w, h), max(4, int(w * 0.07)))
    x = (W - w) // 2
    bezel = max(4, int(w * 0.025))
    draw.rounded_rectangle((x - bezel, top - bezel, x + w + bezel, top + h + bezel), radius=int(w * 0.07) + bezel,
                           fill=(12, 12, 14), outline=accent, width=max(2, bezel // 3))
    img.paste(screen, (x, top), screen)
    return img


def plan_shots(repo: Path, captions: dict, langs: list[str], look: str, shots_dir: Path) -> tuple[list[dict], list[str]]:
    """(jobs, problems). A job is {lang, index, screen, caption, src}. A language with a caption but no capture
    is a problem and gets no jobs: a store set is whole or not written."""
    jobs, problems = [], []
    for lang in langs:
        rows = captions.get(lang)
        if not rows:
            problems.append(f"{lang}: no captions in the captions file")
            continue
        variant = shots_dir / f"{lang}-{look}"
        miss = [s for s, _ in rows if not (variant / f"{s}.png").is_file()]
        if miss:
            problems.append(f"{lang}: no capture in {variant.relative_to(repo) if variant.is_relative_to(repo) else variant} for " + ", ".join(miss))
            continue
        for i, (screen, text) in enumerate(rows, 1):
            jobs.append(dict(lang=lang, index=i, screen=screen, caption=text, src=variant / f"{screen}.png"))
    return jobs, problems


def cmd_shots(args) -> int:
    try:
        repo = resolve_repo(args.repo)
        kit = load(repo)
        cap_path = Path(args.captions).expanduser() if args.captions else repo / "docs" / "store" / "captions.json"
        captions = load_captions(cap_path)
        sizes = [s.strip() for s in args.sizes.split(",")] if args.sizes else list(STORE_SIZES)
        bad = [s for s in sizes if s not in STORE_SIZES]
        if bad:
            raise KitError(f"unknown size {', '.join(bad)} (known: {', '.join(STORE_SIZES)})")
        langs = [l.strip() for l in args.lang.split(",")] if args.lang else sorted(captions)
        unk = [l for l in langs if l not in voice.LANGS]
        if unk:
            raise KitError(f"unknown language {', '.join(unk)} (known: {', '.join(voice.LANGS)})")
    except KitError as e:
        print(f"teyla kit shots: {e}", file=sys.stderr)
        return 2
    shots_dir = Path(args.shots_dir).expanduser() if args.shots_dir else repo / "design" / "shots"
    jobs, problems = plan_shots(repo, captions, langs, args.look, shots_dir)
    n = len(jobs) * len(sizes)
    print(f"kit shots: {len(jobs)} screen(s) x {len(sizes)} size(s) = {n} file(s), look {args.look}, languages {', '.join(langs)}")
    for p in problems:
        print(f"  skipped  {p}", file=sys.stderr)
    if args.dry or not jobs:
        for j in jobs:
            print(f"  {j['lang']}  {j['index']:02d}  {j['screen']}  \"{j['caption']}\"")
        return 1 if problems else 0
    try:
        kitdraw.pillow()
    except kitdraw.Missing as e:
        print(f"teyla kit shots: {e}", file=sys.stderr)
        return 1
    style = kit.get("shots") if isinstance(kit.get("shots"), dict) else {}
    written = 0
    for j in jobs:
        for sid in sizes:
            out = repo / "brand" / "out" / "store" / j["lang"] / sid / f"{j['index']:02d}-{j['screen'].replace('.', '-')}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            render_store_shot(j["src"], j["caption"], STORE_SIZES[sid], style, args.font).save(out)
            written += 1
    print(f"wrote {written} file(s) under {(repo / 'brand' / 'out' / 'store').relative_to(repo)}/<lang>/<size>/")
    return 1 if problems else 0


# --- mascot images ----------------------------------------------------------------------------------

def mascot_prompt(kit: dict, scene: str) -> str:
    m = kit["mascot"]
    return (f"Create one image of the character {m['name']}. Character sheet: {' '.join(str(m['sheet']).split())}\n"
            "The attached reference images show this same character. Keep its shape, colours, face and proportions "
            "exactly as in the references.\n"
            f"Scene: {scene.strip()}\n"
            "One character only. No text, no logo, no watermark.")


def _mascot_ready(repo: Path, kit: dict) -> dict:
    m = kit.get("mascot")
    if not isinstance(m, dict):
        raise KitError(f"{KIT} has no [mascot] table: run `teyla kit check {repo.name}`")
    if "{{" in json.dumps(m, ensure_ascii=False) or not str(m.get("name") or "").strip() or not str(m.get("sheet") or "").strip():
        raise KitError("the mascot's name or character sheet is not filled in: run `teyla kit check`")
    refs = [repo / str(r) for r in (m.get("refs") or [])]
    gone = [r.name for r in refs if not r.is_file()]
    if not refs or gone:
        raise KitError("the reference images are missing" + (": " + ", ".join(gone) if gone else " (mascot.refs is empty)"))
    return m


def _settings(m: dict) -> dict:
    return dict(m.get("settings") or {}) if isinstance(m.get("settings"), dict) else {}


def _refs(repo: Path, m: dict) -> list[Path]:
    cap = _settings(m).get("refs_max")
    refs = [repo / str(r) for r in m.get("refs") or []]
    return refs[:cap] if isinstance(cap, int) and cap > 0 else refs[:6]


def _need_network(what: str) -> bool:
    from . import net
    return net.gate(what)


def cmd_image(args) -> int:
    try:
        repo = resolve_repo(args.repo)
        kit = load(repo)
        m = _mascot_ready(repo, kit)
        model = args.model or m.get("model") or genai.DEFAULT_IMAGE_MODEL
        settings = _settings(m)
        usd, exact = genai.image_price(model, settings)
    except (KitError, genai.GenError) as e:
        print(f"teyla kit image: {e}", file=sys.stderr)
        return 2
    refs = _refs(repo, m)
    prompt = mascot_prompt(kit, args.scene)
    print(f"kit image: {genai.IMAGE_MODELS[model]['label']}, 1 image, {genai.money(usd, exact)}"
          + ("" if exact else " (estimate from output tokens, input excluded)") + f", {len(refs)} reference image(s)")
    print(f"  scene: {args.scene.strip()}")
    if args.dry:
        print("\n" + prompt)
        return 0
    if not args.yes:
        print("teyla kit image: this call costs money; run it again with --yes to confirm the price above", file=sys.stderr)
        return 2
    if not _need_network("kit image"):
        return 2
    today = _dt.date.today().isoformat()
    try:
        png = genai.generate_image(model, prompt, refs, settings)
    except genai.GenError as e:
        print(f"teyla kit image: {e}", file=sys.stderr)
        return 1
    out = _unique(repo / "brand" / "out" / "mascot", f"{today}-{_slug(args.scene, _hash(args.scene))}", ".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png)
    ref_rel = [r.relative_to(repo).as_posix() for r in refs]
    out.with_suffix(".txt").write_text(
        f"model: {model}\nprice_usd: {usd:.4f}{'' if exact else ' (estimate)'}\ndate: {today}\nsettings: {json.dumps(settings, sort_keys=True)}\n"
        "references:\n" + "".join(f"- {r}\n" for r in ref_rel) + f"\nprompt:\n{prompt}\n", encoding="utf-8")
    rel = out.relative_to(repo).as_posix()
    append_provenance(repo, rel, f"model: {model}", prompt, ref_rel, today)
    print(f"wrote {rel} and {out.with_suffix('.txt').relative_to(repo).as_posix()}; provenance added to {KIT}")
    return 0


def _hash(s: str) -> str:
    return "scene-" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:6]


def _unique(folder: Path, stem: str, ext: str) -> Path:
    p = folder / (stem + ext)
    n = 2
    while p.exists() or p.with_suffix(".txt").exists():
        p = folder / f"{stem}-{n}{ext}"
        n += 1
    return p


def compare_plan(kit: dict, models: list[str], poses: int, settings: dict) -> dict:
    per = {}
    for mod in models:
        usd, exact = genai.image_price(mod, settings)
        per[mod] = dict(unit=usd, exact=exact, total=usd * poses)
    total = sum(v["total"] for v in per.values())
    line = "prices: " + "; ".join(f"{mod} {poses} x {genai.money(v['unit'], v['exact'])} = {genai.money(v['total'], v['exact'])}"
                                  for mod, v in per.items()) + f"; total {genai.money(total, all(v['exact'] for v in per.values()))}"
    return dict(per=per, total=total, line=line)


def cmd_compare(args) -> int:
    try:
        repo = resolve_repo(args.repo)
        kit = load(repo)
        m = _mascot_ready(repo, kit)
        models = [x.strip() for x in args.models.split(",") if x.strip()] if args.models else \
            list(dict.fromkeys([m.get("model") or genai.DEFAULT_IMAGE_MODEL, *genai.IMAGE_MODELS]))[:MAX_COMPARE_MODELS]
        if len(models) != len(set(models)) or not (1 <= len(models) <= MAX_COMPARE_MODELS):
            raise KitError(f"the comparison takes one or two different models (at most {MAX_COMPARE_MODELS})")
        for mod in models:
            if mod not in genai.IMAGE_MODELS:
                raise KitError(f"unknown image model {mod!r} (known: {', '.join(genai.IMAGE_MODELS)})")
        if not (1 <= args.poses <= MAX_COMPARE_POSES):
            raise KitError(f"--poses is 1 to {MAX_COMPARE_POSES}")
        settings = _settings(m)
        plan = compare_plan(kit, models, args.poses, settings)
    except (KitError, genai.GenError) as e:
        print(f"teyla kit compare: {e}", file=sys.stderr)
        return 2
    poses = POSES[:args.poses]
    print(f"kit compare: {len(models)} model(s) x {len(poses)} pose(s) = {len(models) * len(poses)} image(s), scene: {args.scene.strip()}")
    for i, p in enumerate(poses, 1):
        print(f"  pose {i:02d}  {p}")
    print(plan["line"])
    if not args.yes:
        print("plan only: nothing was called. Add --yes to run it and pay the total above.")
        return 0
    if not _need_network("kit compare"):
        return 2
    today = _dt.date.today().isoformat()
    folder = repo / "brand" / "out" / "compare" / f"{today}-{_slug(args.scene, _hash(args.scene))}"
    base, n = folder, 2
    while folder.exists():
        folder = base.with_name(f"{base.name}-{n}")
        n += 1
    refs = _refs(repo, m)
    cells: dict[tuple[str, int], Path] = {}
    failed = []
    spent = 0.0
    for mod in models:
        (folder / mod).mkdir(parents=True, exist_ok=True)
        for i, pose in enumerate(poses, 1):
            prompt = mascot_prompt(kit, f"{args.scene.strip()} The character is {pose}.")
            try:
                png = genai.generate_image(mod, prompt, refs, settings)
            except genai.GenError as e:
                failed.append(f"{mod} pose {i}: {e}")
                continue
            dest = folder / mod / f"{i:02d}-{_slug(pose)}.png"
            dest.write_bytes(png)
            cells[(mod, i)] = dest
            spent += plan["per"][mod]["unit"]
    sheet_note = ""
    try:
        sheet = contact_sheet(cells, models, len(poses))
        sheet.save(folder / "contact.png")
        sheet_note = "contact.png"
    except kitdraw.Missing as e:
        sheet_note = f"no contact sheet: {e}"
    rel = folder.relative_to(repo).as_posix()
    (folder / "compare.txt").write_text(
        f"scene: {args.scene.strip()}\nmodels: {', '.join(models)}\nposes: {len(poses)}\ndate: {today}\n{plan['line']}\n"
        f"charged for {len(cells)} image(s): {genai.money(spent, False)}\n" + "".join(f"failed: {f}\n" for f in failed)
        + "\nposes:\n" + "".join(f"{i:02d} {p}\n" for i, p in enumerate(poses, 1)) + "\nprompt of pose 1:\n"
        + mascot_prompt(kit, f"{args.scene.strip()} The character is {poses[0]}.") + "\n", encoding="utf-8")
    append_comparison(repo, dict(date=today, scene=args.scene.strip(), models=models, poses=len(poses), cost_usd=spent, folder=rel))
    print(f"wrote {len(cells)} image(s), {sheet_note}, compare.txt in {rel}/")
    print(plan["line"])
    for f in failed:
        print(f"  failed  {f}", file=sys.stderr)
    print(f"the owner picks: set mascot.model and the comparison's `picked` in {KIT}")
    return 1 if failed else 0


def contact_sheet(cells: dict, models: list[str], poses: int, tile: int = 256):
    """Rows are models, columns are poses; the model's name above each row."""
    Image, ImageDraw, _ = kitdraw.pillow()
    label = 28
    sheet = Image.new("RGB", (tile * poses, (tile + label) * len(models)), (24, 24, 28))
    draw = ImageDraw.Draw(sheet)
    getfont = kitdraw.find_font(None)
    for r, mod in enumerate(models):
        y = r * (tile + label)
        draw.text((6, y + 4), mod, font=getfont(18), fill=(235, 235, 240))
        for c in range(poses):
            p = cells.get((mod, c + 1))
            if p is None:
                continue
            with Image.open(p) as im:
                im = im.convert("RGB")
                im.thumbnail((tile, tile))
                sheet.paste(im, (c * tile + (tile - im.width) // 2, y + label + (tile - im.height) // 2))
    return sheet


# --- command line ---------------------------------------------------------------------------------------

def cmd_kit(args) -> int:
    try:
        if args.kit_cmd == "init":
            repo = resolve_repo(args.repo)
            made, filled = init(repo, args.force)
            for p in made:
                print(f"  created  {p}")
            for k, v in filled.items():
                print(f"  filled   {k} = {v}")
            print(f"next: fill the rest of {KIT} (grep for '{{{{'), then `teyla kit check {repo.name}`")
            return 0
        if args.kit_cmd == "check":
            rep = check(resolve_repo(args.repo))
            print(json.dumps(rep, indent=1, ensure_ascii=False) if args.json else render_check(rep))
            return 1 if rep["verdict"] == FIX else 0
    except KitError as e:
        print(f"teyla kit {args.kit_cmd}: {e}", file=sys.stderr)
        return 2
    return 2


def register(sp):
    q = sp.add_parser("kit", help="a product's brand kit: brand/kit.toml, store screenshots, mascot images (docs/KIT.md)",
                      description=__doc__.split("\n\n")[0])
    ks = q.add_subparsers(dest="kit_cmd", required=True)

    def repo_arg(p, required=False):
        p.add_argument("repo", **({} if required else {"nargs": "?"}),
                       help="a repo name under code_root or a path" + ("" if required else " (default: the git root of the current directory)"))

    a = ks.add_parser("init", help="scaffold brand/kit.toml and the folders, filling what DESIGN.md already says")
    a.set_defaults(fn=cmd_kit)
    repo_arg(a)
    a.add_argument("--force", action="store_true", help="replace an existing brand/kit.toml")

    b = ks.add_parser("check", help="FIX: a placeholder, a missing piece, an asset without provenance, two characters")
    b.set_defaults(fn=cmd_kit)
    repo_arg(b)
    b.add_argument("--json", action="store_true")

    c = ks.add_parser("shots", help="store screenshots from the matrix captures and docs/store/captions.json (needs teyla[reel])")
    c.set_defaults(fn=cmd_shots)
    repo_arg(c)
    c.add_argument("--lang", metavar="L,...", help="languages (default: every language in the captions file)")
    c.add_argument("--look", choices=LOOKS, default="light", help="which capture variant to frame (default light)")
    c.add_argument("--sizes", metavar="S,...", help="of " + ", ".join(STORE_SIZES) + " (default all)")
    c.add_argument("--captions", metavar="FILE", help="default docs/store/captions.json")
    c.add_argument("--shots-dir", metavar="DIR", help="default design/shots")
    c.add_argument("--font", metavar="PATH", help="a bold font file that covers the languages")
    c.add_argument("--dry", action="store_true", help="list what would be written")

    d = ks.add_parser("image", help="one image of the mascot in a scene; prints the price, refuses without --yes")
    d.set_defaults(fn=cmd_image)
    repo_arg(d, required=True)
    d.add_argument("scene", help="what the mascot is doing, in a sentence")
    d.add_argument("--model", choices=sorted(genai.IMAGE_MODELS), help="default: mascot.model in the kit")
    d.add_argument("--yes", action="store_true", help="accept the price and make the call")
    d.add_argument("--dry", action="store_true", help="print the price and the prompt; call nothing")
    d.add_argument("--allow-network", action="store_true", help="safe mode: allow this one call")

    e = ks.add_parser("compare", help="the bounded comparison: ten poses, two models, a contact sheet; plan only without --yes")
    e.set_defaults(fn=cmd_compare)
    repo_arg(e, required=True)
    e.add_argument("scene", help="the scene every pose is set in")
    e.add_argument("--models", metavar="A,B", help="one or two of " + ", ".join(sorted(genai.IMAGE_MODELS)) + " (default: both)")
    e.add_argument("--poses", type=int, default=MAX_COMPARE_POSES, help=f"1 to {MAX_COMPARE_POSES} (default {MAX_COMPARE_POSES})")
    e.add_argument("--yes", action="store_true", help="accept the total and make the calls")
    e.add_argument("--allow-network", action="store_true", help="safe mode: allow these calls")
    return q
