"""`teyla update` — keep this machine's Teyla current, then re-wire what depends on it.

    teyla update            check GitHub for a newer release; install it; run the post-update steps
    teyla update --check    only report (and cache) whether a newer release exists
    teyla update --quiet    one line unless something changed or failed (for the daily routine)

In safe mode (`safe.enabled`, TEYLA_SAFE=1) nothing here touches the network unless the
command line says `--allow-network`; see net.py. The daily routine and the session hook
never pass it, so a work laptop updates only when its owner runs `teyla update --allow-network`.

What gets installed: the latest *published GitHub release* (never a bare `v*` tag), by the
commit its tag resolves to (`git+<repo>@<sha>`), and only if the build then says
`teyla --version` == that release — else the previous version is put back. Tag and sha are
recorded in update-check.json and, after a verified install, in ~/.teyla/installed.json.

    [update] pin     = "0.12.0" | "<sha>"   install exactly that, nothing newer (or older)
    [update] channel = "release" | "none"   none: the daily routine never updates; by hand still works

How the install happened decides how it is upgraded:

    uv tool        ~/.local/share/uv/tools/teyla/...    uv tool install --force --python <X.Y> --reinstall git+<repo>@<sha>
    pipx           .../pipx/venvs/teyla/...             pipx install --force --python <exe> git+<repo>@<sha>
    checkout       <repo>/src/teyla/__init__.py + .git   never touched: the command to pull is printed
    pip            anything else                          python -m pip install --force-reinstall git+<repo>@<sha>

The interpreter is pinned on every self-install: `[update] python` from config if set, else
the one running now. Without that, uv rebuilt the tool environment on its *default*
interpreter and an install that had been moved to 3.12 (because 3.13's strict X.509
verification rejects a corporate proxy's root CA) landed back on 3.13 after the very update
it had just made possible.

The GitHub call verifies TLS through `truststore` (the OS trust store: keychain, Windows
store) when that package is importable, else through OpenSSL's default context, which honours
SSL_CERT_FILE / SSL_CERT_DIR — and those may come from config.toml [env], applied at startup.

Post-update, in order, each idempotent and each reported:
    policy sync         harness wiring (import line, symlinks, Hermes section)
    policy refresh      three-way merge of template changes into ~/.agents/POLICY.md
                        (safe mode: only proposed, in ~/.teyla/policy-proposed.md)
    plugin refresh      the Claude Code plugin cache copy, if the installed one is older
    harness sync        the skills and hooks in Cursor, Codex, Grok and Hermes
    routine install     the launchd wrappers, if they point at a binary that moved
    doctor              the summary line the session hook shows

Nothing here edits a repo. Repo-level AGENTS.md/CLAUDE.md links are reported by doctor
and created only by an explicit `teyla policy sync-repo <path>`.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

from . import __version__, config, net

CHECK_PATH = config.TEYLA_DIR / "update-check.json"


# --- interpreter and trust: the two things a self-update must not lose -----------------

def python_spec(cfg: dict | None = None) -> str:
    """The interpreter to pin: `[update] python` from config, else the running one's X.Y."""
    pinned = ((cfg or config.load()).get("update") or {}).get("python")
    return str(pinned) if pinned else f"{sys.version_info.major}.{sys.version_info.minor}"


def python_executable_for(spec: str) -> str:
    """A concrete interpreter for pipx's --python: the running interpreter's base (outside the
    venv) when it matches `spec`, else `python<spec>` for PATH lookup."""
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    if spec == running:
        base = pathlib.Path(sys.base_prefix) / "bin" / f"python{running}"
        if base.exists():
            return str(base)
    return f"python{spec}"


def _explicit_bundle() -> str | None:
    for var in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        if os.environ.get(var):
            return var
    return None


def trust_source() -> str:
    """One phrase for doctor: where TLS roots come from for Python's HTTPS here. An explicit
    SSL_CERT_FILE/SSL_CERT_DIR (possibly from config.toml [env]) wins over truststore: the
    person who set it chose that bundle on purpose."""
    var = _explicit_bundle()
    if var:
        return f"{var}={os.environ[var]}"
    try:
        import truststore  # noqa: F401
        return "truststore (OS trust store)"
    except ImportError:
        pass
    import ssl
    paths = ssl.get_default_verify_paths()
    return f"openssl default {paths.cafile or paths.capath or '(none found)'}"


def truststore_available() -> bool:
    try:
        import truststore  # noqa: F401
        return True
    except ImportError:
        return False


# `pip install 'teyla[work]'` is Teyla plus truststore: the OS keychain, which on a managed Mac
# already holds the TLS-inspecting proxy's root CA, so no SSL_CERT_FILE has to be exported.
WORK_EXTRA_HINT = ("behind a proxy without truststore: reinstall with the work extra so Python uses the OS "
                   "keychain — uv tool install --force 'teyla[work] @ git+https://github.com/zaitsew/teyla'")


def ssl_context():
    import ssl
    if _explicit_bundle():
        return ssl.create_default_context()
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return ssl.create_default_context()


def proxy_in_use() -> str | None:
    """The HTTPS proxy urllib will use: environment first (HTTPS_PROXY / https_proxy, which on a
    managed Mac an MDM profile may set outside any shell rc), then the system settings."""
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        if os.environ.get(var):
            return os.environ[var]
    try:
        p = urllib.request.getproxies()
    except Exception:  # noqa: BLE001 — system config lookup is best effort
        return None
    return p.get("https") or p.get("http") or None


def explain_tls_error(note: str | None) -> str | None:
    """A hint for the two failure shapes a TLS-inspecting proxy produces, or None."""
    if not note:
        return None
    if "Basic Constraints of CA cert not marked critical" in note:
        return ("Python 3.13+ verifies X.509 strictly and rejects this proxy root CA no matter which bundle it is "
                "handed; pin an older interpreter: teyla config set update.python=3.12 && teyla update --force")
    if "CERTIFICATE_VERIFY_FAILED" in note:
        return ("Python does not trust the certificate chain (git/curl may, via the OS keychain). Point it at a "
                "bundle that includes the proxy's root CA: teyla config set env.SSL_CERT_FILE=/path/to/bundle.pem; "
                "or install the work extra (truststore, the OS keychain): "
                "uv tool install --force 'teyla[work] @ git+https://github.com/zaitsew/teyla'")
    return None


def _vtuple(v: str) -> tuple:
    out = []
    for part in v.lstrip("v").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


def is_newer(latest: str | None, installed: str = __version__) -> bool:
    return bool(latest) and _vtuple(latest) > _vtuple(installed)


def install_method() -> tuple[str, pathlib.Path | None]:
    """('uv-tool'|'pipx'|'checkout'|'pip', checkout root or None)."""
    here = pathlib.Path(__file__).resolve()
    s = str(here)
    if "/uv/tools/teyla/" in s or "\\uv\\tools\\teyla\\" in s:
        return "uv-tool", None
    if "/pipx/venvs/teyla/" in s:
        return "pipx", None
    for cand in (here.parents[2], here.parents[1]):
        if (cand / ".git").exists() and (cand / "pyproject.toml").exists():
            return "checkout", cand
    return "pip", None


def latest_release(repo: str, timeout: int = 10) -> tuple[str | None, str]:
    tag, note, _ = lookup_release(repo, timeout)
    return tag, note


def _get_json(url: str, timeout: int = 10):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"teyla/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:
        return json.loads(r.read().decode())


def lookup_release(repo: str, timeout: int = 10, tag: str | None = None) -> tuple[str | None, str, bool]:
    """(tag or None, note, reachable) of the latest published release — or of release `tag`,
    when given. Only a release counts: a `v*` tag anyone with push access can create or move
    is not something to install unattended. `reachable` is True when GitHub answered at all —
    a repo with no release yet is reachable, not down."""
    endpoint = f"releases/tags/{tag}" if tag else "releases/latest"
    url = f"https://api.github.com/repos/{repo}/{endpoint}"
    try:
        data = _get_json(url, timeout)
    except urllib.error.HTTPError as e:
        return None, f"{endpoint}: {e}", True  # 404 just means no (such) release
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        return None, f"{endpoint}: {e}", False
    found = data.get("tag_name") if isinstance(data, dict) else None
    if not found or data.get("draft"):
        return None, f"{endpoint}: no published release", True
    return found, endpoint, True


def resolve_sha(repo: str, ref: str, timeout: int = 10) -> str | None:
    """The commit a tag points at right now. Installing `@<sha>` instead of `@<tag>` means the
    code that lands is the code that was looked up, even if the tag moves in between."""
    try:
        data = _get_json(f"https://api.github.com/repos/{repo}/commits/{ref}", timeout)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    sha = data.get("sha") if isinstance(data, dict) else None
    return sha if isinstance(sha, str) and _SHA_RE.match(sha) else None


_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def update_settings(cfg: dict | None = None) -> tuple[str, str | None]:
    """(channel, pin). channel: "release" (default) or "none" (never updated by a routine or
    the session hook; `teyla update` by hand still works). pin: a version (`0.12.0`, `v0.12.0`)
    or a commit sha; updates then install exactly that and nothing newer."""
    u = (cfg or config.load()).get("update") or {}
    channel = str(u.get("channel") or "release").strip().lower()
    pin = str(u.get("pin") or "").strip() or None
    return channel, pin


def pin_is_sha(pin: str) -> bool:
    return bool(_SHA_RE.match(pin.lower())) and not re.match(r"^v?\d+(\.\d+)*$", pin)


INSTALLED_PATH = config.TEYLA_DIR / "installed.json"


# Run in a fresh interpreter: the commit uv/pip/pipx recorded for the installed `teyla`
# distribution (PEP 610 direct_url.json, `vcs_info.commit_id`), or nothing.
_COMMIT_PROBE = ("import json, importlib.metadata as m\n"
                 "try:\n    d = json.loads(m.distribution('teyla').read_text('direct_url.json') or '{}')\n"
                 "except Exception:\n    d = {}\n"
                 "print((d.get('vcs_info') or {}).get('commit_id') or '')")


def _as_sha(text: str | None) -> str | None:
    s = (text or "").strip().lower()
    return s if _SHA_RE.match(s) else None


def same_commit(a: str | None, b: str | None) -> bool:
    """A pin may be a short sha; the installer records the full one."""
    a, b = _as_sha(a), _as_sha(b)
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def _dist_commit() -> str | None:
    """The commit the running `teyla` was installed from, as its installer recorded it."""
    try:
        from importlib import metadata
        d = json.loads(metadata.distribution("teyla").read_text("direct_url.json") or "{}")
    except Exception:  # noqa: BLE001 — no distribution (PYTHONPATH run), no or bad direct_url.json
        return None
    return _as_sha((d.get("vcs_info") or {}).get("commit_id")) if isinstance(d, dict) else None


def installed_sha() -> str | None:
    """The commit the running version was installed from: what its installer recorded
    (direct_url.json), else what `teyla update` recorded after a verified install of this
    version. None when neither knows — a pin then counts as not met: the same version number
    says nothing about which commit it was built from (review of #64, P1)."""
    found = _dist_commit()
    if found:
        return found
    try:
        rec = json.loads(INSTALLED_PATH.read_text())
    except (OSError, ValueError):
        return None
    return _as_sha(rec.get("sha")) if rec.get("version") == __version__ else None


def _record_installed(version: str, tag: str | None, sha: str) -> None:
    try:
        INSTALLED_PATH.parent.mkdir(parents=True, exist_ok=True)
        INSTALLED_PATH.write_text(json.dumps({"version": version, "tag": tag, "sha": sha}, indent=2) + "\n")
    except OSError:
        pass


FAIL_MAX_AGE_MIN = 15  # a failed lookup is retried after this long; only a success is good for max_age_hours


def _wanted(tag: str | None, sha: str | None, pin: str | None) -> bool:
    """Is there something to install? Unpinned: a newer release. Pinned: anything other than
    exactly the pin — which may be older than what runs now; that is what freezing means."""
    if not pin:
        return is_newer(tag, __version__)
    if tag and not sha:
        return _vtuple(tag) != _vtuple(__version__)  # nothing to compare commits with; install would refuse anyway
    # By commit, never by version: a build of main that says 0.12.0 is not release v0.12.0,
    # and an install whose commit is unknown is not known to be the pin (review of #64, P1).
    return bool(sha) and not same_commit(installed_sha(), sha)


def check(repo: str | None = None, refresh: bool = True, max_age_hours: int = 24) -> dict:
    """Cached lookup of the latest release. Writes ~/.teyla/update-check.json.

    A record served from the cache carries `from_cache: True` so doctor can say "cached, not
    retried" instead of presenting a stale failure as a fresh one. A *failed* lookup is cached
    for FAIL_MAX_AGE_MIN only: the check that gates every future update must not report a
    fixed network as broken for the rest of the day."""
    cfg = config.load()
    repo = repo or cfg["update"]["repo"]
    channel, pin = update_settings(cfg)
    now = _dt.datetime.now(_dt.timezone.utc)
    if not net.allowed(cfg):
        return _offline_record(repo, cfg, now)
    if not refresh and CHECK_PATH.exists():
        try:
            cached = json.loads(CHECK_PATH.read_text())
            when = _dt.datetime.fromisoformat(cached["checked"])
            age = (now - when).total_seconds()
            limit = max_age_hours * 3600 if cached.get("latest") else FAIL_MAX_AGE_MIN * 60
            if age < limit and cached.get("repo") == repo and cached.get("pin") == pin:
                cached["installed"] = __version__
                cached["newer"] = _wanted(cached.get("latest"), cached.get("sha"), pin)
                cached["from_cache"] = True
                return cached
        except (OSError, ValueError, KeyError):
            pass
    if pin and pin_is_sha(pin):
        # A sha pin names the commit itself; there is no release to look up, only the sha to
        # confirm GitHub has (and to expand, when it was given short).
        tag, sha = None, resolve_sha(repo, pin)
        note, reachable = (f"pinned to commit {pin}", True) if sha else (f"commits/{pin}: not found or unreachable", False)
    else:
        want = None if not pin else (pin if pin.startswith("v") else f"v{pin}")
        tag, note, reachable = lookup_release(repo, tag=want)
        sha = resolve_sha(repo, tag) if tag else None
        if tag and not sha:
            note += f"; could not resolve {tag} to a commit"
    method, root = install_method()
    rec = {"checked": now.isoformat(timespec="seconds"), "repo": repo, "installed": __version__,
           "latest": tag, "sha": sha, "pin": pin, "channel": channel,
           "note": note, "method": method, "checkout": str(root) if root else None,
           "newer": _wanted(tag, sha, pin), "reachable": reachable,
           "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
           "python_pin": python_spec(cfg), "executable": sys.executable, "trust": trust_source(),
           "proxy": proxy_in_use(), "from_cache": False}
    try:
        CHECK_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHECK_PATH.write_text(json.dumps(rec, indent=2) + "\n")
    except OSError:
        pass
    return rec


def _offline_record(repo: str, cfg: dict, now) -> dict:
    """Safe mode: no lookup. The last record an explicit `--allow-network` run left, whatever its
    age (marked `from_cache`), else a record that says nothing was asked. Never written back."""
    method, root = install_method()
    rec = {"checked": "", "repo": repo, "latest": None, "note": "safe mode: not checked", "reachable": None}
    try:
        cached = json.loads(CHECK_PATH.read_text())
        if cached.get("repo") == repo:
            rec = cached
    except (OSError, ValueError):
        pass
    channel, pin = update_settings(cfg)
    rec.update({"installed": __version__, "newer": _wanted(rec.get("latest"), rec.get("sha"), pin), "method": method,
                "pin": pin, "channel": channel,
                "checkout": str(root) if root else None, "from_cache": bool(rec.get("checked")), "safe": True,
                "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                "python_pin": python_spec(cfg), "executable": sys.executable, "trust": trust_source(),
                "proxy": proxy_in_use()})
    return rec


def _run(cmd: list[str], cwd: pathlib.Path | None = None) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def _uv_cache_corrupt(out: str) -> bool:
    return "unable to read sha1 file" in out or "Could not reset index file" in out or "Git operation failed" in out


def install_source(repo: str, ref: str) -> str:
    """What uv/pipx/pip install. With truststore importable here the install came with the
    `work` extra (or had it added), and a plain `git+...` reinstall would drop it — the next
    update check behind the proxy would then fail on the very release it just installed."""
    url = f"git+https://github.com/{repo}@{ref}"
    return f"teyla[work] @ {url}" if truststore_available() else url


def _installer(method: str, spec: str, src: str) -> list[str] | None:
    """The install command for `method`, or None when its tool is missing."""
    # Every install names one exact commit, and it must land even when that commit carries the
    # version already installed: pip's --upgrade then keeps what is there, and uv may reuse its
    # build. So always reinstall (review of #64, P1). pipx --force recreates the venv already.
    if method == "uv-tool":
        uv = shutil.which("uv")
        return [uv, "tool", "install", "--force", "--python", spec, "--reinstall", src] if uv else None
    if method == "pipx":
        pipx = shutil.which("pipx")
        return [pipx, "install", "--force", "--python", python_executable_for(spec), src] if pipx else None
    return [sys.executable, "-m", "pip", "install", "--force-reinstall", src]


def installed_version(method: str) -> str | None:
    """`teyla --version` of what is on disk now, from a fresh process — the running one still
    has the old code imported."""
    if method in ("uv-tool", "pipx"):
        exe = shutil.which("teyla") or str(pathlib.Path.home() / ".local" / "bin" / "teyla")
        cmd = [exe, "--version"]
    else:
        cmd = [sys.executable, "-c", "import teyla; print(teyla.__version__)"]
    try:
        rc, out = _run(cmd)
    except OSError:
        return None
    return out.strip().splitlines()[-1].strip() if rc == 0 and out.strip() else None


def installed_commit(method: str) -> str | None:
    """The commit of what is on disk now, from a fresh process in the install's own interpreter
    (for uv/pipx, the `python` beside the resolved `teyla` entry point). None when unknown."""
    if method in ("uv-tool", "pipx"):
        exe = shutil.which("teyla") or str(pathlib.Path.home() / ".local" / "bin" / "teyla")
        bindir = pathlib.Path(exe).resolve().parent
        py = next((c for c in (bindir / "python", bindir / "python.exe", bindir / "python3") if c.exists()), None)
        if py is None:
            return None
        cmd = [str(py), "-c", _COMMIT_PROBE]
    else:
        cmd = [sys.executable, "-c", _COMMIT_PROBE]
    try:
        rc, out = _run(cmd)
    except OSError:
        return None
    return _as_sha(out.strip().splitlines()[-1]) if rc == 0 and out.strip() else None


def restore(repo: str, method: str, spec: str, before: str | None = None) -> list[str]:
    """Put the version that was running back: by the commit it was installed from when
    `teyla update` recorded one, else by its release tag. After an install, pass `before`
    (installed_sha() read *before* the installer ran): by then direct_url.json describes the
    build being rejected, and restoring "what is installed" reinstalled it (review of #64, P1)."""
    ref = before or installed_sha() or f"v{__version__}"
    cmd = _installer(method, spec, install_source(repo, ref))
    if cmd is None:
        return [f"FAIL: could not restore {__version__}: no installer for {method}"]
    rc, out = _run(cmd)
    return [f"restored {__version__} ({ref})" if rc == 0 else f"FAIL: could not restore {__version__} ({ref}): {out[-300:]}"]


def checkout_command(checkout: pathlib.Path) -> str:
    return f"git -C {checkout} pull --ff-only && {sys.executable} -m pip install -q -e {checkout}"


def upgrade(tag: str | None, repo: str, method: str, checkout: pathlib.Path | None = None,
            python: str | None = None, sha: str | None = None) -> list[str]:
    """Install the release `tag` by its commit `sha`, then check `teyla --version` says `tag`.
    No sha → nothing is installed: a tag alone can be moved between the lookup and the build."""
    spec = python or python_spec()
    label = tag or (sha or "?")[:12]
    if method == "checkout":
        # A git checkout is somebody's working tree: fast-forwarding it unattended to whatever
        # origin/main holds is exactly the unpinned update this module exists to avoid.
        return [f"SKIP: {checkout or 'this checkout'} is a git checkout; update it by hand: "
                f"{checkout_command(checkout) if checkout else 'git pull --ff-only && pip install -e .'}"]
    if not sha:
        return [f"FAIL: could not resolve {label} to a commit on {repo}; not installing an unpinned ref"]
    src = install_source(repo, sha)
    # What to roll back to, frozen before the installer replaces direct_url.json. The tag
    # fallback is frozen too: when the running build's commit is unknown, re-reading it after
    # the install found the rejected build's commit (review of #64, P1).
    before = installed_sha() or f"v{__version__}"
    cmd = _installer(method, spec, src)
    if cmd is None:
        return [f"FAIL: installed with {method} but `{'uv' if method == 'uv-tool' else method}` is not on PATH"]
    lines = []
    rc, out = _run(cmd)
    if rc != 0 and method == "uv-tool" and _uv_cache_corrupt(out):
        # uv's git checkout of the repo lost objects ("unable to read sha1 file"); seen
        # 2026-09-15 on the 0.9.3 → 0.10.0 update. Clearing the cache entry and retrying
        # once is the fix; nothing else is.
        lines.append("uv's cached checkout of teyla is corrupt — `uv cache clean teyla`, then retrying")
        _run([cmd[0], "cache", "clean", "teyla"])
        rc, out = _run(cmd)
    if rc != 0:
        lines.append(f"FAIL: upgrade via {method}: {out[-800:]}")
        if method == "uv-tool" and not shutil.which("teyla") and not (pathlib.Path.home() / ".local" / "bin" / "teyla").exists():
            # `uv tool install --force` removes the old tool before the new build; a failed
            # build therefore leaves no `teyla` at all — the daily wrapper, the session-start
            # hook and doctor all go quiet. Put the installed version back first.
            lines += restore(repo, method, spec, before)
        return lines
    got = installed_version(method)
    if (got != tag.lstrip("v")) if tag else not got:
        # The commit built, but it is not the release it was looked up as (a moved tag, a
        # mis-versioned build) — or, for a sha pin, it does not run at all (review of #64, P2).
        # Keep the version that was known to work.
        want = f", expected {tag.lstrip('v')}" if tag else ""
        lines.append(f"FAIL: installed {sha[:12]} reports version {got or '(none)'}{want} — restoring")
        lines += restore(repo, method, spec, before)
        return lines
    landed = installed_commit(method)
    if landed and not same_commit(landed, sha):
        # The installer kept another build of the same version; recording `sha` would make the
        # pin look met forever (review of #64, P1). Unknown provenance is accepted: the forced
        # reinstall of one exact commit is what guarantees it, the probe only double-checks.
        lines.append(f"FAIL: asked for {sha[:12]} but the installed build is {landed[:12]} — restoring")
        lines += restore(repo, method, spec, before)
        return lines
    _record_installed(got, tag, landed or sha)
    on = f" on python {spec}" if method in ("uv-tool", "pipx") else ""
    lines.append(f"installed {label} ({sha[:12]}) via {method}{on}")
    return lines


def post_update(quiet: bool = False) -> list[str]:
    """Runs in a fresh process so the *new* code does the wiring."""
    teyla = shutil.which("teyla") or sys.argv[0]
    lines = []
    for args in (["policy", "sync"], ["policy", "refresh"], ["plugin", "refresh"], ["harness", "sync"], ["routine", "install", "--if-stale"],
                 ["doctor", "--quiet"]):
        rc, out = _run([teyla, *args])
        head = f"$ teyla {' '.join(args)}"
        if rc != 0 and args[0] != "doctor":
            lines.append(f"{head}: exit {rc}\n  " + out.replace("\n", "\n  "))
        elif not quiet or args[0] == "doctor":
            lines.append(f"{head}\n  " + (out or "(nothing to do)").replace("\n", "\n  "))
    return lines


def cmd_update(args):
    cfg = config.load()
    repo = cfg["update"]["repo"]
    channel, pin = update_settings(cfg)
    if channel not in ("release", "none"):
        print(f"teyla: [update] channel = {channel!r} is not one of release, none — teyla config set update.channel=release")
        return 1
    if channel == "none" and os.environ.get("TEYLA_IN_ROUTINE") and not args.check:
        if not args.quiet:
            print("teyla: [update] channel = none — no automatic update; run `teyla update` by hand")
        return 0
    if not net.gate("`teyla update" + (" --check`" if args.check else "`"), cfg):
        return 1
    rec = check(repo, refresh=True)
    method, root = rec["method"], rec.get("checkout")
    target = rec.get("latest") or (rec.get("sha") if pin else None)
    pinned = f", pinned to {pin}" if pin else ""
    if target is None:
        print(f"teyla {__version__} ({method}, python {rec['python']}, trust: {rec['trust']}{pinned}); "
              f"no release to install from {repo}: {rec['note']}")
        hint = explain_tls_error(rec["note"])
        if hint:
            print(f"  → {hint}")
        running = f"{sys.version_info.major}.{sys.version_info.minor}"
        if args.force and rec["python_pin"] != running and method in ("uv-tool", "pipx"):
            # The lookup failed *on this interpreter* and config pins another one. The latest
            # release is unknown, but the installed version is: reinstall it (by the commit it
            # came from, when recorded) on the pinned interpreter so the next check runs there.
            # This is how a 3.13 install whose TLS verification rejects the proxy root gets to
            # 3.12 without a working lookup.
            print(f"--force: reinstalling {__version__} on python {rec['python_pin']} (lookup failed on {running}); "
                  f"run `teyla update` again afterwards")
            lines = restore(repo, method, rec["python_pin"])
            for line in lines:
                print(line)
            return 1 if any(line.startswith(("FAIL", "SKIP")) for line in lines) else 0
        return 1
    if args.check:
        state = "update available" if rec["newer"] else "up to date"
        print(f"teyla {__version__} ({method}) — {'pinned' if pin else 'latest'} {target} ({rec['note']}) — {state}")
        return 0
    if not rec["newer"] and not args.force:
        if not args.quiet:
            print(f"teyla {__version__} ({method}) is the {'pinned' if pin else 'latest'} release ({target}).")
            print("post-update steps (--force to run them anyway):")
        if args.wire:
            for line in post_update(quiet=args.quiet):
                print(line)
        return 0
    sha = rec.get("sha")
    print(f"teyla {__version__} → {target}" + (f" ({sha[:12]})" if sha else "") + f" via {method} (python {rec['python_pin']}{pinned})")
    lines = upgrade(rec.get("latest"), repo, method, pathlib.Path(root) if root else None, python=rec["python_pin"], sha=sha)
    for line in lines:
        print(line)
    if any(line.startswith(("FAIL", "SKIP")) for line in lines):
        return 1
    for line in post_update(quiet=args.quiet):
        print(line)
    return 0


def register(sp):
    q = sp.add_parser("update", help="check GitHub for a newer release, install it, re-wire policy/plugin/routines")
    q.set_defaults(fn=cmd_update)
    q.add_argument("--check", action="store_true", help="only report whether a newer release exists")
    q.add_argument("--force", action="store_true", help="reinstall the latest release even if it is the current one")
    q.add_argument("--wire", action="store_true", help="when already current, still run the post-update steps")
    q.add_argument("--quiet", action="store_true")
    q.add_argument("--allow-network", action="store_true", help="safe mode: allow this one run to reach GitHub")
