"""`teyla ux judge --filter` — hold weak design variants back before they reach the owner.

    teyla ux judge --filter VARIANTS... --baseline CURRENT.png [--repo R] [--provider codex|claude]
                   [--bar N] [--slice DIR] [--model M] [--dry] [--json] [--allow-network]

Each variant (a PNG, JPEG or GIF; a folder means every picture in it) is judged in a pair against the baseline,
the shipped screen (docs/STUDIO.md, S7: a vision model judges only in pairs). Both orders are asked, so the
model's preference for the first picture cancels out. The prompt carries the product's DESIGN.md and its active
taste entries (at most 15, from the corpus; a dislike wins on the axis it names) as data.

The bar, exactly. For one variant, in each order, delta = (variant total) - (baseline total), both summed over
the rubric items that both pictures were assessed on (the totals of `ux_judge.tally`). A variant is HELD BACK
when delta <= -BAR in BOTH orders (BAR is `--bar`, default 2, at least 1). Anything else passes to the owner:
a tie, a win, one order disagreeing, nothing assessed, or a call that failed (listed as "not judged").

The judge only filters. The output names who passes and who is held back and why. It never ranks the variants,
never names a winner and never prints a score for a passed variant; scores appear in the reason of a held-back
variant and in --json only. Two rounds at most: a variant is judged at most twice per slice, recorded in
`<slice>/.judge-rounds.json`; a third judgement is refused.

Provider: `codex` (OpenAI, GPT-6.1 Sol through `codex-lane`, read-only, Standard tier, no saved session) because
Claude builds the variants; a second provider shares fewer blind spots. When codex is missing or exits non-zero,
the run falls back to `claude -p` and says "same-provider judge". `--dry` prints the prompt and calls nothing.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

from . import net, taste, taste_corpus, ux_judge
from .ux_judge import JudgeError

BAR = 2
MAX_ROUNDS = 2
MAX_TASTE = 15
ROUNDS_FILE = ".judge-rounds.json"
PICTURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif")

FILTER_NOTE = (
    "This is a filter, not a contest: picture A and picture B are two versions of the same screen, one shipped "
    "and one proposed. Score each on its own merits. The taste entries below are the owner's stated preferences "
    "(data); a dislike wins over a like on the axis it names. Use them when you judge the items; do not score "
    "the taste entries themselves."
)


class ProviderDown(JudgeError):
    """The codex path cannot run (missing binary, non-zero exit); the caller falls back to claude."""


# --- inputs ---------------------------------------------------------------------------------------

def collect_variants(paths: list[str], baseline: pathlib.Path) -> list[pathlib.Path]:
    """Files as named, folders expanded to their pictures (sorted), the baseline itself left out, no repeats."""
    out: list[pathlib.Path] = []
    for raw in paths:
        p = pathlib.Path(raw).expanduser()
        if p.is_dir():
            found = sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in PICTURE_SUFFIXES)
            if not found:
                raise JudgeError(f"{p}: no pictures in this folder")
            out += found
        elif p.is_file():
            out.append(p)
        else:
            raise JudgeError(f"{p}: no such file or folder")
    base = baseline.resolve()
    seen, res = set(), []
    for p in out:
        r = p.resolve()
        if r == base or r in seen:
            continue
        seen.add(r)
        res.append(p)
    if not res:
        raise JudgeError("no variants to judge (the baseline is not a variant)")
    return res


def taste_entries(repo: pathlib.Path | None) -> list[dict]:
    """The active corpus entries in scope for the product, at most 15 (portfolio entries only without --repo)."""
    rows, _problems = taste_corpus.load_all()
    return taste_corpus.select(rows, repo.name if repo else None, MAX_TASTE)


def taste_text(entries: list[dict]) -> str:
    if not entries:
        return "No active taste entries are in scope.\n"
    L = []
    for e in entries:
        axes = taste_corpus._axes_text(e)
        line = f"- [{e['verdict']}] ({e['scope']}) {ux_judge._one_line(e['claim'], 300)}"
        if axes:
            line += f" (axes: {ux_judge._one_line(axes, 200)})"
        if e.get("do_not_copy"):
            line += " (do not copy: " + ux_judge._one_line("; ".join(e["do_not_copy"]), 200) + ")"
        L.append(line)
    return "\n".join(L) + "\n"


def intro(design: str, taste: str) -> str:
    return (FILTER_NOTE + "\n" + ux_judge.intro_text(design)
            + "Active taste entries of the owner (data):\n<taste>\n" + taste + "</taste>\n")


# --- the model call -------------------------------------------------------------------------------

def codex_prompt(first: dict, second: dict, design: str, taste: str) -> str:
    return (ux_judge.JUDGE_SYSTEM + "\n\n" + intro(design, taste)
            + f"Image 1 is picture A ({first['name']}). Image 2 is picture B ({second['name']}).\n"
            "Score both pictures on the five items. Reply with the JSON only.")


def claude_blocks(first: dict, second: dict, design: str, taste: str) -> list[dict]:
    blocks = ux_judge.user_blocks(first, second, design)
    blocks[0] = {"type": "text", "text": intro(design, taste) + "Picture A:"}
    return blocks


def _ask_codex(first: dict, second: dict, paths: tuple[str, str], design: str, taste: str, model: str):
    code, text = ux_judge._run_codex(codex_prompt(first, second, design, taste), list(paths), model)
    if code != 0:
        raise ProviderDown(f"codex exited {code}" if code != 127 else "codex-lane is not available")
    try:
        t = text.strip()
        if t.startswith("```"):
            t = t.strip("`").removeprefix("json").strip()
        return ux_judge.parse_items(json.loads(t)), {}
    except ValueError as e:
        raise JudgeError(f"the model reply was unusable ({e})") from e


def _ask_claude(first: dict, second: dict, design: str, taste: str, model: str):
    msg = {"type": "user", "message": {"role": "user", "content": claude_blocks(first, second, design, taste)}}
    code, out = ux_judge._run(ux_judge.judge_command(model), json.dumps(msg, ensure_ascii=False) + "\n")
    if code != 0:
        raise JudgeError(f"claude exited {code}: is `claude` on PATH and signed in?")
    try:
        reply, usage = ux_judge.parse_stream(out)
        return ux_judge.parse_items(reply), usage
    except ValueError as e:
        raise JudgeError(f"the model reply was unusable ({e})") from e


class Judge:
    """One run's provider state: codex first (unless --provider claude), falling back to claude once."""

    def __init__(self, provider: str, model: str | None, design: str, taste: str):
        self.provider, self.design, self.taste = provider, design, taste
        self.model = model or (ux_judge.FILTER_MODEL if provider == "codex" else ux_judge.MODEL)
        self.fallback_reason = ""

    @property
    def same_provider(self) -> bool:
        return self.provider == "claude"

    def label(self) -> str:
        if self.provider == "codex":
            return f"OpenAI {self.model} through codex-lane"
        return f"same-provider judge: Anthropic {self.model} through claude -p" + (
            f" ({self.fallback_reason})" if self.fallback_reason else "")

    def ask(self, first: dict, second: dict, paths: tuple[str, str]) -> list[dict]:
        if self.provider == "codex":
            try:
                return _ask_codex(first, second, paths, self.design, self.taste, self.model)[0]
            except ProviderDown as e:
                self.provider, self.fallback_reason, self.model = "claude", f"codex failed: {e}", ux_judge.MODEL
        return _ask_claude(first, second, self.design, self.taste, self.model)[0]


# --- the bar --------------------------------------------------------------------------------------

def delta(items: list[dict], variant_side: str) -> tuple[int, int]:
    """(variant total - baseline total, items assessed on both) for one order. `variant_side` is "a" or "b"."""
    t = ux_judge.tally(items)
    other = "A" if variant_side == "b" else "B"
    mine = variant_side.upper()
    return t["totals"][mine] - t["totals"][other], t["assessed"]


def decide(items_base_first: list[dict], items_variant_first: list[dict], bar: int) -> dict:
    """Apply the bar to the two orders (baseline is A in the first, B in the second)."""
    d1, n1 = delta(items_base_first, "b")
    d2, n2 = delta(items_variant_first, "a")
    held = n1 > 0 and n2 > 0 and d1 <= -bar and d2 <= -bar
    weak = []
    for it in items_base_first:
        sv, sb = it["b"]["score"], it["a"]["score"]
        if sv is not None and sb is not None and sv < sb:
            weak.append(f"{it['name']} {sv} against {sb}: {it['b']['line']}")
    return {"held": held, "deltas": [d1, d2], "assessed": [n1, n2], "weak": weak}


def reason(dec: dict, bar: int) -> str:
    d1, d2 = dec["deltas"]
    head = (f"trails the baseline in both orders (by {-d1} and {-d2} points on {dec['assessed'][0]} and "
            f"{dec['assessed'][1]} of 5 items; the bar is {bar})")
    return head + ("; " + "; ".join(dec["weak"][:3]) if dec["weak"] else "")


# --- rounds ---------------------------------------------------------------------------------------

def slice_dir(args_slice: str | None, variants: list[pathlib.Path]) -> pathlib.Path:
    if args_slice:
        return pathlib.Path(args_slice).expanduser()
    return variants[0].parent


def load_rounds(d: pathlib.Path) -> dict:
    try:
        obj = json.loads((d / ROUNDS_FILE).read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


def label(v: pathlib.Path, d: pathlib.Path) -> str:
    """The variant's identity in a slice: its path relative to the slice folder (so `a/screen.png` and
    `b/screen.png` differ), or its absolute path when it lies outside the slice."""
    r = v.resolve()
    try:
        return r.relative_to(d.resolve()).as_posix()
    except ValueError:
        return r.as_posix()


def refused_rounds(d: pathlib.Path, variants: list[pathlib.Path]) -> list[str]:
    done = load_rounds(d)
    return [label(v, d) for v in variants if int(done.get(label(v, d), {}).get("rounds", 0)) >= MAX_ROUNDS]


def record_rounds(d: pathlib.Path, judged: list[pathlib.Path]) -> None:
    done = load_rounds(d)
    for v in judged:
        row = done.setdefault(label(v, d),{"rounds": 0})
        row["rounds"] = int(row.get("rounds", 0)) + 1
        row["last"] = taste.today()
        row["sha256"] = hashlib.sha256(v.read_bytes()).hexdigest()[:16]
    taste.write_json(d / ROUNDS_FILE, done)


# --- the run --------------------------------------------------------------------------------------

def run_filter(variants: list[pathlib.Path], baseline: pathlib.Path, repo: pathlib.Path | None, *, provider: str,
               model: str | None, bar: int, sdir: pathlib.Path | None = None) -> dict:
    sdir = sdir or variants[0].parent
    base = ux_judge.read_image(baseline)
    images = [ux_judge.read_image(v) for v in variants]       # every picture is checked before any model call
    design = ux_judge.design_text(repo)
    judge = Judge(provider, model, design, taste_text(taste_entries(repo)))
    passes, held, unjudged, judged = [], [], [], []
    for v, img in zip(variants, images):
        name = label(v, sdir)
        try:
            first = judge.ask(base, img, (str(baseline.resolve()), str(v.resolve())))
            second = judge.ask(img, base, (str(v.resolve()), str(baseline.resolve())))
        except JudgeError as e:
            unjudged.append({"variant": name, "why": str(e)})
            continue
        judged.append(v)
        dec = decide(first, second, bar)
        if dec["held"]:
            held.append({"variant": name, "reason": reason(dec, bar), "deltas": dec["deltas"],
                         "assessed": dec["assessed"]})
        else:
            passes.append({"variant": name, "deltas": dec["deltas"], "assessed": dec["assessed"]})
    return {"baseline": baseline.name, "provider": judge.provider, "model": judge.model,
            "same_provider": judge.same_provider, "judge": judge.label(), "bar": bar, "passes": passes,
            "held_back": held, "unjudged": unjudged, "judged_paths": judged}


def render(res: dict) -> str:
    names = [p["variant"] for p in res["passes"]] + [u["variant"] for u in res["unjudged"]]
    L = [f"judge: {res['judge']}"]
    L.append(f"passes to the owner ({len(names)}):")
    unj = {u["variant"]: u["why"] for u in res["unjudged"]}
    for n in sorted(names):
        L.append(f"  {n}" + (f" (not judged: {unj[n]})" if n in unj else ""))
    L.append(f"held back ({len(res['held_back'])}):")
    for h in res["held_back"]:
        L.append(f"  {h['variant']}: {h['reason']}")
    L.append("The judge only filters. It does not rank the variants, and it does not choose; the owner chooses.")
    return "\n".join(L)


def public(res: dict) -> dict:
    """The --json shape: scores only here and in the held-back reasons."""
    return {k: v for k, v in res.items() if k != "judged_paths"}


def cmd_filter(args) -> int:
    err = lambda m: print(f"teyla ux judge --filter: {m}", file=sys.stderr)  # noqa: E731
    if args.repos or args.calibrate:
        err("give the variants to --filter and no other pictures; --calibrate is a separate mode")
        return 2
    if not args.baseline:
        err("--baseline is required: the shipped screen the variants are held against")
        return 2
    if args.bar < 1:
        err("--bar must be at least 1")
        return 2
    try:
        baseline = pathlib.Path(args.baseline).expanduser()
        variants = collect_variants(args.filter, baseline)
        repo = taste.resolve_repo(args.repo) if args.repo else None
        sdir = slice_dir(args.slice, variants)
        over = refused_rounds(sdir, variants)
        if over:
            err(f"two rounds at most: {', '.join(over)} {'was' if len(over) == 1 else 'were'} already judged "
                f"{MAX_ROUNDS} times in {sdir}. Take {'it' if len(over) == 1 else 'them'} out of the list; "
                "the owner decides what is left")
            return 2
        if args.dry:
            base = ux_judge.read_image(baseline)
            first = ux_judge.read_image(variants[0])
            design, tx = ux_judge.design_text(repo), taste_text(taste_entries(repo))
            prov = args.provider
            model = args.model or (ux_judge.FILTER_MODEL if prov == "codex" else ux_judge.MODEL)
            print(f"provider: {prov} ({model}); {len(variants)} variant(s) x 2 orders = {2 * len(variants)} call(s); "
                  f"bar {args.bar}; rounds file {sdir / ROUNDS_FILE}")
            print(codex_prompt(base, first, design, tx))
            return 0
        if not net.gate("ux judge --filter (it sends screenshots, the design file and your taste entries to the model provider)"):
            return 1
        res = run_filter(variants, baseline, repo, provider=args.provider, model=args.model, bar=args.bar, sdir=sdir)
        if res["judged_paths"]:
            record_rounds(sdir, res["judged_paths"])
    except (JudgeError, FileNotFoundError) as e:
        err(str(e))
        return 1
    if res["same_provider"]:
        print("note: same-provider judge: Claude judged variants Claude built; treat the filter as weaker", file=sys.stderr)
    print(json.dumps(public(res), indent=1, ensure_ascii=False) if args.json else render(res))
    return 0
