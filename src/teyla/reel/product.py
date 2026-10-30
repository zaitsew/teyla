"""`teyla reel product` — a product demo cut from a screen recording, with captions and an optional voice-over.

    teyla reel product <repo> [--input movie.mov] [--copy copy.json] [--control caption] [--lang en,es,ru]
                       [--formats vertical,square] [--voice [--script voiceover.json]] [--yes] [-o DIR] [--dry]

Where `teyla reel render` draws a session as a terminal story, this command takes the recording of the app
itself (a simulator recording of the screenshot tour, `xcrun simctl io booted recordVideo demo.mov`, or one
the owner made) and adds the captions of the product's copy table. Per language it writes, under
`brand/out/reel/<lang>/`: `product-vertical.mp4` (1080x1920), `product-square.mp4` (1080x1080), `captions.srt`,
and with `--voice` `voice.mp3`.

Captions come from the copy table (`copy.json`: rows with key, control, state, budget, en, es, ru; the rows whose
`control` is `caption`) or from a plain captions file: {"en": ["line", ...], "es": [...]}, where a line may be
{"text": "...", "start": 0.5, "end": 3.0}. Without start times the captions share the video's length equally.
Every caption passes `teyla reel` redaction (secrets, private terms, e-mail addresses, paths) and is drawn into a
transparent PNG by Pillow; ffmpeg overlays the PNGs, so no ffmpeg text filter is needed.

`--voice` reads the script aloud with the OpenAI speech API (`docs/PRIVACY.md`, row 28). The script is the
`--script` file ({"en": "text", ...}) or, without it, the captions in order. The price is printed first; the
command refuses without `--yes`, and nothing is rendered until you have confirmed. A voice-over longer than the
recording holds the last frame; a shorter one leaves the rest silent.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .. import genai, kitdraw, voice
from .redact import Redactor

FORMATS = {"vertical": (1080, 1920), "square": (1080, 1080)}
# Bottom margin kept clear of platform UI, in pixels.
SAFE_BOTTOM = {"vertical": 400, "square": 130}
MOVIE_EXT = (".mov", ".mp4", ".m4v")
COPY_NAMES = ("brand/reel/copy.json", "brand/copy.json", "copy.json")
TTS_MAX_CHARS = 4096
MIN_CAPTION_SECONDS = 1.5


class ProductError(Exception):
    """The input cannot be used; the message says what to fix."""


@dataclass
class Caption:
    text: str
    start: float | None = None
    end: float | None = None


# --- captions ---------------------------------------------------------------------------------------

def _caption(item) -> Caption:
    if isinstance(item, str):
        if not item.strip():
            raise ProductError("a caption must not be empty")
        return Caption(item.strip())
    if isinstance(item, dict) and str(item.get("text") or "").strip():
        def num(k):
            v = item.get(k)
            if v is None:
                return None
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                raise ProductError(f"caption {item['text'][:30]!r}: `{k}` must be a number of seconds")
            return float(v)
        return Caption(str(item["text"]).strip(), num("start"), num("end"))
    raise ProductError(f"a caption is a string or an object with `text`, not {item!r}"[:120])


def load_captions(path: Path, control: str = "caption", langs: list[str] | None = None) -> dict[str, list[Caption]]:
    """{lang: [Caption]} from a copy table or a plain captions file (see the module docstring)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ProductError(f"cannot read {path}: {e}") from None
    out: dict[str, list[Caption]] = {}
    if isinstance(data, dict) and data and all(k in voice.LANGS for k in data) and all(isinstance(v, list) for v in data.values()):
        for lang, items in data.items():
            out[lang] = [_caption(i) for i in items]
    else:
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            rows = data["rows"]
        elif isinstance(data, list):
            rows = data
        elif isinstance(data, dict) and all(isinstance(v, dict) for v in data.values()):
            rows = [{"key": k, **v} for k, v in data.items()]
        else:
            raise ProductError(f"{path}: expected a copy table (rows with key, control, state, budget, en, es, ru) "
                               "or {\"en\": [captions], ...}")
        rows = [r for r in rows if isinstance(r, dict)]
        picked = [r for r in rows if str(r.get("control") or "") == control]
        if not picked:
            seen = sorted({str(r.get("control")) for r in rows if r.get("control")})
            raise ProductError(f"{path}: no row has control {control!r}" + (f" (controls found: {', '.join(seen)}; pass --control)" if seen else ""))
        for r in picked:
            for lang in voice.LANGS:
                if str(r.get(lang) or "").strip():
                    out.setdefault(lang, []).append(_caption({"text": r[lang], "start": r.get("start"), "end": r.get("end")}))
    if langs:
        gone = [l for l in langs if not out.get(l)]
        if gone:
            raise ProductError(f"no captions in {', '.join(gone)}")
        out = {l: out[l] for l in langs}
    out = {l: c for l, c in out.items() if c}
    if not out:
        raise ProductError(f"{path}: no captions")
    return out


def _unsafe(red: Redactor, text: str) -> bool:
    o = red.clean(text)
    return bool(o.fatal or o.skip or " ".join(o.text.split()) != " ".join(text.split()))


def vet(captions: dict[str, list[Caption]], repo: Path) -> list[str]:
    """Problems with captions that would go into a public video: a string redaction drops or changes."""
    red = Redactor([str(repo)])
    bad = []
    for lang, caps in captions.items():
        for i, c in enumerate(caps, 1):
            if _unsafe(red, c.text):
                bad.append(f"{lang} caption {i} holds a secret, a private term, an address or a path")
    return bad


def vet_texts(texts: dict[str, str], repo: Path) -> list[str]:
    """The same check for a voice-over script: it is spoken into a public video and sent to the speech API."""
    red = Redactor([str(repo)])
    return [f"the {lang} voice-over script holds a secret, a private term, an address or a path"
            for lang, text in texts.items() if _unsafe(red, text)]


def schedule(caps: list[Caption], duration: float) -> list[tuple[float, float, str]]:
    """(start, end, text) for each caption. Timed captions keep their times; the rest share what is left equally."""
    if any(c.start is not None for c in caps):
        if any(c.start is None for c in caps):
            raise ProductError("give every caption a start time, or none")
        out = []
        for i, c in enumerate(caps):
            nxt = caps[i + 1].start if i + 1 < len(caps) else duration
            end = c.end if c.end is not None else nxt
            out.append((c.start, min(max(end, c.start + 0.1), duration), c.text))
        return out
    span = duration / len(caps)
    return [(i * span, (i + 1) * span, c.text) for i, c in enumerate(caps)]


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def srt(timed: list[tuple[float, float, str]]) -> str:
    return "".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(timed, 1))


# --- drawing --------------------------------------------------------------------------------------------

def overlay_png(text: str, fmt: str, path: Path, font_path: str | None = None) -> None:
    """A transparent canvas of the format's size with the caption in a rounded dark pill above the safe margin."""
    Image, ImageDraw, _ = kitdraw.pillow()
    W, H = FORMATS[fmt]
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    getfont = kitdraw.find_font(font_path)
    pad = int(W * 0.035)
    font, lines, size = kitdraw.fit_text(draw, text, getfont, int(W * 0.84) - 2 * pad, 3, int(W * 0.058), int(W * 0.036))
    lh = int(size * 1.25)
    box_w = max(int(draw.textlength(l, font=font)) for l in lines) + 2 * pad
    box_h = lh * len(lines) + 2 * pad
    x0, y1 = (W - box_w) // 2, H - SAFE_BOTTOM[fmt]
    draw.rounded_rectangle((x0, y1 - box_h, x0 + box_w, y1), radius=int(pad * 0.9), fill=(10, 12, 16, 214))
    y = y1 - box_h + pad
    for l in lines:
        draw.text(((W - draw.textlength(l, font=font)) / 2, y), l, font=font, fill=(255, 255, 255, 255))
        y += lh
    canvas.save(path)


# --- ffmpeg ------------------------------------------------------------------------------------------------

def ffmpeg_cmd(ffmpeg: str, src: Path, fmt: str, overlays: list[tuple[Path, float, float]], audio: Path | None,
               out: Path, extra: float = 0.0, background: str = "0B0D10") -> list[str]:
    """The ffmpeg command for one format: fit the recording to the canvas, overlay each caption PNG during its
    time span, mix in the voice-over, encode H.264/AAC."""
    W, H = FORMATS[fmt]
    chain = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x{background},"
             "setsar=1,fps=30")
    if extra > 0.05:
        chain += f",tpad=stop_mode=clone:stop_duration={extra:.2f}"
    parts = [chain + "[v0]"]
    for i, (_, a, b) in enumerate(overlays, 1):
        parts.append(f"[v{i - 1}][{i}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'[v{i}]")
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src)]
    for png, _, _ in overlays:
        cmd += ["-i", str(png)]
    if audio is not None:
        cmd += ["-i", str(audio)]
    cmd += ["-filter_complex", ";".join(parts), "-map", f"[v{len(overlays)}]"]
    if audio is not None:
        cmd += ["-map", f"{len(overlays) + 1}:a", "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    return cmd


def probe_duration(path: Path, run=None, which=None) -> float:
    run, which = run or subprocess.run, which or shutil.which
    ffprobe = which("ffprobe")
    if not ffprobe:
        raise kitdraw.Missing("ffprobe is not on PATH (it comes with ffmpeg: brew install ffmpeg)")
    r = run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60)
    try:
        d = float((r.stdout or "").strip())
    except ValueError:
        raise ProductError(f"cannot read the length of {path.name}: ffprobe said {(r.stderr or r.stdout or '').strip()[:100]!r}") from None
    if d <= 0:
        raise ProductError(f"{path.name} has no length")
    return d


# --- the command ----------------------------------------------------------------------------------------------

def find_input(repo: Path, arg: str | None) -> Path:
    if arg:
        p = Path(arg).expanduser()
        if not p.is_file():
            raise ProductError(f"no recording at {p}")
        return p
    folder = repo / "brand" / "recordings"
    found = sorted((p for p in folder.glob("*") if p.suffix.lower() in MOVIE_EXT), key=lambda p: p.stat().st_mtime) if folder.is_dir() else []
    if not found:
        raise ProductError("no recording: pass --input movie.mov, or put one in brand/recordings/ "
                           "(a simulator recording: xcrun simctl io booted recordVideo demo.mov)")
    return found[-1]


def find_copy(repo: Path, arg: str | None) -> Path:
    if arg:
        p = Path(arg).expanduser()
        if not p.is_file():
            raise ProductError(f"no copy file at {p}")
        return p
    for name in COPY_NAMES:
        if (repo / name).is_file():
            return repo / name
    raise ProductError("no captions: pass --copy copy.json (looked for " + ", ".join(COPY_NAMES) + ")")


def voice_texts(captions: dict[str, list[Caption]], script: Path | None) -> dict[str, str]:
    if script is None:
        return {l: " ".join(c.text for c in caps) for l, caps in captions.items()}
    try:
        data = json.loads(script.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ProductError(f"cannot read the script {script}: {e}") from None
    if not isinstance(data, dict):
        raise ProductError(f"{script}: expected {{\"en\": \"text\", ...}}")
    out = {}
    for l in captions:
        t = data.get(l)
        if not isinstance(t, str) or not t.strip():
            raise ProductError(f"{script} has no text for {l}")
        out[l] = t.strip()
    return out


def cmd_product(args) -> int:
    from .. import kit as kitmod
    run, which = subprocess.run, shutil.which
    try:
        repo = kitmod.resolve_repo(args.repo)
        src = find_input(repo, args.input)
        captions = load_captions(find_copy(repo, args.copy), args.control,
                                 [l.strip() for l in args.lang.split(",")] if args.lang else None)
        fmts = [f.strip() for f in args.formats.split(",") if f.strip()]
        bad = [f for f in fmts if f not in FORMATS]
        if bad or not fmts:
            raise ProductError(f"--formats takes {', '.join(FORMATS)}")
        problems = vet(captions, repo)
        if problems:
            raise ProductError("; ".join(problems) + " (edit the copy file)")
        texts = voice_texts(captions, Path(args.script).expanduser() if args.script else None) if args.voice else {}
        problems = vet_texts(texts, repo) if args.script else []
        if problems:
            raise ProductError("; ".join(problems) + " (edit the script)")
        for l, t in texts.items():
            if len(t) > TTS_MAX_CHARS:
                raise ProductError(f"the {l} voice-over is {len(t)} characters; the speech API takes {TTS_MAX_CHARS}")
        chars = sum(len(t) for t in texts.values())
        usd = genai.tts_price(chars, args.tts_model) if args.voice else 0.0
        kit = kitmod.load(repo) if (repo / kitmod.KIT).is_file() else {}
    except (ProductError, kitmod.KitError, genai.GenError) as e:
        print(f"teyla reel product: {e}", file=sys.stderr)
        return 2
    out_base = Path(args.output).expanduser() if args.output else repo / "brand" / "out" / "reel"
    print(f"reel product: {src.name} -> {', '.join(fmts)} x {', '.join(captions)}"
          + (f", voice-over {chars} characters, {args.tts_model}, {genai.money(usd)}" if args.voice else ", no voice-over"))
    if args.voice and not args.dry and not args.yes:
        print("teyla reel product: the voice-over costs money; run it again with --yes to confirm the price above", file=sys.stderr)
        return 2
    if args.dry:
        for lang, caps in captions.items():
            print(f"  {lang}: " + " | ".join(c.text for c in caps))
        return 0
    if args.voice:
        from .. import net
        if not net.gate("reel product voice-over"):
            return 2
    ffmpeg = which("ffmpeg")
    try:
        kitdraw.pillow()
        if not ffmpeg:
            raise kitdraw.Missing("ffmpeg is not on PATH (brew install ffmpeg)")
        duration = probe_duration(src, run, which)
        for caps in captions.values():
            schedule(caps, duration)            # a timing error must not come after a paid speech call
    except (kitdraw.Missing, ProductError) as e:
        print(f"teyla reel product: {e}", file=sys.stderr)
        return 1
    bg = str((kit.get("shots") or {}).get("background") or "#0B0D10").lstrip("#") if isinstance(kit.get("shots"), dict) else "0B0D10"
    bg = bg if len(bg) == 6 else "0B0D10"
    rc = 0
    for lang, caps in captions.items():
        folder = out_base / lang
        folder.mkdir(parents=True, exist_ok=True)
        audio, extra = None, 0.0
        try:
            if args.voice:
                audio = folder / "voice.mp3"
                audio.write_bytes(genai.speak(texts[lang], args.tts_model, args.tts_voice))
                extra = max(0.0, probe_duration(audio, run, which) - duration)
            timed = schedule(caps, duration + extra)
        except (genai.GenError, ProductError, kitdraw.Missing) as e:
            print(f"teyla reel product: {lang}: {e}", file=sys.stderr)
            rc = 1
            continue
        short = [t for a, b, t in timed if b - a < MIN_CAPTION_SECONDS]
        if short:
            print(f"  {lang}: {len(short)} caption(s) shown under {MIN_CAPTION_SECONDS} s; fewer or shorter captions read better", file=sys.stderr)
        (folder / "captions.srt").write_text(srt(timed), encoding="utf-8")
        for fmt in fmts:
            pngs = []
            for i, (a, b, text) in enumerate(timed, 1):
                png = folder / f".caption-{fmt}-{i:02d}.png"
                overlay_png(text, fmt, png, args.font)
                pngs.append((png, a, b))
            out = folder / f"product-{fmt}.mp4"
            r = run(ffmpeg_cmd(ffmpeg, src, fmt, pngs, audio, out, extra, bg), capture_output=True, text=True, timeout=1800)
            for png, _, _ in pngs:
                png.unlink(missing_ok=True)
            if r.returncode != 0:
                print(f"teyla reel product: ffmpeg failed for {lang} {fmt}: {(r.stderr or '').strip()[-300:]}", file=sys.stderr)
                rc = 1
                continue
            print(f"  wrote {out}")
        if audio is not None:
            print(f"  wrote {audio}  (about {genai.money(genai.tts_price(len(texts[lang]), args.tts_model))})")
    return rc


def add_arguments(rs) -> None:
    """The `product` subcommand of `teyla reel` (called from reel/cli.py)."""
    p = rs.add_parser("product", help="a product demo from a screen recording: captions from the copy table, optional voice-over (docs/KIT.md)")
    p.set_defaults(fn=cmd_product)
    p.add_argument("repo", nargs="?", help="a repo name under code_root or a path (default: the git root of the current directory)")
    p.add_argument("--input", metavar="MOVIE", help="the recording (default: the newest in brand/recordings/)")
    p.add_argument("--copy", metavar="FILE", help="the copy table or a plain captions file (default: " + ", ".join(COPY_NAMES) + ")")
    p.add_argument("--control", default="caption", help="which rows of the copy table are captions (default caption)")
    p.add_argument("--lang", metavar="L,...", help="languages (default: every language in the file)")
    p.add_argument("--formats", default="vertical,square", help="vertical (1080x1920), square (1080x1080) (default both)")
    p.add_argument("--voice", action="store_true", help="add a voice-over read by the OpenAI speech API (costs money; needs --yes)")
    p.add_argument("--script", metavar="FILE", help='the voice-over text per language, {"en": "..."} (default: the captions in order)')
    p.add_argument("--tts-model", choices=sorted(genai.TTS_USD_PER_MCHAR), default=genai.DEFAULT_TTS_MODEL)
    p.add_argument("--tts-voice", default=genai.DEFAULT_VOICE)
    p.add_argument("--yes", action="store_true", help="accept the voice-over price and make the call")
    p.add_argument("--dry", action="store_true", help="print the plan and the price; render and call nothing")
    p.add_argument("-o", "--output", metavar="DIR", help="default: brand/out/reel/ in the repo")
    p.add_argument("--font", metavar="PATH", help="a bold font file that covers the languages")
    p.add_argument("--allow-network", action="store_true", help="safe mode: allow the voice-over call")
