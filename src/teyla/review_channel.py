"""The Mac side of the shared review channel (`packages/review-channel/`, docs/REVIEW.md "The shared channel").

    teyla review pull --channel [--json]        move ready captures from the server into the inbox
    teyla review channel key add <product> [--rotate]
    teyla review channel key revoke <product>
    teyla review channel key path <product>
    teyla review channel install | uninstall    an hourly LaunchAgent that runs the pull

Config, `~/.teyla/review-channel.toml`:

    ssh  = "user@host"          # the box that runs the service
    root = "/path/to/data"      # its data directory: ready/, incoming/, keys/keys.txt

The pull copies `ready/` over rsync into a private temp folder and hands each capture to the inbox the way
`--vouched-folder` does, with `source` set to `channel`: nobody vouched for the sender, and `teyla review list`
says so. Then it deletes from the server exactly the folders the inbox now holds. A capture the inbox
refused stays on the server and the run exits 1. New captures raise one macOS notification that carries
only their number. A comment is a tester's text: this command never prints one.

Every remote command is built from a product slug and a UUID that matched a regex first, and from the
two config values, which are checked against a regex when they are read.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib

from . import config, net, review, routine_install as ri
from .control import state as control

LABEL = "com.zaitsew.teyla.review-channel"
EVERY_SECONDS = 3600
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SSH_TARGET = re.compile(r"^(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9][A-Za-z0-9.-]*$")
ROOT = re.compile(r"^/[A-Za-z0-9._@+=,:/-]*$")
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20"]
DELETE_BATCH = 40
EXAMPLE = 'ssh  = "user@host"\nroot = "/path/to/data"'


class ChannelError(Exception):
    """A message for the person, printed once; the command exits 2 (setup) or 1 (the remote failed)."""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


# --- config and keys ----------------------------------------------------------------------------

def config_path() -> pathlib.Path:
    return control.home() / "review-channel.toml"


def key_dir() -> pathlib.Path:
    return pathlib.Path.home() / ".config" / "teyla" / "review-channel"


def key_path(product: str) -> pathlib.Path:
    return key_dir() / f"{product}.key"


def load_config() -> dict:
    path = config_path()
    if not path.is_file():
        raise ChannelError(f"the review channel is not set up: {path} is missing. Create it with two lines:\n{EXAMPLE}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ChannelError(f"{path} cannot be read ({e})") from None
    ssh, root = raw.get("ssh"), raw.get("root")
    missing = [k for k, v in (("ssh", ssh), ("root", root)) if not isinstance(v, str) or not v]
    if missing:
        raise ChannelError(f"{path} is missing {' and '.join(missing)}. It needs:\n{EXAMPLE}")
    if not SSH_TARGET.match(ssh):
        raise ChannelError(f"{path}: ssh must look like user@host (letters, digits, dot and dash only)")
    if not ROOT.match(root) or ".." in root.split("/") or len(root) < 2:
        raise ChannelError(f"{path}: root must be an absolute path without spaces, quotes or '..'")
    return {"ssh": ssh, "root": root.rstrip("/")}


def _slug(word: str) -> str:
    if not SLUG.match(word or ""):
        raise ChannelError(f"'{word}' is not a product slug (lowercase letters, digits and dashes, at most 40)")
    return word


# --- the remote ---------------------------------------------------------------------------------

class Remote:
    """The server over SSH and rsync. Nothing is run through a local shell."""

    def __init__(self, ssh: str, root: str):
        self.ssh, self.root = ssh, root

    def run(self, command: str, timeout: int = 120) -> subprocess.CompletedProcess:
        return subprocess.run(["ssh", *SSH_OPTS, "--", self.ssh, command], capture_output=True, text=True, timeout=timeout)

    def fetch(self, dest: pathlib.Path) -> subprocess.CompletedProcess:
        """Copy `ready/` into `dest`. Symlinks are not copied (no -l), and a file over 11 MB is left behind."""
        src = f"{self.ssh}:{shlex.quote(self.root + '/ready/')}"
        return subprocess.run(["rsync", "-rt", "--max-size=11M", "--timeout=60", "-e", "ssh " + " ".join(SSH_OPTS),
                               src, str(dest) + "/"], capture_output=True, text=True, timeout=600)

    def ready_path(self, slug: str, cid: str) -> str:
        if not SLUG.match(slug) or not UUID.match(cid):
            raise ValueError("not a capture path")
        return f"{self.root}/ready/{slug}/{cid}"

    def delete(self, items: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Remove exactly these ready folders. Returns the ones a failed batch left behind."""
        left: list[tuple[str, str]] = []
        for i in range(0, len(items), DELETE_BATCH):
            batch = items[i:i + DELETE_BATCH]
            cmd = "rm -rf -- " + " ".join(shlex.quote(self.ready_path(s, c)) for s, c in batch)
            try:
                ok = self.run(cmd).returncode == 0
            except (OSError, subprocess.SubprocessError):
                ok = False
            if not ok:
                left += batch
        return left

    def keys_edit(self, slug: str, line: str | None) -> subprocess.CompletedProcess:
        """Replace the product's line in keys/keys.txt (or drop it when `line` is None) by writing a new
        file beside it and renaming over it."""
        d = shlex.quote(f"{self.root}/keys")
        add = f"echo {shlex.quote(line)}; " if line else ""
        # mkdir is the lock: without one, an add that read the file before a revoke could restore the revoked key.
        cmd = (f'd={d}; f="$d/keys.txt"; l="$d/.keys.lock"; n=0; '
               f'until mkdir "$l" 2>/dev/null; do n=$((n+1)); [ "$n" -ge 20 ] && exit 75; sleep 1; done; '
               f'trap \'rmdir "$l"\' EXIT; t=$(mktemp "$d/.keys.XXXXXX") && '
               f'{{ if [ -f "$f" ]; then grep -v -e " {slug}$" "$f"; fi; {add}true; }} > "$t" && '
               f'chmod 644 "$t" && mv -f "$t" "$f" || {{ rm -f "$t"; exit 1; }}')
        return self.run(cmd, timeout=60)


# --- the pull -----------------------------------------------------------------------------------

def notice_script(count: int) -> str:
    """Only the number: a comment is a tester's text and a banner shows on a locked screen."""
    what = "1 new tester capture" if count == 1 else f"{count} new tester captures"
    return f'display notification "{what}: teyla review list" with title "Teyla"'


def notify(count: int) -> None:
    """A capture is already safe in the inbox, so a banner that fails must not fail the pass."""
    if sys.platform != "darwin" or not shutil.which("osascript"):
        return
    try:
        subprocess.run(["osascript", "-e", notice_script(count)], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def _declared_product(folder: pathlib.Path) -> str | None:
    j = folder / "capture.json"
    if review._plain_file(j, review.MAX_JSON) is None:
        return None
    try:
        app = json.loads(j.read_text(encoding="utf-8")).get("app")
    except (OSError, ValueError, AttributeError):
        return None
    p = app.get("product") if isinstance(app, dict) else None
    return p if isinstance(p, str) else None


def _discard(path: pathlib.Path) -> None:
    """Drop a temp copy of something the inbox will not take. The server's copy is not touched."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _name(text: str) -> str:
    return ascii(text)[:60]


def pull_remote(conn, remote: Remote, now: float | None = None) -> dict:
    """One pass. {source, added, known, waiting, skipped: [...], imported: [ids], deleted, left, note, error?}."""
    rep: dict = {"source": "channel", "added": 0, "known": 0, "waiting": 0, "skipped": [], "imported": [],
                 "deleted": 0, "left": 0, "note": ""}
    with tempfile.TemporaryDirectory(prefix="teyla-review-channel-") as tmp:
        box = pathlib.Path(tmp) / "ready"
        box.mkdir(mode=0o700)
        try:
            got = remote.fetch(box)
        except (OSError, subprocess.SubprocessError) as e:
            rep.update(error=True, note=f"could not run rsync ({type(e).__name__}); nothing was deleted")
            return rep
        if got.returncode != 0:
            rep.update(error=True, note=f"rsync exited {got.returncode}; nothing was deleted from the server")
            return rep
        held: list[tuple[str, str]] = []
        for sdir in sorted(box.iterdir(), key=lambda p: p.name):
            if sdir.is_symlink() or not sdir.is_dir() or not SLUG.match(sdir.name):
                rep["skipped"].append(f"{_name(sdir.name)}: not a product folder; left on the server")
                continue
            for folder in sorted(sdir.iterdir(), key=lambda p: p.name):
                if folder.is_symlink() or not folder.is_dir() or not UUID.match(folder.name):
                    rep["skipped"].append(f"{sdir.name}/{_name(folder.name)}: not a capture folder; left on the server")
                    _discard(folder)
                    continue
                if _declared_product(folder) != sdir.name:
                    rep["skipped"].append(f"{folder.name}: its app.product is not '{sdir.name}'; left on the server")
                    shutil.rmtree(folder, ignore_errors=True)
            sub = review.pull_vouched(conn, sdir, now, source="channel")
            for k in ("added", "known", "waiting"):
                rep[k] += sub[k]
            rep["skipped"] += sub["skipped"]
            rep["imported"] += sub["imported"]
            held += [(sdir.name, cid) for cid in sub["imported"]]
    # Before the deletes: a run that dies in them finds these captures "known" next time.
    if rep["added"]:
        notify(rep["added"])
    left = remote.delete(held) if held else []
    rep["deleted"] = len(held) - len(left)
    rep["left"] = len(left) + len(rep["skipped"]) + rep["waiting"]
    if left:
        rep["skipped"].append(f"{len(left)} imported capture(s) could not be deleted from the server; the next pass retries")
    return rep


def _print(rep: dict) -> None:
    line = (f"channel: {rep['added']} new, {rep['known']} already known, {rep['deleted']} deleted from the server")
    if rep.get("pruned"):
        line += f", {rep['pruned']} past retention removed here"
    if rep.get("waiting"):
        line += f", {rep['waiting']} incomplete"
    if rep["skipped"]:
        line += f", {len(rep['skipped'])} refused or left"
    print(line + (f" ({rep['note']})" if rep.get("note") else ""))
    for s in rep["skipped"][:10]:
        print(f"  {s}")


def cmd_pull(conn, args) -> int:
    # Before anything that can stop the pass: no config, safe mode and a dead server all leave the Mac's copy to expire.
    pruned = review.prune_channel(conn)
    try:
        cfg = load_config()
    except ChannelError as e:
        print(f"teyla review pull --channel: {e}", file=sys.stderr)
        return e.code
    if not net.gate("the review channel pull (ssh and rsync)"):
        return 1
    rep = pull_remote(conn, Remote(cfg["ssh"], cfg["root"]))
    rep["pruned"] = pruned["deleted"]
    if pruned["kept"]:
        rep["skipped"].append(f"{len(pruned['kept'])} capture(s) past retention could not be removed; the next pass retries")
    if args.json:
        print(json.dumps(rep, ensure_ascii=False))
    else:
        _print(rep)
    return 1 if rep.get("error") or rep["skipped"] or rep["waiting"] else 0


# --- keys ---------------------------------------------------------------------------------------

def _write_secret(path: pathlib.Path, secret: str) -> None:
    config.private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(secret + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


@contextlib.contextmanager
def _key_lock(path: pathlib.Path):
    """One key change per product on this Mac: two rotations must not swap pending secrets, or the
    server ends on a key nobody holds. A second run is refused, not queued: it would rotate again."""
    config.private_dir(path.parent)
    fd = os.open(path.with_name(path.name + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ChannelError(f"another key change for {path.stem} is running; try again when it ends", 1) from None
        yield
    finally:
        os.close(fd)


def key_add(remote: Remote, product: str, rotate: bool = False) -> pathlib.Path:
    path = key_path(_slug(product))
    with _key_lock(path):
        if path.exists() and not rotate:
            raise ChannelError(f"{product} already has a key at {path}. `key revoke {product}` first, or add --rotate", 1)
        secret = secrets.token_urlsafe(32)
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        # Saved first: a rotation whose local write fails must not leave the server on a key nobody holds.
        pending = path.with_name(path.name + ".new")
        _write_secret(pending, secret)
        r = remote.keys_edit(product, f"{digest} {product}")
        if r.returncode != 0:
            pending.unlink(missing_ok=True)
            raise ChannelError(f"the server did not take the key (ssh exited {r.returncode}); nothing was stored here", 1)
        os.replace(pending, path)
    return path


def key_revoke(remote: Remote, product: str) -> None:
    path = key_path(_slug(product))
    with _key_lock(path):
        r = remote.keys_edit(product, None)
        if r.returncode != 0:
            raise ChannelError(f"the server did not drop the key (ssh exited {r.returncode}); the local key was kept", 1)
        path.unlink(missing_ok=True)


# --- the hourly agent ---------------------------------------------------------------------------

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>{wrapper}</string>
    </array>
    <key>StartInterval</key>
    <integer>{interval}</integer>
    <key>EnvironmentVariables</key>
    <dict>
{env_plist}    </dict>
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>Nice</key>
    <integer>10</integer>
</dict>
</plist>
"""

WRAPPER = """#!/usr/bin/env bash
# Written by `teyla review channel install`; `teyla review channel uninstall` removes it. One pass, every hour.
set -uo pipefail
{env_sh}
export TEYLA_IN_ROUTINE="{label}"
echo "— $(date -u +%Y-%m-%dT%H:%MZ) review channel pull"
"{teyla_bin}" review pull --channel
"""


def plist_path() -> pathlib.Path:
    return ri.PLIST_PATH.parent / f"{LABEL}.plist"


def wrapper_path() -> pathlib.Path:
    return ri.WRAPPER_PATH.parent / "review-channel.sh"


def log_path() -> pathlib.Path:
    return ri.LOG_PATH.parent / "teyla-review-channel.log"


def agent_install(*, load=None) -> list[str]:
    load = ri._load if load is None else load
    load_config()                        # an agent that would fail every hour is not worth installing
    teyla_bin = ri._teyla_bin()
    env = ri.launchd_env(teyla_bin)
    wrapper, plist, log = wrapper_path(), plist_path(), log_path()
    for d in (wrapper.parent, plist.parent, log.parent):
        d.mkdir(parents=True, exist_ok=True)
    ri._write(wrapper, WRAPPER.format(env_sh=ri._env_sh(env), label=LABEL, teyla_bin=teyla_bin), 0o755)
    ri._write(plist, PLIST.format(label=LABEL, wrapper=ri._xml(str(wrapper)), interval=EVERY_SECONDS,
                                  log=ri._xml(str(log)), env_plist=ri._env_plist(env)))
    lines = [f"wrote {wrapper}", f"wrote {plist}"]
    lines.append(load(plist, LABEL) if sys.platform == "darwin" else f"not macOS: run `teyla review pull --channel` every hour yourself ({wrapper})")
    return lines


def agent_uninstall(*, unload=None) -> list[str]:
    unload = ri._unload if unload is None else unload
    lines = []
    plist, wrapper = plist_path(), wrapper_path()
    if plist.exists() and sys.platform == "darwin":
        lines.append(unload(plist, LABEL))
    for f in (plist, wrapper):
        if f.exists():
            f.unlink()
            lines.append(f"removed {f}")
    return lines or [f"{LABEL} was not installed"]


# --- the command --------------------------------------------------------------------------------

USAGE = ("teyla review channel: key add <product> [--rotate] | key revoke <product> | key path <product> | install | uninstall")


def cmd_channel(words: list[str], args) -> int:
    try:
        if words[:1] == ["install"] and len(words) == 1:
            print("\n".join(agent_install()))
            return 0
        if words[:1] == ["uninstall"] and len(words) == 1:
            print("\n".join(agent_uninstall()))
            return 0
        if len(words) == 3 and words[0] == "key" and words[1] in ("add", "revoke", "path"):
            verb, product = words[1], _slug(words[2])
            if verb == "path":
                p = key_path(product)
                print(p)
                if not p.is_file():
                    print(f"teyla review channel: no key there yet; run `teyla review channel key add {product}`", file=sys.stderr)
                    return 1
                return 0
            cfg = load_config()
            if not net.gate("the review channel key change (ssh)"):
                return 1
            remote = Remote(cfg["ssh"], cfg["root"])
            if verb == "add":
                print(key_add(remote, product, rotate=bool(getattr(args, "rotate", False))))
            else:
                key_revoke(remote, product)
                print(f"revoked {product}")
            return 0
    except ChannelError as e:
        print(f"teyla review channel: {e}", file=sys.stderr)
        return e.code
    except (OSError, subprocess.SubprocessError) as e:
        print(f"teyla review channel: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(USAGE, file=sys.stderr)
    return 2
