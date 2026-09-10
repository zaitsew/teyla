"""~/.teyla/config.toml — the few machine-level settings Teyla needs.

    code_root = "~/repos"          where this machine keeps code repos (doctor scans it)
    ops_root  = "~/ops"            the ops root (run artifacts, wiki)
    [update]
    repo    = "zaitsew/teyla"      GitHub repo `teyla update` pulls releases from
    channel = "release"            "release" (tags) or "main" (tip of main)

Every key has a default; the file is optional. `teyla policy init` writes it once so the
work laptop and the home laptop can differ in roots without differing in commands.
"""
from __future__ import annotations

import os
import pathlib

HOME = pathlib.Path.home()
TEYLA_DIR = HOME / ".teyla"
CONFIG_PATH = TEYLA_DIR / "config.toml"

DEFAULTS = {
    "code_root": "~/repos",
    "ops_root": "~/ops",
    "update": {"repo": "zaitsew/teyla", "channel": "release"},
}


def load(path: pathlib.Path | None = None) -> dict:
    import copy
    cfg = copy.deepcopy(DEFAULTS)
    p = path or CONFIG_PATH
    if p.exists():
        import tomllib
        try:
            data = tomllib.loads(p.read_text())
        except (tomllib.TOMLDecodeError, OSError):
            data = {}
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    env_repo = os.environ.get("TEYLA_REPO")
    if env_repo:
        cfg["update"]["repo"] = env_repo
    return cfg


def write(code_root: str = "~/repos", ops_root: str = "~/ops", repo: str = "zaitsew/teyla",
          channel: str = "release", path: pathlib.Path | None = None, force: bool = False) -> str:
    p = path or CONFIG_PATH
    if p.exists() and not force:
        return f"exists: {p}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f'code_root = "{code_root}"\nops_root = "{ops_root}"\n\n[update]\nrepo = "{repo}"\nchannel = "{channel}"\n'
    )
    return f"wrote {p}"


def code_root(cfg: dict | None = None) -> pathlib.Path:
    return pathlib.Path((cfg or load())["code_root"]).expanduser()


def ops_root(cfg: dict | None = None) -> pathlib.Path:
    return pathlib.Path((cfg or load())["ops_root"]).expanduser()
