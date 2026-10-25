#!/usr/bin/env python3
"""Writes the brand: per-concept SVG files, the chosen set in brand/, and the comparison board.

    python3 brand/build.py

Every shape is described once, here, on a 64-unit grid (marks) or a 150-unit line
(wordmark). The SVG files and board.html are generated from these descriptions, so
they never drift apart. Colours come from tokens.json.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = json.loads((HERE / "tokens.json").read_text())
L, D = T["color"]["light"], T["color"]["dark"]
MARK = T["color"]["mark"]

# --- Marks, on a 64 x 64 grid. P = primary, A = accent ("needs you"). ---------------
GLYPHS = {
    "1": {
        "name": "Lanes",
        "svg": (
            '<rect x="8" y="13" width="48" height="9" rx="4.5" fill="{P}"/>'
            '<rect x="8" y="27.5" width="30" height="9" rx="4.5" fill="{P}"/>'
            '<circle cx="50.5" cy="32" r="5.5" fill="{A}"/>'
            '<rect x="8" y="42" width="40" height="9" rx="4.5" fill="{P}"/>'
        ),
        "term": "lanes",
        "small": (
            '<rect x="6" y="8" width="20" height="4" rx="2" fill="{P}"/>'
            '<rect x="6" y="14" width="12" height="4" rx="2" fill="{P}"/>'
            '<rect x="22" y="14" width="4" height="4" rx="2" fill="{A}"/>'
            '<rect x="6" y="20" width="16" height="4" rx="2" fill="{P}"/>'
        ),
        "word": "round",
    },
    "2": {
        "name": "Meter",
        "svg": (
            '<path d="M16.44 50.56A22 22 0 1 1 47.56 50.56" fill="none" stroke="{P}" '
            'stroke-width="7" stroke-linecap="round"/>'
            '<path d="M32 35L21.5 24.5" stroke="{P}" stroke-width="7" stroke-linecap="round"/>'
            '<circle cx="32" cy="35" r="6.5" fill="{P}"/>'
            '<circle cx="32" cy="54" r="3.5" fill="{A}"/>'
        ),
        "term": "meter",
        "small": (
            '<path d="M11.05 21.95A7 7 0 1 1 20.95 21.95" fill="none" stroke="{P}" stroke-width="4" stroke-linecap="round"/>'
            '<path d="M16 17L12.5 13.5" stroke="{P}" stroke-width="4" stroke-linecap="round"/>'
            '<circle cx="16" cy="17" r="3" fill="{P}"/>'
            '<circle cx="16" cy="25.5" r="2" fill="{A}"/>'
        ),
        "word": "round",
    },
    "3": {
        "name": "Cursor",
        "svg": (
            '<rect x="9" y="12" width="32" height="10" rx="2.5" fill="{P}"/>'
            '<rect x="27" y="12" width="10" height="40" rx="2.5" fill="{P}"/>'
            '<rect x="45" y="12" width="10" height="17" rx="2.5" fill="{A}"/>'
        ),
        "term": "cursor",
        "small": (
            '<rect x="6" y="8" width="14" height="4" fill="{P}"/>'
            '<rect x="14" y="8" width="4" height="16" fill="{P}"/>'
            '<rect x="22" y="8" width="4" height="8" fill="{A}"/>'
        ),
        "word": "block",
    },
}

# --- Wordmark "Teyla", box 0..150 x 0..66. Two cuts of one skeleton: ------------------
# "round" (stroke 7, round ends) sits with the soft marks 1 and 2; "block" (stroke 9, cut
# ends, square joins) is fitted to the Cursor mark's blocks: cap top and baseline line up
# with the T's bar and stem.
WORDS = {
    "round": (
        '<g fill="none" stroke="{C}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M0 8H28M14 8V48"/>'                      # T
        '<path d="M33 34H61A14 14 0 1 0 57.72 43"/>'        # e
        '<path d="M72 20L86.29 45.5M96 20L80 62"/>'         # y
        '<path d="M107 6V48"/>'                             # l
        '<circle cx="132" cy="34" r="14"/><path d="M146 20V48"/>'  # a
        "</g>"
    ),
    "block": (
        '<g fill="none" stroke="{C}" stroke-width="9" stroke-linecap="butt" stroke-linejoin="miter">'
        '<path d="M0 8H28M14 3.5V51.5"/>'                   # T
        '<path d="M33 34H61A14 14 0 1 0 57.72 43"/>'        # e
        '<path d="M72 15.5L85.2 45M96 15.5L79 62"/>'        # y
        '<path d="M107 3.5V51.5"/>'                         # l
        '<circle cx="132" cy="34" r="14"/><path d="M146 15.5V51.5"/>'  # a
        "</g>"
    ),
}
# Per cut: lockup viewBox width and the wordmark's place beside the 64-unit mark.
LOCKUP = {"round": (204, "translate(73 9) scale(0.8)"), "block": (201, "translate(67 9.08) scale(0.8333)")}

# The concept in use. The top-level brand/*.svg files and the app icons are made from it;
# change it, run this script, then `swift apps/mac/Tools/make_icon.swift`.
CHOSEN = "3"


def glyph(cid, p, a):
    return GLYPHS[cid]["svg"].format(P=p, A=a)


def svg(view, body, w=None, h=None, title="Teyla"):
    size = f' width="{w}" height="{h}"' if w else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}"{size} role="img" '
            f'aria-label="{title}"><title>{title}</title>{body}</svg>\n')


def lockup_view(cid):
    return f"0 0 {LOCKUP[GLYPHS[cid]['word']][0]} 64"


def lockup_body(cid, p, a, ink):
    cut = GLYPHS[cid]["word"]
    return glyph(cid, p, a) + f'<g transform="{LOCKUP[cut][1]}">{WORDS[cut].format(C=ink)}</g>'


def icon_body(cid, uid):
    """The macOS app icon: a 1024 canvas, an 824 body with a 185 corner, as in make_icon.swift."""
    top, bottom = MARK["icon-top"], MARK["icon-bottom"]
    return (
        f'<defs><linearGradient id="g{uid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient></defs>'
        f'<rect x="100" y="100" width="824" height="824" rx="185" fill="url(#g{uid})"/>'
        f'<g transform="translate(224 224) scale(9)">{glyph(cid, MARK["on-icon"], MARK["accent-on-icon"])}</g>'
    )


def icon_small_body(cid, uid):
    """The small-size icon master, for 16, 32 and 16@2x px. A 32-unit canvas: every edge is on an
    even unit, so it lands on whole pixels at 16 px and at 32 px. Less padding (the body is 28 of
    32), a heavier glyph, and no shadow. Lanes and Cursor are snapped; Meter's curves cannot be."""
    top, bottom = MARK["icon-top"], MARK["icon-bottom"]
    return (
        f'<defs><linearGradient id="s{uid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient></defs>'
        f'<rect x="2" y="2" width="28" height="28" rx="6" fill="url(#s{uid})"/>'
        + GLYPHS[cid]["small"].format(P=MARK["on-icon"], A=MARK["accent-on-icon"])
    )


def write_set(d, cid, name):
    d.mkdir(exist_ok=True)
    view, (w, _) = lockup_view(cid), LOCKUP[GLYPHS[cid]["word"]]
    (d / "mark.svg").write_text(svg("0 0 64 64", glyph(cid, L["primary"], MARK["accent-light"]), 64, 64, name))
    (d / "mark-dark.svg").write_text(svg("0 0 64 64", glyph(cid, D["primary"], D["needs-you"]), 64, 64, name))
    (d / "lockup.svg").write_text(svg(view, lockup_body(cid, L["primary"], MARK["accent-light"], L["text"]), w * 2, 128, name))
    (d / "lockup-dark.svg").write_text(svg(view, lockup_body(cid, D["primary"], D["needs-you"], D["text"]), w * 2, 128, name))
    (d / "icon.svg").write_text(svg("0 0 1024 1024", icon_body(cid, cid), 1024, 1024, name))
    (d / "icon-small.svg").write_text(svg("0 0 32 32", icon_small_body(cid, cid), 32, 32, name))


def write_files():
    for cid in GLYPHS:
        write_set(HERE / f"concept-{cid}", cid, f"Teyla, concept {cid}: {GLYPHS[cid]['name']}")
    write_set(HERE, CHOSEN, "Teyla")


# --- Board ----------------------------------------------------------------------------

def inline(view, body, px, cls=""):
    return f'<svg viewBox="{view}" width="{px}" height="{px}" class="{cls}" aria-hidden="true">{body}</svg>'


def terminal(cid):
    p, a, s, t2 = "t-primary", "t-needs", "t-saving", "t-dim"
    head = f'<span class="{p} b">teyla</span> <span class="{t2}">0.30.0</span>'
    line2 = f'<span class="{a}">2 waiting on you</span> <span class="{t2}">· 7 sessions running</span>'
    line3 = f'<span>$41.20 today</span> <span class="{t2}">·</span> <span class="{s}">$6.10 saved</span>'
    if GLYPHS[cid]["term"] == "lanes":
        g1, g2, g3 = (f'<span class="{p}">━━━━━━━</span>', f'<span class="{p}">━━━━</span> <span class="{a}">●</span>',
                      f'<span class="{p}">━━━━━━</span>')
        banner = f"{g1}  {head}\n{g2}  {line2}\n{g3}  {line3}"
    elif GLYPHS[cid]["term"] == "meter":
        banner = f'<span class="{p}">◔</span> {head}  {line2}\n  {line3}'
    else:
        banner = f'<span class="{p} b">T</span><span class="{a} blink">█</span> {head}  {line2}\n   {line3}'
    return (f'<div class="term"><div class="term-bar"><i></i><i></i><i></i><span>zsh</span></div>'
            f'<pre><span class="t-dim">$</span> teyla\n{banner}\n\n'
            f'<span class="t-dim">  oldest ask  </span>notes-app · "Ship build 212 to TestFlight?" <span class="t-dim">3 h</span>\n'
            f'<span class="t-dim">  top waste   </span>Opus on a docs lane <span class="t-dim">·</span> <span class="{s}">−$2.40/day</span> if moved to Haiku\n'
            f'<span class="t-dim">$</span> <span class="cursor">▌</span></pre></div>')


def readme(cid):
    lock = inline(lockup_view(cid), lockup_body(cid, L["primary"], MARK["accent-light"], L["text"]), 0, "lockup")
    return (f'<div class="readme"><div class="gh-bar"><span>README.md</span></div><div class="gh-body">'
            f'<div class="hero">{lock}</div>'
            f'<p class="promise">Teyla reads your Claude Code and Codex sessions on your Mac, shows what they cost '
            f'and what\'s waiting on you, and fixes the waste.</p>'
            f'<div class="badges"><span>Apache-2.0</span><span>macOS</span><span>local-first</span><span>v0.30.0</span></div>'
            f'<pre class="gh-code">teyla doctor\nteyla asks</pre></div></div>')


RATIONALE = {
    "1": ("Many sessions run in parallel. One of them waits on you.",
          "Three rounded bars are agent sessions, a list or a timeline seen from above. The middle one is shorter "
          "and ends in an amber dot: the session that stopped on a question. It shows the product in one look, "
          "with no letter and no metaphor to explain. At 16 px the bars are 2 px tall with 1.4 px gaps, the dot is "
          "3 px, and it still reads as three lines and a point."),
    "2": ("An instrument: what it costs, and whether you can relax.",
          "An open dial with the needle resting low, the calm reading. The opening at the foot holds a small amber "
          "dot for what waits on you. It says measurement and cost, the part of Teyla people pay attention to "
          "first. At 16 px the ring is a 1.75 px stroke and the needle a short diagonal. The amber dot drops to "
          "under 2 px and fades, so the mark leans on its silhouette."),
    "3": ("The CLI's own letter: a T whose right arm is a waiting cursor.",
          "A heavy T built from blocks. Its right arm is a separate amber block, the cursor a terminal shows when "
          "it waits for input. It is a monogram that belongs to a command-line tool, and it carries the "
          "\"waiting on you\" idea without a bubble. At 16 px the small-size icon is a T with 2 px strokes on whole pixels, plus a 2 by 4 px block. It is "
          "the most legible of the three and works as a one-character banner in the terminal."),
}


def concept_card(cid):
    name = GLYPHS[cid]["name"]
    lead, para = RATIONALE[cid]
    m_l = glyph(cid, L["primary"], MARK["accent-light"])
    m_d = glyph(cid, D["primary"], D["needs-you"])
    sizes = [16, 32, 64, 256]

    def strip(body, theme):
        cells = "".join(f'<figure>{inline("0 0 64 64", body, s)}<figcaption>{s}</figcaption></figure>' for s in sizes)
        ink = L["text"] if theme == "light" else D["text"]
        acc = MARK["accent-light"] if theme == "light" else D["needs-you"]
        prim = L["primary"] if theme == "light" else D["primary"]
        lock = inline(lockup_view(cid), lockup_body(cid, prim, acc, ink), 0, "lockup")
        return f'<div class="panel {theme}"><div class="sizes">{cells}</div><div class="lock-row">{lock}</div></div>'

    icon = icon_body(cid, f"b{cid}")
    small = icon_small_body(cid, f"b{cid}")
    icons = "".join(f'<figure>{inline("0 0 32 32", small, s) if s <= 32 else inline("0 0 1024 1024", icon, s)}'
                    f'<figcaption>{s}</figcaption></figure>' for s in sizes)
    pix = "".join(
        f'<figure><canvas class="pix" data-concept="{cid}" data-kind="{k}" data-px="{p}"></canvas>'
        f'<figcaption>{label}</figcaption></figure>'
        for k, p, label in (("icon", 16, "icon 16 px, ×4"), ("icon", 32, "icon 32 px, ×2"),
                            ("mark", 16, "mark 16 px, ×4"), ("markdark", 16, "dark 16 px, ×4")))
    return f'''
<section class="concept">
  <header><h2><span class="num">{cid}</span>{name}</h2><p class="lead">{lead}</p></header>
  <p class="why">{para}</p>
  <div class="two">{strip(m_l, "light")}{strip(m_d, "dark")}</div>
  <div class="iconrow">
    <figure class="big">{inline("0 0 1024 1024", icon, 512)}<figcaption>app icon, 1024 canvas, shown at 50%; 16 and 32 px use the small-size master</figcaption></figure>
    <div class="iconside">
      <div class="panel desk light"><div class="sizes">{icons}</div></div>
      <div class="panel desk darkdesk"><div class="sizes">{icons}</div></div>
      <div class="pixrow">{pix}</div>
    </div>
  </div>
  <div class="two">{terminal(cid)}{readme(cid)}</div>
</section>'''


def swatch(label, hexv, fg):
    return f'<div class="sw" style="background:{hexv};color:{fg}"><b>{label}</b><span>{hexv}</span></div>'


def board():
    marks_js = {cid: {"mark": svg("0 0 64 64", glyph(cid, L["primary"], MARK["accent-light"])),
                      "markdark": svg("0 0 64 64", glyph(cid, D["primary"], D["needs-you"])),
                      "icon": svg("0 0 32 32", icon_small_body(cid, "p" + cid))} for cid in GLYPHS}
    sw_l = "".join(swatch(k, L[k], L["text"] if k not in ("primary", "text", "text-secondary", "needs-you", "saving", "danger") else "#FFFFFF")
                   for k in ("background", "surface", "border", "text", "text-secondary", "primary", "needs-you", "saving", "danger"))
    sw_d = "".join(swatch(k, D[k], D["text"] if k in ("background", "surface", "border") else D["background"])
                   for k in ("background", "surface", "border", "text", "text-secondary", "primary", "needs-you", "saving", "danger"))
    cards = "".join(concept_card(c) for c in GLYPHS)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Teyla brand concepts</title>
<style>
:root {{
  --bg:{L["background"]}; --surface:{L["surface"]}; --border:{L["border"]}; --text:{L["text"]};
  --text2:{L["text-secondary"]}; --primary:{L["primary"]};
  --dbg:{D["background"]}; --dsurface:{D["surface"]}; --dborder:{D["border"]}; --dtext:{D["text"]};
  --dtext2:{D["text-secondary"]}; --dprimary:{D["primary"]}; --dneeds:{D["needs-you"]}; --dsaving:{D["saving"]};
  --sans:{T["type"]["sans"]}; --mono:{T["type"]["mono"]};
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:13px/1.45 var(--sans); }}
main {{ max-width:1400px; margin:0 auto; padding:40px 40px 64px; }}
h1 {{ font-size:28px; font-weight:600; margin:0 0 4px; letter-spacing:-0.01em; }}
.sub {{ color:var(--text2); margin:0 0 24px; font-size:16px; }}
.tokens {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:40px; }}
.swatches {{ display:grid; grid-template-columns:repeat(9,1fr); border-radius:10px; overflow:hidden; border:1px solid var(--border); }}
.sw {{ padding:10px 8px 8px; min-height:64px; display:flex; flex-direction:column; justify-content:space-between; font-size:11px; }}
.sw span {{ font-family:var(--mono); opacity:.85; }}
.concept {{ background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:28px; margin-bottom:32px; }}
.concept header {{ display:flex; align-items:baseline; gap:16px; }}
h2 {{ font-size:28px; font-weight:600; margin:0; display:flex; align-items:center; gap:12px; }}
.num {{ display:inline-grid; place-items:center; width:32px; height:32px; border-radius:8px; background:var(--primary); color:#fff; font-size:16px; }}
.lead {{ font-size:16px; font-weight:500; margin:0; color:var(--text2); }}
.why {{ max-width:880px; margin:8px 0 20px; color:var(--text2); }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }}
.panel {{ border-radius:10px; padding:20px; }}
.panel.light {{ background:var(--bg); border:1px solid var(--border); }}
.panel.dark {{ background:var(--dbg); color:var(--dtext2); }}
.panel.darkdesk {{ background:#1C1E24; color:var(--dtext2); }}
.sizes {{ display:flex; align-items:flex-end; gap:24px; }}
figure {{ margin:0; display:flex; flex-direction:column; align-items:center; gap:6px; }}
figcaption {{ font-size:11px; color:var(--text2); font-family:var(--mono); }}
.dark figcaption, .darkdesk figcaption {{ color:var(--dtext2); }}
.lock-row {{ margin-top:16px; }}
.lockup {{ height:56px; width:auto; display:block; }}
.iconrow {{ display:grid; grid-template-columns:512px 1fr; gap:24px; margin-bottom:16px; align-items:start; }}
.big svg {{ display:block; }}
.iconside {{ display:flex; flex-direction:column; gap:16px; }}
.desk {{ padding:16px 20px; }}
.pixrow {{ display:flex; gap:24px; padding:8px 4px; }}
.pix {{ width:64px; height:64px; image-rendering:pixelated; border:1px solid var(--border); background:
  repeating-conic-gradient(#EEE 0 25%, #FFF 0 50%) 0 0/8px 8px; }}
.term {{ background:var(--dbg); border-radius:10px; overflow:hidden; border:1px solid #000; }}
.term-bar {{ background:#22252C; padding:8px 12px; display:flex; gap:6px; align-items:center; color:var(--dtext2); font-size:11px; }}
.term-bar i {{ width:10px; height:10px; border-radius:50%; background:#3A3E48; display:inline-block; }}
.term-bar span {{ margin-left:8px; }}
.term pre {{ margin:0; padding:16px 18px 18px; font:12.5px/1.6 var(--mono); color:var(--dtext); white-space:pre; overflow:hidden; }}
.t-primary {{ color:var(--dprimary); }} .t-needs {{ color:var(--dneeds); }} .t-saving {{ color:var(--dsaving); }}
.t-dim {{ color:var(--dtext2); }} .b {{ font-weight:700; }} .cursor {{ color:var(--dtext2); }}
.readme {{ background:#FFFFFF; border:1px solid var(--border); border-radius:10px; overflow:hidden; }}
.gh-bar {{ padding:10px 16px; border-bottom:1px solid var(--border); font-weight:600; font-size:12px; }}
.gh-body {{ padding:28px 32px 24px; text-align:center; }}
.hero .lockup {{ height:72px; margin:0 auto 14px; }}
.promise {{ font-size:15px; max-width:520px; margin:0 auto 14px; }}
.badges {{ display:flex; gap:6px; justify-content:center; margin-bottom:16px; }}
.badges span {{ font:11px var(--mono); padding:2px 8px; border-radius:4px; background:var(--bg); border:1px solid var(--border); color:var(--text2); }}
.gh-code {{ text-align:left; background:var(--bg); border-radius:6px; padding:12px 14px; margin:0; font:12px/1.5 var(--mono); }}
footer {{ color:var(--text2); }}
footer h2 {{ font-size:16px; margin-bottom:8px; color:var(--text); }}
footer p {{ max-width:880px; margin:0 0 6px; }}
</style></head>
<body><main>
<h1>Teyla brand concepts</h1>
<p class="sub">Three marks, one wordmark in two cuts, one token set. Concept {CHOSEN} is in use; the other two stay here as alternatives.</p>
<div class="tokens"><div class="swatches">{sw_l}</div><div class="swatches">{sw_d}</div></div>
{cards}
<footer><h2>In use: concept {CHOSEN}, {GLYPHS[CHOSEN]["name"]}</h2>
<p>{T["brand"]["why"]}</p>
<p>Concepts 1 and 2 share the round cut of the wordmark; Cursor uses the block cut, fitted to its bars. Type: {T["type"]["sans"].split(",")[0]} for UI, {T["type"]["mono"].split(",")[0]} for code and the terminal.</p></footer>
</main>
<script>
// Rasterises each mark to a real 16 or 32 px bitmap, then shows it enlarged with hard pixels.
const MARKS = {json.dumps(marks_js)};
document.querySelectorAll("canvas.pix").forEach((cv) => {{
  const px = +cv.dataset.px, src = MARKS[cv.dataset.concept][cv.dataset.kind];
  cv.width = px; cv.height = px;
  const img = new Image();
  img.onload = () => {{
    const ctx = cv.getContext("2d");
    if (cv.dataset.kind === "markdark") {{ ctx.fillStyle = "{D["background"]}"; ctx.fillRect(0, 0, px, px); }}
    ctx.drawImage(img, 0, 0, px, px);
  }};
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(src);
}});
</script>
</body></html>
'''


if __name__ == "__main__":
    write_files()
    (HERE / "board.html").write_text(board())
    print("wrote", ", ".join(sorted(str(p.relative_to(HERE)) for p in HERE.rglob("*.svg"))), "and board.html")
