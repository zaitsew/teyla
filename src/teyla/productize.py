"""`teyla productize` — is this thing usable by a second person, and what is in the way.

An app built for one person fails to become an app for four in the same few ways every
time: one shared key instead of accounts, tables with no `user_id`, a backend running on
the builder's laptop, no distribution path off that laptop, the builder's own model key
on someone else's device, and no page telling a newcomer what to do first. None of these
is hard. All of them are invisible until somebody tries to hand the app over, which is
the moment they turn into a week of work.

So a repo declares what it serves today and what it should serve next, in the same
`teyla.toml` that already holds its routines and checks:

    [productize]
    users = "owner"                 # owner | family | testers | public
    target = "family"
    platforms = ["ios", "web"]
    identity = "supabase-auth"      # none | shared-key | invite-key | supabase-auth | accounts-hub | ...
    tenancy = "user_id+rls"         # single | per-device | user_id | user_id+rls
    backend = "supabase:abcdef"     # none | local-mac | supabase:<ref> | droplet:<name> | ...
    llm = "proxy-metered"           # none | byo-key | app-key | proxy-metered | ...
    onboarding_doc = "docs/GETTING-STARTED.md"
    secrets = ["OPENAI_API_KEY"]
    cost_cap = "$5 per user, house key"

    [productize.distribution]
    web = "pwa"
    ios = "testflight-internal"

    [[productize.blocker]]
    what = "external TestFlight group"
    who = "owner"
    how = "App Store Connect → TestFlight → add an external group, submit for beta review"

`teyla productize [paths]` reads every such manifest under `code_root`, checks the seven
requirements below against the declared target, and prints what is unmet. `--owner-steps`
turns the whole set — plus whatever `teyla platform` says is missing — into one numbered
list of things only the owner can do, platform first because those unblock several
products at once.

The manifest is parsed leniently on purpose: a repo halfway through filling it in should
get a useful answer, not a parse error. An unknown value is reported as unmet with the
value quoted, never raised.
"""
from __future__ import annotations

import json
import pathlib
import tomllib

from . import config

TARGETS = ("owner", "family", "testers", "public")
SHAREABLE = ("family", "testers", "public")

WEAK_IDENTITY = ("none", "shared-key", "")
# "accounts-hub" — one Supabase-Auth project shared by every product, not a per-product
# login — is the strongest shape R1 recognises: it is listed first and on equal footing
# with a bespoke supabase-auth setup, never treated as a lesser or exotic option.
PUBLIC_IDENTITY = ("accounts-hub", "supabase-auth", "supabase-auth+tokens", "sign-in-with-apple")
METERED_LLM = ("app-key", "proxy-metered", "byo-key+proxy-metered")

# A distribution value that still requires the owner's own machine, or a developer's,
# to put the app on someone else's device.
DEV_ONLY_DISTRIBUTION = ("none", "", "xcode", "apk-sideload")
# The public bar, per platform. `macos` deliberately does not accept `dmg-notarized`:
# a notarized disk image you email to two people is a handover, not a distribution path.
PUBLIC_DISTRIBUTION = {
    "ios": ("testflight-external", "app-store"),
    "macos": ("testflight-external", "app-store"),
    "watch": ("testflight-external", "app-store"),
    "android": ("play-internal", "play"),
    "extension": ("chrome-web-store",),
}


# --- discovery -------------------------------------------------------------------

def find_manifests(paths: list[str] | None = None) -> list[pathlib.Path]:
    """teyla.toml files: at the given paths, or one level under every git repo in `code_root`.

    Same shape as `teyla routines`, except the root comes from ~/.teyla/config.toml so a
    machine that keeps its repos somewhere else still finds them."""
    if paths:
        out = []
        for p in paths:
            q = pathlib.Path(p).expanduser()
            if q.is_dir() and (q / "teyla.toml").exists():
                out.append(q / "teyla.toml")
            elif q.name == "teyla.toml" and q.exists():
                out.append(q)
        return out
    root = config.code_root()
    if not root.is_dir():
        return []
    return [p / "teyla.toml" for p in sorted(root.iterdir())
            if (p / ".git").exists() and (p / "teyla.toml").exists()]


def parse(path: pathlib.Path) -> dict:
    """{product, repo, productize, blockers} — or {error} when the file will not parse."""
    try:
        data = tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, OSError) as e:
        return {"product": path.parent.name, "repo": path.parent, "error": f"{path}: {e}"}
    pz = data.get("productize") or {}
    blockers = [b for b in (pz.get("blocker") or []) if isinstance(b, dict)]
    return {
        "product": (data.get("product") or {}).get("name", path.parent.name),
        "repo": path.parent,
        "productize": pz,
        "blockers": blockers,
    }


# --- the requirements ------------------------------------------------------------

def _req(rid, name, met, detail):
    return {"id": rid, "name": name, "met": bool(met), "detail": detail}


def _env_example_names(repo: pathlib.Path) -> tuple[set[str], bool]:
    """(names declared in every .env.example found, whether any file was found).

    Looks at the repo root and one level under `apps/*/` — a monorepo puts the example
    next to the runtime that reads it, not at the top."""
    files = [repo / ".env.example"]
    apps = repo / "apps"
    if apps.is_dir():
        files += sorted(apps.glob("*/.env.example"))
    names: set[str] = set()
    found = False
    for f in files:
        if not f.exists():
            continue
        found = True
        for line in f.read_text(errors="replace").splitlines():
            line = line.lstrip("#").strip()
            if "=" in line:
                names.add(line.split("=", 1)[0].removeprefix("export ").strip())
    return names, found


def requirements(pz: dict, repo: pathlib.Path, *, target: str | None = None,
                 mail_ready: bool | None = None) -> list[dict]:
    """The requirement rows for one product. `target` overrides the declared one;
    `mail_ready` is `teyla platform`'s answer and only matters for a public target."""
    target = (target or pz.get("target") or pz.get("users") or "owner").strip()
    public = target == "public"
    dist = pz.get("distribution") or {}
    platforms = [str(p) for p in (pz.get("platforms") or [])]
    identity = str(pz.get("identity") or "")
    tenancy = str(pz.get("tenancy") or "")
    backend = str(pz.get("backend") or "")
    llm = str(pz.get("llm") or "")

    rows = []

    # R1 — identity. A device-local app has no account to have: per-device tenancy is
    # the exemption, not an oversight.
    if tenancy == "per-device" and not public:
        rows.append(_req("R1", "identity", True, f"identity={identity or 'none'} (exempt: per-device)"))
    elif public:
        rows.append(_req("R1", "identity", identity in PUBLIC_IDENTITY,
                         f"identity={identity or 'none'}" + ("" if identity in PUBLIC_IDENTITY else f" (public needs one of {', '.join(PUBLIC_IDENTITY)})")))
    else:
        rows.append(_req("R1", "identity", identity not in WEAK_IDENTITY, f"identity={identity or 'none'}"))

    # R2 — tenancy. `single` means two people share one dataset.
    rows.append(_req("R2", "tenancy", tenancy not in ("single", ""), f"tenancy={tenancy or 'unset'}"))

    # R3 — backend. A laptop is not a host: it sleeps, it travels, it is one person's.
    rows.append(_req("R3", "backend", backend not in ("local-mac", ""), f"backend={backend or 'unset'}"))

    # R4 — distribution, one clause per declared platform.
    unmet_platforms = []
    for plat in platforms:
        value = str(dist.get(plat) or "")
        if public:
            allowed = PUBLIC_DISTRIBUTION.get(plat)
            ok = (value not in DEV_ONLY_DISTRIBUTION) if allowed is None else (value in allowed)
        elif plat == "web":
            ok = value not in ("none", "")
        else:
            ok = value not in DEV_ONLY_DISTRIBUTION
        if not ok:
            unmet_platforms.append(f"{plat}={value or 'unset'}")
    rows.append(_req("R4", "distribution", not unmet_platforms,
                     ", ".join(unmet_platforms) if unmet_platforms else f"{len(platforms)} platform(s) have a path"))

    # R5 — an onboarding doc, written for a person who is not you.
    doc = str(pz.get("onboarding_doc") or "")
    rows.append(_req("R5", "onboarding_doc", bool(doc) and (repo / doc).exists(),
                     f"onboarding_doc={doc} missing" if doc else "onboarding_doc unset"))

    # R6 — every secret the product needs is named in an .env.example. No .env.example
    # anywhere is a warning, not a failure: a pure client app may genuinely have none.
    secrets = [str(s) for s in (pz.get("secrets") or [])]
    declared, found = _env_example_names(repo)
    absent = [s for s in secrets if s not in declared]
    if secrets and not found:
        rows.append(_req("R6", "secrets", True, f"WARN: no .env.example anywhere; {len(secrets)} secret(s) undocumented"))
    else:
        rows.append(_req("R6", "secrets", not absent,
                         f"secrets not in .env.example: {', '.join(absent)}" if absent else f"{len(secrets)} secret(s) documented"))

    # R7 — a cost cap wherever the owner's key pays for someone else's use.
    needs_cap = llm in METERED_LLM
    rows.append(_req("R7", "cost_cap", (not needs_cap) or bool(str(pz.get("cost_cap") or "").strip()),
                     f"cost_cap unset (llm={llm})" if needs_cap and not pz.get("cost_cap") else f"llm={llm or 'none'}"))

    # R8 — public sign-in needs a mail sender the platform owns. Only a public target
    # can fail this: for a handful of named people the built-in mailer is enough.
    if public:
        rows.append(_req("R8", "mail", bool(mail_ready),
                         "mail: no platform sender, so sign-in codes reach only your own inbox" if not mail_ready else "platform mail ready"))
    return rows


def evaluate(manifest: dict, *, mail_ready: bool | None = None) -> dict:
    if manifest.get("error"):
        return {"product": manifest["product"], "repo": str(manifest["repo"]), "error": manifest["error"],
                "requirements": [], "blockers": []}
    pz = manifest["productize"]
    users = str(pz.get("users") or "owner")
    target = str(pz.get("target") or users)
    if not pz:
        return {"product": manifest["product"], "repo": str(manifest["repo"]), "users": users, "target": target,
                "declared": False, "requirements": [], "blockers": []}
    if target not in SHAREABLE:
        return {"product": manifest["product"], "repo": str(manifest["repo"]), "users": users, "target": target,
                "declared": True, "requirements": [], "blockers": manifest["blockers"]}
    rows = requirements(pz, manifest["repo"], target=target, mail_ready=mail_ready)
    return {"product": manifest["product"], "repo": str(manifest["repo"]), "users": users, "target": target,
            "declared": True, "requirements": rows, "blockers": manifest["blockers"]}


def evaluate_all(paths: list[str] | None = None, *, mail_ready: bool | None = None) -> list[dict]:
    return [evaluate(parse(m), mail_ready=mail_ready) for m in find_manifests(paths)]


def unmet(report: dict) -> list[dict]:
    return [r for r in report.get("requirements", []) if not r["met"]]


def summarize(reports: list[dict]) -> tuple[int, int]:
    """(products with unmet requirements, unmet requirements in total)."""
    bad = [r for r in reports if unmet(r)]
    return len(bad), sum(len(unmet(r)) for r in bad)


def exit_code(reports: list[dict]) -> int:
    return 1 if any(unmet(r) for r in reports) else 0


# --- owner steps -----------------------------------------------------------------

def owner_steps(reports: list[dict], platform_steps: list[str] | None = None) -> list[str]:
    """One deduplicated, numbered list across every product and the platform.

    Platform items come first: one domain, one mail sender or one server unblocks several
    products at once, and doing them in that order is the difference between one evening
    and four."""
    out: list[str] = []
    seen: set[str] = set()

    def add(line: str) -> None:
        key = line.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(line)

    for step in platform_steps or []:
        add(step)
    for r in reports:
        for b in r.get("blockers", []):
            if str(b.get("who", "owner")) != "owner":
                continue
            what = str(b.get("what") or "").strip()
            how = str(b.get("how") or "").strip()
            add(f"{what} — {how}" if how else what)
    return out


def agent_steps(reports: list[dict]) -> list[str]:
    out, seen = [], set()
    for r in reports:
        for b in r.get("blockers", []):
            if str(b.get("who", "owner")) != "agent":
                continue
            line = f"{r['product']}: {b.get('what', '')}" + (f" — {b['how']}" if b.get("how") else "")
            if line.lower() not in seen:
                seen.add(line.lower())
                out.append(line)
    return out


# --- rendering -------------------------------------------------------------------

def render_text(reports: list[dict]) -> str:
    lines = []
    for r in reports:
        if r.get("error"):
            lines.append(f"{r['product']}  ERROR: {r['error']}")
            continue
        if not r.get("declared"):
            lines.append(f"{r['product']:16} no [productize] block — `teyla productize` cannot tell who this serves")
            continue
        head = f"{r['product']:16} {r['users']}→{r['target']}"
        rows = r["requirements"]
        if not rows:
            lines.append(f"{head}  nothing to meet (target is not a shared one)")
            continue
        met = sum(1 for q in rows if q["met"])
        line = f"{head}  {met}/{len(rows)} met"
        bad = unmet(r)
        if bad:
            line += "  unmet: " + ", ".join(f"{q['id']} {q['detail']}" for q in bad)
        lines.append(line)
        for who in ("owner", "agent"):
            bs = [b for b in r.get("blockers", []) if str(b.get("who", "owner")) == who]
            for b in bs:
                lines.append(f"    [{who}] {b.get('what', '')}" + (f" — {b['how']}" if b.get("how") else ""))
    n, m = summarize(reports)
    lines.append("")
    lines.append(f"{n} product(s) with unmet requirements, {m} requirement(s) unmet")
    return "\n".join(lines) + "\n"


def render_json(reports: list[dict], platform_steps: list[str] | None = None) -> dict:
    n, m = summarize(reports)
    return {
        "products": reports,
        "unmet_products": n,
        "unmet_requirements": m,
        "owner_steps": owner_steps(reports, platform_steps),
        "agent_steps": agent_steps(reports),
    }


def render_owner_steps(reports: list[dict], platform_steps: list[str] | None = None) -> str:
    steps = owner_steps(reports, platform_steps)
    if not steps:
        return "Nothing is waiting on you.\n"
    lines = ["Only you can do these. Platform first — each one unblocks several products.", ""]
    lines += [f"{i}. {s}" for i, s in enumerate(steps, 1)]
    lines.append("")
    return "\n".join(lines)


# --- command ---------------------------------------------------------------------

def cmd_productize(args):
    from . import platform as platform_mod
    # The platform is probed with --no-net: this command answers a question about repos,
    # and should not hang on ssh because a droplet is asleep. An absent manifest still
    # produces one row — "write it" is itself an owner step.
    cfg = platform_mod.load()
    steps = platform_mod.owner_steps(platform_mod.checks(cfg, no_net=True))
    reports = evaluate_all(args.paths or None, mail_ready=platform_mod.mail_ready(cfg))
    if getattr(args, "json", False):
        print(json.dumps(render_json(reports, steps), indent=2, default=str))
    elif getattr(args, "owner_steps", False):
        print(render_owner_steps(reports, steps), end="")
    else:
        print(render_text(reports), end="")
    return exit_code(reports)


def register(sp):
    q = sp.add_parser("productize", help="what stands between each product and its second user")
    q.set_defaults(fn=cmd_productize)
    q.add_argument("paths", nargs="*")
    q.add_argument("--json", action="store_true")
    q.add_argument("--owner-steps", action="store_true", help="one numbered list of what only you can do, platform first")
    return q
