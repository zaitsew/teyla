"""teyla scaffold — stamp out a new plug-and-play repo from templates/repo/.

    teyla scaffold <path> --name X [--kind cli|app|service|ios] [--license apache|mit|none]

"Productize from the start": every new repo is born with AGENTS.md,
a README with a real quick start, check.sh as the first-run check, .env.example,
a .gitignore that keeps runs/ out of git, a LICENSE, CI that runs check.sh, a
routines/ folder with the reference schema, docs/DECISIONS.md, and the
skill/rule/fact split (.claude/rules/README.md). See templates/repo/ for the
source of every file this writes.

Kinds `app` and `service` are the ones somebody else will eventually use, so they
are also born with the answer to "who is this for": a `[productize]` block in
teyla.toml, a `docs/GETTING-STARTED.md` addressed to a person who is not you, and
`deploy/droplet/` fragments for the shared server. `teyla productize` reads that
block. Adding all three later is a week; declaring them on day one is a minute.

Idempotent: a file that already exists at the destination is never
overwritten — it is reported as SKIP. Safe to re-run after hand-editing.
"""
from __future__ import annotations

import datetime
import pathlib
import subprocess

PKG_ROOT = None  # templates resolved via teyla.templates_dir()
TEMPLATE_ROOT = __import__("teyla").templates_dir() / "repo"
KIND_ROOT = TEMPLATE_ROOT / "_kind"

KINDS = ("cli", "app", "service", "ios")
LICENSES = ("apache", "mit", "none")

# Kinds that end up in someone else's hands. They share one extra template tree rather
# than each carrying a copy of it — two copies of an onboarding stub drift in a month.
PRODUCTIZED_KINDS = ("app", "service")
PRODUCTIZED_ROOT = KIND_ROOT / "_productized"

LICENSE_TEMPLATES = {
    "apache": "LICENSE-Apache-2.0.txt",
    "mit": "LICENSE-MIT.txt",
}

# Files in the template root that are handled specially, not by the generic
# walk (the two license bodies are merged into a single chosen LICENSE).
_SPECIAL = set(LICENSE_TEMPLATES.values())

RELEASE_SECTION_IOS = """## Releases (iOS)

See `docs/RELEASE.md`. TestFlight and the App Store go through the App Store
Connect API key only — never the Xcode GUI, never a password.
`~/ops/bin/testflight release ...` cuts a release; `~/ops/bin/testflight
bootstrap ...` sets up signing once per machine.
"""


PRODUCTIZE_BLOCK = """
# ---------------------------------------------------------------------------
# Who this serves, and who it should serve next. `teyla productize` reads this
# block and says what stands between the two. Fill it in now — the answers are
# cheap while the code is small and expensive once someone is waiting.
# ---------------------------------------------------------------------------
[productize]
users = "owner"                         # owner | family | testers | public
target = "family"                       # what you want next
platforms = ["web"]                     # ios | macos | web | android | watch | extension | cli
identity = "none"                       # none | shared-key | invite-key | supabase-auth |
                                        # supabase-auth+tokens | sign-in-with-apple | icloud
tenancy = "single"                      # single | per-device | user_id | user_id+rls
backend = "none"                        # none | local-mac | supabase:<ref> | droplet:<name> |
                                        # vercel | github-pages
llm = "none"                            # none | byo-key | app-key | proxy-metered |
                                        # byo-key+proxy-metered
first_run = "none"                      # sign-in | sign-in+skip | none — the screen the
                                        # app opens on; see "The first screen" in
                                        # docs/PRODUCTIZE.md. Never "none" for family/public.
sample_data = "unlabelled"              # none | labelled | unlabelled — canned content must
                                        # never look like the user's own
onboarding_doc = "docs/GETTING-STARTED.md"
secrets = []                            # every name must appear in .env.example
cost_cap = ""                           # required once your key pays for someone else's use

[productize.distribution]
web = "none"                            # none | pwa | github-pages | vercel | droplet
# ios = "none"                          # none | xcode | testflight-internal |
#                                       # testflight-external | app-store
# macos = "none"                        # none | xcode | testflight | dmg-notarized | app-store
# android = "none"                      # none | apk-sideload | pwa | play-internal | play
# extension = "none"                    # none | unpacked-zip | chrome-web-store

# One per thing standing in the way. `who` is who can actually do it — an owner
# blocker is an account, a payment or a signature; an agent blocker is work.
# [[productize.blocker]]
# what = "no account system"
# who = "agent"
# how = "user_id + row-level security from the first migration, not retrofitted"

"""


def _context(name: str, kind: str) -> dict:
    return {
        "name": name,
        "kind": kind,
        "year": str(datetime.date.today().year),
        "release_section": RELEASE_SECTION_IOS if kind == "ios" else "",
        "productize": PRODUCTIZE_BLOCK if kind in PRODUCTIZED_KINDS else "",
    }


def _render(text: str, ctx: dict) -> str:
    for key, value in ctx.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _write(dest: pathlib.Path, content: str, executable: bool, report: list[str]) -> None:
    if dest.exists():
        report.append(f"SKIP {dest} (already exists)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)
    if executable:
        dest.chmod(dest.stat().st_mode | 0o111)
    report.append(f"wrote {dest}")


def _copy_tree(src_root: pathlib.Path, dest_root: pathlib.Path, ctx: dict, report: list[str], skip_names: set[str] = frozenset()) -> None:
    for src in sorted(src_root.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(src_root)
        if rel.parts[0] in skip_names:
            continue
        if src.name in _SPECIAL and src_root == TEMPLATE_ROOT:
            continue  # handled by the license step
        dest = dest_root / rel
        content = _render(src.read_text(), ctx)
        executable = src.name == "check.sh"
        _write(dest, content, executable, report)


def scaffold(path: str, name: str, kind: str = "cli", license: str = "apache") -> list[str]:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    if license not in LICENSES:
        raise ValueError(f"license must be one of {LICENSES}, got {license!r}")
    if not TEMPLATE_ROOT.exists():
        raise FileNotFoundError(f"template root missing: {TEMPLATE_ROOT}")

    dest = pathlib.Path(path).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    ctx = _context(name, kind)
    report: list[str] = [f"scaffolding {kind} repo '{name}' into {dest}"]

    _copy_tree(TEMPLATE_ROOT, dest, ctx, report, skip_names={"_kind"})

    kind_dir = KIND_ROOT / kind
    if kind_dir.exists():
        _copy_tree(kind_dir, dest, ctx, report)

    if kind in PRODUCTIZED_KINDS and PRODUCTIZED_ROOT.exists():
        _copy_tree(PRODUCTIZED_ROOT, dest, ctx, report)

    if license != "none":
        license_src = TEMPLATE_ROOT / LICENSE_TEMPLATES[license]
        _write(dest / "LICENSE", _render(license_src.read_text(), ctx), False, report)

    agents = dest / "AGENTS.md"
    claude = dest / "CLAUDE.md"
    if agents.exists():
        if claude.exists():
            report.append(f"SKIP {claude} (already exists)")
        else:
            claude.symlink_to("AGENTS.md")
            report.append(f"symlinked {claude} -> AGENTS.md")
    else:
        report.append(f"SKIP {claude} (no AGENTS.md to point at)")

    if not (dest / ".git").exists():
        subprocess.run(["git", "init", "-q", str(dest)], check=True)
        report.append(f"git init {dest}")
    else:
        report.append(f"SKIP git init (already a repo: {dest})")

    report.append("")
    report.append("Next steps:")
    report.append(f"  cd {dest}")
    report.append("  cp .env.example .env   # fill in whatever it lists")
    report.append("  ./check.sh              # first-run check")
    if kind == "ios":
        report.append("  see docs/RELEASE.md before the first TestFlight upload")
    if kind in PRODUCTIZED_KINDS:
        report.append("  fill in [productize] in teyla.toml, then: teyla productize .")
    report.append("  fill in README.md, docs/DECISIONS.md, and routines/ for this repo")
    return report
