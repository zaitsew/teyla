#!/usr/bin/env python3
"""Build the skills-only upload archive for OpenAI's plugin directory.

    scripts/build_openai_plugin.py [--profile portable|full] [--out DIR]

The guide (https://developers.openai.com/plugins/guides/submit-claude-plugin.md) accepts a
Claude Code plugin as a skills-only upload when the archive root, or its single top-level
directory, holds `.claude-plugin/plugin.json` with a non-empty `description` and at least one
`skills/<name>/SKILL.md`. The portal then generates `.codex-plugin/plugin.json` itself.
Hooks do not carry over (ChatGPT runs none; Codex runs command hooks only), and commands
become skills. So this script copies `plugin/` minus `hooks/`, turns each command into a
skill, and swaps Claude's argument placeholders for plain words.

Profiles:
  portable  `review` and `rule`: they need no Teyla CLI and no Claude Code transcripts.
            The default, and the one to submit first.
  full      every skill and command. `harvest`, `tidy`, `wiki-pass`, `adoption-review` and
            `correct` need the separately installed `teyla` CLI and say so, then stop.

Output: DIR/teyla-openai-<profile>-<version>.zip (default DIR: dist/). The archive is
byte-for-byte reproducible: sorted entries, fixed timestamps. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugin"
TOP = "teyla"
EPOCH = (2026, 1, 1, 0, 0, 0)

PROFILES = {
    "portable": {
        "skills": ["review"],
        "commands": ["rule"],
        "description": ("Review a branch diff before merge (P1 and P2 findings only, at most two rounds) "
                        "and record one-sentence rules in the repo. Local files only; nothing is uploaded."),
    },
    "full": {
        "skills": ["adoption-review", "harvest", "review", "tidy", "wiki-pass"],
        "commands": ["correct", "rule"],
        "description": None,  # keep the plugin's own description
    },
}

# Claude Code argument placeholders mean nothing to another harness. Longest phrases first.
REPLACEMENTS = [
    ("Record this rule: $ARGUMENTS", "Record the rule the user gave."),
    ("Record this correction: $ARGUMENTS", "Record the correction the user gave."),
    ("Parse `$ARGUMENTS`:", "Parse the user's text:"),
    ("the argument text above", "the user's text"),
    ("`teyla tidy --json $ARGUMENTS`", "`teyla tidy --json [paths the user named]`"),
    ("teyla tidy --json $ARGUMENTS", "teyla tidy --json [paths the user named]"),
    ('"$1"', '"<path the user named>"'),
]
LEFTOVER = re.compile(r"\$ARGUMENTS|\$\{?1\}?(?![0-9])")


def neutral(text: str, where: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    left = LEFTOVER.search(text)
    if left:
        raise SystemExit(f"{where}: placeholder {left.group(0)!r} is still there; add a replacement")
    return text


def command_to_skill(name: str, text: str) -> str:
    """commands/<name>.md has no `name:` in its front matter; a skill needs one."""
    head, sep, rest = text.partition("\n---\n")
    if not text.startswith("---\n") or not sep:
        raise SystemExit(f"commands/{name}.md has no front matter")
    return f"---\nname: {name}\n{head[4:]}\n---\n{rest}"


CLI_SKILLS = {"adoption-review", "harvest", "tidy", "wiki-pass", "correct"}


def readme(profile: str, version: str, spec: dict) -> str:
    """The Claude README describes hooks this archive does not carry; this one describes the archive."""
    names = sorted(spec["skills"] + spec["commands"])
    rows = []
    for n in names:
        src = PLUGIN / ("skills" if n in spec["skills"] else "commands")
        src = src / n / "SKILL.md" if n in spec["skills"] else src / f"{n}.md"
        desc = re.search(r"^description: (.*)$", src.read_text(), re.M).group(1)
        need = "needs the separately installed Teyla CLI" if n in CLI_SKILLS else "no CLI needed"
        rows.append(f"- **`{n}`** ({need}): {desc}")
    cli = ""
    if any(n in CLI_SKILLS for n in names):
        cli = ("\nSkills marked as needing the CLI check for it first. When it is missing they print one line,\n"
               "`uv tool install --python 3.12 git+https://github.com/zaitsew/teyla` (Python 3.11 or newer), and stop.\n"
               "`harvest` instead continues with a plain `grep` and `python3` pass.\n")
    writes = ("- Writes only files in the repo you work in (`.claude/rules/`, `AGENTS.md`)." if profile == "portable" else
              "- Writes files in the repo you work in (`.claude/rules/`, `AGENTS.md`, the folders named in each skill) and,\n"
              "  for `correct`, `~/.teyla/corrections/` (mode 0600, secrets replaced by `[redacted]`).\n"
              "- `harvest` and `adoption-review` read your local Claude Code session transcripts. Nothing is uploaded.")
    return f"""# Teyla skills ({version})

Skills from the Teyla plugin, without its Claude Code hooks. Nothing here runs a server or
uploads anything.

{chr(10).join(rows)}
{cli}
## Privacy

{writes}
- `review` can run a `codex-review` or `claude-review` script if one is on PATH. That script sends the diff to the
  provider it wraps. Without it, one fresh sub-agent reviews the diff and nothing else is contacted.
- Source, issues and the full manual (including the Claude Code hooks): https://github.com/zaitsew/teyla
- Apache-2.0, see `LICENSE`.
"""


def collect(profile: str) -> dict[str, bytes]:
    spec = PROFILES[profile]
    files: dict[str, bytes] = {}
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    if spec["description"]:
        manifest["description"] = spec["description"]
    files[".claude-plugin/plugin.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    files["README.md"] = readme(profile, manifest["version"], spec).encode()
    files["LICENSE"] = (PLUGIN / "LICENSE").read_bytes()
    for skill in spec["skills"]:
        src = PLUGIN / "skills" / skill / "SKILL.md"
        files[f"skills/{skill}/SKILL.md"] = neutral(src.read_text(), str(src)).encode()
    for cmd in spec["commands"]:
        src = PLUGIN / "commands" / f"{cmd}.md"
        files[f"skills/{cmd}/SKILL.md"] = neutral(command_to_skill(cmd, src.read_text()), str(src)).encode()
    return files


def check(files: dict[str, bytes]) -> None:
    """The guide's two requirements, plus what the Claude directory also demands of a skill."""
    manifest = json.loads(files[".claude-plugin/plugin.json"])
    if not str(manifest.get("description", "")).strip():
        raise SystemExit("plugin.json has an empty description")
    skills = [p for p in files if re.fullmatch(r"skills/[^/]+/SKILL\.md", p)]
    if not skills:
        raise SystemExit("no skills/<name>/SKILL.md in the archive")
    for path in skills:
        text = files[path].decode()
        m = re.match(r"---\n(.*?)\n---\n", text, re.S)
        if not m or not re.search(r"^name: ", m.group(1), re.M) or not re.search(r"^description: ", m.group(1), re.M):
            raise SystemExit(f"{path}: front matter needs name and description")
    if any(p.startswith(("hooks/", "commands/")) for p in files):
        raise SystemExit("hooks and commands must not be in a skills-only archive")


def write_zip(files: dict[str, bytes], out: pathlib.Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(f"{TOP}/{name}", EPOCH)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, files[name])


def build(profile: str, out_dir: pathlib.Path) -> pathlib.Path:
    files = collect(profile)
    check(files)
    version = json.loads(files[".claude-plugin/plugin.json"])["version"]
    out = out_dir / f"teyla-openai-{profile}-{version}.zip"
    write_zip(files, out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", choices=sorted(PROFILES), default="portable")
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "dist")
    args = ap.parse_args(argv)
    out = build(args.profile, args.out)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(names)} files)")
    for n in names:
        print(f"  {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
