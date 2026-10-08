"""`teyla plugin install|uninstall` — the no-CLI install path.

Written for machines where Claude Code runs as the desktop app and there is no `claude` binary
on PATH, so `claude plugin marketplace add` / `claude plugin install` cannot run at all. The
only way to install is then to clone the repo into the marketplace directory and hand-write
the registry JSON files, which is not a documented path. This module is that hand-editing,
made safe and reversible.

What the harness actually keeps, as inspected in `~/.claude/plugins/`:

    known_marketplaces.json    {marketplace: {source: {...}, installLocation, lastUpdated}}
    installed_plugins.json     {"version": 2, "plugins": {"<name>@<marketplace>": [
                                    {scope, installPath, version, installedAt, lastUpdated,
                                     gitCommitSha}]}}
    cache/<marketplace>/<plugin>/<version>/     a copy of the plugin directory — the thing
                                                 the harness actually loads, distinct from a
                                                 `directory`-source marketplace's own working
                                                 tree, which is used in place and never copied.

No separate file-hash manifest exists in either registry file or anywhere under
`~/.claude/plugins` in the versions inspected (a harness version may add one, so there is
none to copy the shape of). `install()` looks for one — a JSON file
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

Safe mode (`safe.enabled`, TEYLA_SAFE=1) edits no registry file: a managed laptop may restrict
marketplaces through Claude Code's own settings, and a hand-written registry row goes around
that. install/refresh/uninstall then print the `claude plugin ...` (or in-app `/plugin ...`)
commands to run instead, and nothing is cloned.

Safe mode with `update.pin` set to a release (`0.15.0`) also pins the *plugin*: the hooks run
shell code at every session start and before every tool call, so on a pinned machine they must
not be newer than the CLI. The marketplace is then added as `zaitsew/teyla#v<pin>` (Claude Code
takes `#ref` for a branch or tag, not a commit), and a mismatch is fixed by removing and
re-adding it at that tag; `marketplace update` would pull main. A pin that is a commit sha
cannot be expressed that way, so the source stays unpinned and doctor warns. See `pin_ref`.

Every `rmtree` here is of a path under ~/.claude/plugins/cache, checked first: an
`installPath` read from installed_plugins.json, or a version string read from a cloned
plugin.json, is data, and `"../../.."` in either must not become a recursive delete.

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


def _inside(root: pathlib.Path, path) -> bool:
    try:
        pathlib.Path(path).resolve().relative_to(pathlib.Path(root).resolve())
    except ValueError:
        return False
    return pathlib.Path(path).resolve() != pathlib.Path(root).resolve()


def _rmtree_in_cache(plugins_dir: pathlib.Path, path) -> bool:
    """rmtree `path` only if it lies strictly inside `<plugins_dir>/cache`. False = refused."""
    if not _inside(plugins_dir / "cache", path):
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True


def _safe() -> bool:
    from . import config
    return config.safe_mode()


TEYLA_REPO = "zaitsew/teyla"
_RELEASE_PIN_RE = re.compile(r"^v?\d+(\.\d+)*$")


def pin_ref(cfg: dict | None = None) -> str | None:
    """`v<pin>`, the git tag the plugin's marketplace should be pinned to — only in safe mode
    with `update.pin` set to a release version. A sha, or no pin, is None."""
    from . import config, update
    if not config.safe_mode(cfg):
        return None
    pin = update.update_settings(cfg)[1]
    if not pin or not _RELEASE_PIN_RE.match(pin):
        return None
    return pin if pin.startswith("v") else f"v{pin}"


def pin_is_sha(cfg: dict | None = None) -> bool:
    """Safe mode with `update.pin` a commit sha: the plugin cannot follow it (a marketplace
    `ref` is a branch or tag)."""
    from . import config, update
    if not config.safe_mode(cfg):
        return False
    pin = update.update_settings(cfg)[1]
    return bool(pin) and update.pin_is_sha(pin)


def pinned_source(ref: str) -> str:
    return f"{TEYLA_REPO}#{ref}"


def repin_command(ref: str) -> str:
    """Remove the teyla marketplace (which uninstalls its plugin) and add it back at `ref`."""
    steps = ["plugin marketplace remove teyla", f"plugin marketplace add {pinned_source(ref)}", "plugin install teyla@teyla"]
    return " && ".join(f"claude {c}" for c in steps)


def marketplace_ref(name: str = "teyla", *, plugins_dir: pathlib.Path | None = None) -> tuple[bool, str | None, str]:
    """(found, ref, kind) for marketplace `name` in known_marketplaces.json: `ref` is the git
    ref its source pins (None = the default branch), `kind` the source type. Missing or garbled
    file, or no such marketplace: found is False."""
    path = (plugins_dir or PLUGINS_DIR) / "known_marketplaces.json"
    try:
        row = json.loads(path.read_text()).get(name)
        src = row.get("source")
    except (OSError, ValueError, AttributeError):
        return False, None, ""
    if isinstance(src, str):
        return True, None, src
    if not isinstance(src, dict):
        return False, None, ""
    ref = src.get("ref")
    return True, ref if isinstance(ref, str) and ref else None, str(src.get("source") or "?")


def _claude_commands(*cmds: str) -> list[str]:
    head = "safe mode: the plugin registry is not edited by hand. Run instead"
    if shutil.which("claude"):
        return [head + ":"] + [f"  claude {c}" for c in cmds]
    return [head + " (no `claude` on PATH — type them in a Claude Code session):"] + [f"  /{c}" for c in cmds]


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
        from . import net
        if not net.allowed():
            raise InstallError(net.refusal(f"cloning {source}"))
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

def safe_install_commands(source: str) -> list[str]:
    """The `claude plugin` commands that do what install() would, for safe mode. A local
    marketplace names its plugins; a GitHub one is not cloned to find out, so the repo name is
    assumed for both the marketplace and the plugin (true of zaitsew/teyla)."""
    p = pathlib.Path(source).expanduser()
    manifest = p / ".claude-plugin" / "marketplace.json"
    if p.is_dir() and manifest.exists():
        m = _load_json(manifest)
        mkt = m.get("name") or p.name
        names = [e["name"] for e in m.get("plugins") or [] if e.get("name")] or [p.name]
        src = str(p.resolve())
    else:
        mkt = source.rstrip("/").split("/")[-1]
        names, src = [mkt], source
        ref = pin_ref()
        if ref and source.lower() == TEYLA_REPO:
            src = pinned_source(ref)
            # `marketplace add` refuses a name that is already registered, which would
            # leave an unpinned (or other-tag) marketplace in place (Codex review, P2).
            found, cur, _kind = marketplace_ref(mkt)
            if found and cur != ref:
                return _claude_commands(f"plugin marketplace remove {mkt}", f"plugin marketplace add {src}",
                                        *(f"plugin install {n}@{mkt}" for n in names))
    return _claude_commands(f"plugin marketplace add {src}", *(f"plugin install {n}@{mkt}" for n in names))


def install(source: str, *, plugins_dir: pathlib.Path | None = None) -> list[str]:
    if _safe():
        return safe_install_commands(source)
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
        if not _inside(cache_dir, cache_path):
            raise InstallError(f"{marketplace_name}/{plugin_name}/{version} resolves outside {cache_dir} — refusing")
        if cache_path.exists():
            _rmtree_in_cache(plugins_dir, cache_path)
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
    if _safe():
        return _claude_commands(f"plugin uninstall {name}")
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
                    if _rmtree_in_cache(plugins_dir, p):
                        lines.append(f"removed {p}")
                    else:
                        lines.append(f"kept {p}: installPath is not under {plugins_dir / 'cache'}; remove it by hand if it is yours")

    _write_json(installed_path, installed)
    return lines


# --- CLI -------------------------------------------------------------------------

def refresh(*, plugins_dir: pathlib.Path | None = None, force: bool = False) -> list[str]:
    """Bring the installed Claude Code plugin copy up to the version shipped with this package.

    The harness loads a *copy* under ~/.claude/plugins/cache/<marketplace>/teyla/<version>/;
    it never re-reads the marketplace on its own. After `teyla update` the CLI is new but the
    hooks and skills in that copy are the old ones — until this runs. Works with or without
    the `claude` binary: it rewrites the same registry rows `install()` writes."""
    import teyla
    plugins_dir = plugins_dir or PLUGINS_DIR
    installed_path = plugins_dir / "installed_plugins.json"
    installed = _load_json(installed_path)
    plugins = installed.get("plugins", {})
    keys = [k for k in plugins if k.split("@", 1)[0] == "teyla"]
    if not keys:
        return ["teyla plugin not installed — `teyla plugin install zaitsew/teyla` "
                "(or `claude plugin marketplace add zaitsew/teyla && claude plugin install teyla@teyla`)"]
    src = teyla.plugin_dir()
    version = _load_json(src / ".claude-plugin" / "plugin.json").get("version") or "0.0.0"
    if _safe():
        stale = [k for k in keys if (plugins[k] or [{}])[0].get("version") != version or force]
        ref = pin_ref()
        # The right version on the wrong ref is still stale: the next marketplace update
        # would pull main (Codex review, P2).
        if ref and "teyla@teyla" in keys and "teyla@teyla" not in stale:
            found, cur, _kind = marketplace_ref("teyla")
            if found and cur != ref:
                stale.append("teyla@teyla")
        if not stale:
            return [f"{k}: already {version}" for k in keys]
        if ref and "teyla@teyla" in stale:
            # `marketplace update` would pull main; re-add the marketplace at the pinned tag.
            return _claude_commands("plugin marketplace remove teyla", f"plugin marketplace add {pinned_source(ref)}",
                                    "plugin install teyla@teyla")
        mkts = sorted({k.split("@", 1)[1] for k in stale})
        return _claude_commands(*(f"plugin marketplace update {m}" for m in mkts), *(f"plugin update {k}" for k in stale))
    lines = []
    for key in keys:
        rows = plugins[key]
        row = rows[0] if rows else {}
        if row.get("version") == version and not force:
            lines.append(f"{key}: already {version}")
            continue
        marketplace_name = key.split("@", 1)[1]
        cache_path = plugins_dir / "cache" / marketplace_name / "teyla" / version
        bak = _backup(installed_path)
        if bak:
            lines.append(f"backed up {installed_path} -> {bak}")
        if not _inside(plugins_dir / "cache", cache_path):
            lines.append(f"{key}: {cache_path} resolves outside {plugins_dir / 'cache'} — skipped")
            continue
        if cache_path.exists():
            _rmtree_in_cache(plugins_dir, cache_path)
        shutil.copytree(src, cache_path)
        old = row.get("installPath")
        if old and pathlib.Path(old).is_dir() and pathlib.Path(old) != cache_path:
            if not _rmtree_in_cache(plugins_dir, old):
                lines.append(f"{key}: kept old installPath {old} — not under {plugins_dir / 'cache'}")
        new_row = dict(row)
        new_row.update({"installPath": str(cache_path), "version": version, "lastUpdated": _now(),
                        "installedAt": row.get("installedAt") or _now(), "scope": row.get("scope", "user")})
        plugins[key] = [new_row]
        lines.append(f"{key}: {row.get('version') or '?'} -> {version} ({cache_path})")
    _write_json(installed_path, installed)
    return lines


def installed_version(*, plugins_dir: pathlib.Path | None = None) -> str | None:
    plugins_dir = plugins_dir or PLUGINS_DIR
    installed = _load_json(plugins_dir / "installed_plugins.json") if (plugins_dir / "installed_plugins.json").exists() else {}
    for k, rows in installed.get("plugins", {}).items():
        if k.split("@", 1)[0] == "teyla" and rows:
            return rows[0].get("version")
    return None


def cmd_plugin(args):
    if args.action == "install":
        for line in install(args.arg):
            print(line)
    elif args.action == "refresh":
        for line in refresh(force=getattr(args, "force", False)):
            print(line)
    else:
        for line in uninstall(args.arg):
            print(line)


def register(sp):
    """Add `teyla plugin install|uninstall` to an argparse subparsers object."""
    q = sp.add_parser("plugin", help="install/uninstall a Claude Code plugin by hand-editing its registry (no `claude` CLI needed)")
    q.set_defaults(fn=cmd_plugin)
    q.add_argument("action", choices=["install", "uninstall", "refresh"])
    q.add_argument("arg", nargs="?", help="install: a local path or owner/repo; uninstall: a plugin name or name@marketplace; refresh: none")
    q.add_argument("--force", action="store_true", help="refresh: re-copy even when the version already matches")
    return q
