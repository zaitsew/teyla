"""`teyla plugin install|uninstall` — the no-CLI install path.

Written for the machine docs/case-studies/2026-09-09-corporate-pm-feedback.md describes:
Claude Code runs as the desktop app, there is no `claude` binary on PATH, so
`claude plugin marketplace add` / `claude plugin install` cannot run at all. The feedback
is explicit about what that means: *"I installed it by cloning the repo into the
marketplace directory and hand-writing three registry JSON files. That worked, but it is
not a documented path and it is not something I would ask a colleague to do."* This module
is that hand-editing, made safe and reversible.

What the harness actually keeps, inspected on this machine (`~/.claude/plugins/`):

    known_marketplaces.json    {marketplace: {source: {...}, installLocation, lastUpdated}}
    installed_plugins.json     {"version": 2, "plugins": {"<name>@<marketplace>": [
                                    {scope, installPath, version, installedAt, lastUpdated,
                                     gitCommitSha}]}}
    cache/<marketplace>/<plugin>/<version>/     a copy of the plugin directory — the thing
                                                 the harness actually loads, distinct from a
                                                 `directory`-source marketplace's own working
                                                 tree, which is used in place and never copied.

No separate file-hash manifest exists in either registry file or anywhere under
`~/.claude/plugins` on this machine as of 2026-09-09 (the case study mentions one but the
directory here has none to copy the shape of). `install()` looks for one — a JSON file
whose values are all hex-hash-shaped strings — and mirrors its exact shape into the new
cache path only if it finds one; it never invents a format. See `_find_hash_manifest`.

    teyla plugin install <source>     source: a local path to a repo with
                                       .claude-plugin/marketplace.json, or "owner/repo"
                                       (cloned via git into ~/.claude/plugins/marketplaces/)
    teyla plugin uninstall <name>     name or name@marketplace; reverses install() for that
                                       plugin: the installed_plugins.json entry and its cache
                                       copy. Leaves known_marketplaces.json alone — other
                                       plugins may still be sourced from the same marketplace,
                                       and re-adding it is idempotent anyway.

Both back up the two registry files first, to `<file>.bak-<date>` (once per day, so re-running
the same day does not pile up backups), and both are idempotent: installing the same source
twice, or uninstalling something already gone, changes nothing further and prints what it
finds instead of erroring.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import pathlib
import re
import shutil
import subprocess

HOME = pathlib.Path.home()
PLUGINS_DIR = HOME / ".claude" / "plugins"

GITHUB_SHORTHAND_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
HEX_HASH_RE = re.compile(r"^[0-9a-f]{32,64}$", re.I)
# Files under ~/.claude/plugins that are never themselves a "file-hash manifest", so
# _find_hash_manifest does not mistake the registries (or a plugin's own descriptor) for one.
_NOT_A_HASH_MANIFEST = {"known_marketplaces.json", "installed_plugins.json",
                          "plugin-catalog-cache.json", "blocklist.json",
                          "plugin.json", "marketplace.json"}


class InstallError(ValueError):
    pass


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _load_json(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise InstallError(f"{path}: {e}") from e


def _write_json(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _backup(path: pathlib.Path, *, today: str | None = None) -> str | None:
    """Copy `path` to `path.bak-<date>` if it exists and today's backup is not already there."""
    if not path.exists():
        return None
    today = today or _dt.date.today().isoformat()
    bak = path.with_name(f"{path.name}.bak-{today}")
    if not bak.exists():
        shutil.copy2(path, bak)
    return str(bak)


def _git_sha(repo_dir: pathlib.Path) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
                            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


# --- resolving <source> --------------------------------------------------------

def resolve_source(source: str, *, marketplaces_dir: pathlib.Path) -> tuple[pathlib.Path, dict]:
    """(local directory holding .claude-plugin/marketplace.json, the `source` dict to write
    into known_marketplaces.json). A local path is used as-is; "owner/repo" is git-cloned
    (or fast-forward pulled, if already cloned) into `marketplaces_dir`."""
    p = pathlib.Path(source).expanduser()
    if p.is_dir():
        return p.resolve(), {"source": "directory", "path": str(p.resolve())}
    if GITHUB_SHORTHAND_RE.match(source):
        if shutil.which("git") is None:
            raise InstallError(f"{source!r} looks like a GitHub repo but no `git` binary is on PATH; "
                                f"clone it by hand and pass the local path to `teyla plugin install` instead")
        dest = marketplaces_dir / source.split("/")[-1]
        if dest.exists():
            subprocess.run(["git", "-C", str(dest), "pull", "--ff-only"],
                            capture_output=True, text=True, timeout=60)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(["git", "clone", f"https://github.com/{source}", str(dest)],
                                capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                raise InstallError(f"git clone {source} failed: {r.stderr.strip()}")
        return dest.resolve(), {"source": "github", "repo": source}
    raise InstallError(f"{source!r} is neither an existing directory nor an owner/repo GitHub shorthand")


# --- the hash manifest: mirrored only if one already exists --------------------

def _find_hash_manifest(root: pathlib.Path) -> pathlib.Path | None:
    """A JSON file under `root` shaped like `{path: hex-hash, ...}` — a file-hash manifest —
    other than the registries and standard plugin/marketplace descriptors. None found means
    this machine's harness version does not write one; install() then skips that step rather
    than guessing a format."""
    if not root.is_dir():
        return None
    for p in sorted(root.rglob("*.json")):
        if p.name in _NOT_A_HASH_MANIFEST:
            continue
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(data, dict) and data and all(isinstance(v, str) and HEX_HASH_RE.match(v) for v in data.values()):
            return p
    return None


def _hash_tree(plugin_dir: pathlib.Path) -> dict:
    return {str(f.relative_to(plugin_dir)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(plugin_dir.rglob("*")) if f.is_file()}


# --- install / uninstall --------------------------------------------------------

def install(source: str, *, plugins_dir: pathlib.Path | None = None) -> list[str]:
    plugins_dir = plugins_dir or PLUGINS_DIR
    known_path = plugins_dir / "known_marketplaces.json"
    installed_path = plugins_dir / "installed_plugins.json"
    marketplaces_dir = plugins_dir / "marketplaces"
    cache_dir = plugins_dir / "cache"

    local_root, source_dict = resolve_source(source, marketplaces_dir=marketplaces_dir)
    manifest_path = local_root / ".claude-plugin" / "marketplace.json"
    if not manifest_path.exists():
        raise InstallError(f"{local_root}: no .claude-plugin/marketplace.json — not a plugin marketplace")
    manifest = _load_json(manifest_path)
    marketplace_name = manifest.get("name") or local_root.name
    plugin_entries = manifest.get("plugins") or []
    if not plugin_entries:
        raise InstallError(f"{manifest_path}: lists no plugins")

    lines = []
    for p in (known_path, installed_path):
        bak = _backup(p)
        if bak:
            lines.append(f"backed up {p} -> {bak}")

    known = _load_json(known_path)
    installed = _load_json(installed_path)
    installed.setdefault("version", 2)
    installed.setdefault("plugins", {})

    now = _now()
    sha = _git_sha(local_root)
    hash_manifest_src = _find_hash_manifest(plugins_dir)

    known[marketplace_name] = {"source": source_dict, "installLocation": str(local_root), "lastUpdated": now}
    lines.append(f"wrote known_marketplaces.json[{marketplace_name!r}]")

    for entry in plugin_entries:
        plugin_name = entry["name"]
        plugin_dir = (local_root / entry.get("source", "./")).resolve()
        version = _load_json(plugin_dir / ".claude-plugin" / "plugin.json").get("version") or "0.0.0"
        cache_path = cache_dir / marketplace_name / plugin_name / version
        if cache_path.exists():
            shutil.rmtree(cache_path)
        shutil.copytree(plugin_dir, cache_path)
        lines.append(f"copied {plugin_dir} -> {cache_path}")

        key = f"{plugin_name}@{marketplace_name}"
        existing_rows = installed["plugins"].get(key) or [{}]
        installed_at = existing_rows[0].get("installedAt") or now
        row = {"scope": "user", "installPath": str(cache_path), "version": version,
               "installedAt": installed_at, "lastUpdated": now}
        if sha:
            row["gitCommitSha"] = sha
        installed["plugins"][key] = [row]
        lines.append(f"wrote installed_plugins.json[{key!r}]")

        if hash_manifest_src is not None:
            out = cache_path / hash_manifest_src.name
            _write_json(out, _hash_tree(cache_path))
            lines.append(f"wrote hash manifest {out} (mirrored the shape of {hash_manifest_src})")
        else:
            lines.append("no file-hash manifest format found on this machine — skipped")

    _write_json(known_path, known)
    _write_json(installed_path, installed)
    return lines


def uninstall(name: str, *, plugins_dir: pathlib.Path | None = None, remove_cache: bool = True) -> list[str]:
    plugins_dir = plugins_dir or PLUGINS_DIR
    installed_path = plugins_dir / "installed_plugins.json"
    installed = _load_json(installed_path)
    plugins = installed.get("plugins", {})

    matches = [k for k in plugins if k == name or k.split("@", 1)[0] == name]
    if not matches:
        return [f"{name}: not installed — nothing to do"]

    lines = []
    bak = _backup(installed_path)
    if bak:
        lines.append(f"backed up {installed_path} -> {bak}")

    for key in matches:
        rows = plugins.pop(key)
        lines.append(f"removed installed_plugins.json[{key!r}]")
        if remove_cache:
            for row in rows:
                p = row.get("installPath")
                if p and pathlib.Path(p).is_dir():
                    shutil.rmtree(p)
                    lines.append(f"removed {p}")

    _write_json(installed_path, installed)
    return lines


# --- CLI -------------------------------------------------------------------------

def cmd_plugin(args):
    if args.action == "install":
        for line in install(args.arg):
            print(line)
    else:
        for line in uninstall(args.arg):
            print(line)


def register(sp):
    """Add `teyla plugin install|uninstall` to an argparse subparsers object."""
    q = sp.add_parser("plugin", help="install/uninstall a Claude Code plugin by hand-editing its registry (no `claude` CLI needed)")
    q.set_defaults(fn=cmd_plugin)
    q.add_argument("action", choices=["install", "uninstall"])
    q.add_argument("arg", help="install: a local path or owner/repo; uninstall: a plugin name or name@marketplace")
    return q
