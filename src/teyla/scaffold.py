"""teyla scaffold — stamp out a new plug-and-play repo from templates/repo/.

    teyla scaffold <path> --name X [--kind cli|app|service|ios] [--license apache|mit|none]

"Productize from the start": every new repo is born with AGENTS.md,
a README with a real quick start, check.sh as the first-run check, .env.example,
a .gitignore that keeps runs/ out of git, a LICENSE, CI that runs check.sh, a
routines/ folder with the reference schema, docs/DECISIONS.md, and the
skill/rule/fact split (.claude/rules/README.md). See templates/repo/ for the
source of every file this writes.

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


def _context(name: str, kind: str) -> dict:
    return {
        "name": name,
        "kind": kind,
        "year": str(datetime.date.today().year),
        "release_section": RELEASE_SECTION_IOS if kind == "ios" else "",
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
    report.append("  fill in README.md, docs/DECISIONS.md, and routines/ for this repo")
    return report
