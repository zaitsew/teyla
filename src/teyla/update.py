"""`teyla update` — keep this machine's Teyla current, then re-wire what depends on it.

    teyla update            check GitHub for a newer release; install it; run the post-update steps
    teyla update --check    only report (and cache) whether a newer release exists
    teyla update --quiet    one line unless something changed or failed (for the daily routine)

How the install happened decides how it is upgraded:

    uv tool        ~/.local/share/uv/tools/teyla/...    uv tool install --force --python <X.Y> git+<repo>@<tag>
    pipx           .../pipx/venvs/teyla/...             pipx install --force --python <exe> git+<repo>@<tag>
    checkout       <repo>/src/teyla/__init__.py + .git   git fetch + fast-forward merge of origin/main
    pip            anything else                          python -m pip install --upgrade git+<repo>@<tag>

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
    plugin refresh      the Claude Code plugin cache copy, if the installed one is older
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
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

from . import __version__, config

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


def trust_source() -> str:
    """One phrase for doctor: where TLS roots come from for Python's HTTPS here."""
    try:
        import truststore  # noqa: F401
        return "truststore (OS trust store)"
    except ImportError:
        pass
    for var in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        if os.environ.get(var):
            return f"{var}={os.environ[var]}"
    import ssl
    paths = ssl.get_default_verify_paths()
    return f"openssl default {paths.cafile or paths.capath or '(none found)'}"


def ssl_context():
    import ssl
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return ssl.create_default_context()


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
                "or pip install truststore into Teyla's environment")
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
    """(tag or None, note). Tries releases/latest, then tags."""
    for url, key in ((f"https://api.github.com/repos/{repo}/releases/latest", "tag_name"),
                     (f"https://api.github.com/repos/{repo}/tags", None)):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": f"teyla/{__version__}"})
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:
                data = json.loads(r.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as e:
            note = f"{url.split('/')[-1]}: {e}"
            continue
        if key:
            tag = data.get(key)
            if tag:
                return tag, "releases/latest"
        else:
            tags = [t.get("name") for t in data if isinstance(t, dict) and str(t.get("name", "")).startswith("v")]
            if tags:
                tags.sort(key=_vtuple)
                return tags[-1], "tags"
        note = "no tags"
    return None, note


def check(repo: str | None = None, refresh: bool = True, max_age_hours: int = 24) -> dict:
    """Cached lookup of the latest release. Writes ~/.teyla/update-check.json."""
    cfg = config.load()
    repo = repo or cfg["update"]["repo"]
    now = _dt.datetime.now(_dt.timezone.utc)
    if not refresh and CHECK_PATH.exists():
        try:
            cached = json.loads(CHECK_PATH.read_text())
            when = _dt.datetime.fromisoformat(cached["checked"])
            if (now - when).total_seconds() < max_age_hours * 3600 and cached.get("repo") == repo:
                cached["installed"] = __version__
                cached["newer"] = is_newer(cached.get("latest"), __version__)
                return cached
        except (OSError, ValueError, KeyError):
            pass
    tag, note = latest_release(repo)
    method, root = install_method()
    rec = {"checked": now.isoformat(timespec="seconds"), "repo": repo, "installed": __version__,
           "latest": tag, "note": note, "method": method, "checkout": str(root) if root else None,
           "newer": is_newer(tag, __version__),
           "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
           "python_pin": python_spec(cfg), "executable": sys.executable, "trust": trust_source()}
    try:
        CHECK_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHECK_PATH.write_text(json.dumps(rec, indent=2) + "\n")
    except OSError:
        pass
    return rec


def _run(cmd: list[str], cwd: pathlib.Path | None = None) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def upgrade(tag: str, repo: str, method: str, checkout: pathlib.Path | None = None,
            python: str | None = None) -> list[str]:
    src = f"git+https://github.com/{repo}@{tag}"
    spec = python or python_spec()
    lines = []
    if method == "uv-tool":
        uv = shutil.which("uv")
        if not uv:
            return ["FAIL: installed with uv but `uv` is not on PATH"]
        rc, out = _run([uv, "tool", "install", "--force", "--python", spec, src])
    elif method == "pipx":
        pipx = shutil.which("pipx")
        if not pipx:
            return ["FAIL: installed with pipx but `pipx` is not on PATH"]
        rc, out = _run([pipx, "install", "--force", "--python", python_executable_for(spec), src])
    elif method == "checkout" and checkout:
        rc, out = _run(["git", "status", "--porcelain"], cwd=checkout)
        if rc != 0:
            return [f"FAIL: git status in {checkout}: {out}"]
        if out.strip():
            return [f"SKIP: {checkout} has uncommitted changes; pull by hand"]
        rc, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=checkout)
        if branch.strip() != "main":
            return [f"SKIP: {checkout} is on {branch.strip()}, not main; pull by hand"]
        rc, out = _run(["git", "fetch", "--tags", "origin"], cwd=checkout)
        if rc == 0:
            rc, out = _run(["git", "merge", "--ff-only", "origin/main"], cwd=checkout)
        if rc == 0:
            lines.append(f"fast-forwarded {checkout} to origin/main")
            rc, out2 = _run([sys.executable, "-m", "pip", "install", "-q", "-e", str(checkout)])
            out = out2 if rc != 0 else out
    else:
        rc, out = _run([sys.executable, "-m", "pip", "install", "--upgrade", src])
    if rc != 0:
        lines.append(f"FAIL: upgrade via {method}: {out[-800:]}")
    elif method in ("uv-tool", "pipx"):
        lines.append(f"installed {tag} via {method} on python {spec}")
    else:
        lines.append(f"installed {tag} via {method}")
    return lines


def post_update(quiet: bool = False) -> list[str]:
    """Runs in a fresh process so the *new* code does the wiring."""
    teyla = shutil.which("teyla") or sys.argv[0]
    lines = []
    for args in (["policy", "sync"], ["policy", "refresh"], ["plugin", "refresh"], ["routine", "install", "--if-stale"],
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
    rec = check(repo, refresh=True)
    method, root = rec["method"], rec.get("checkout")
    if rec["latest"] is None:
        print(f"teyla {__version__} ({method}, python {rec['python']}, trust: {rec['trust']}); "
              f"could not reach GitHub for {repo}: {rec['note']}")
        hint = explain_tls_error(rec["note"])
        if hint:
            print(f"  → {hint}")
        return 1
    if args.check:
        state = "update available" if rec["newer"] else "up to date"
        print(f"teyla {__version__} ({method}) — latest {rec['latest']} ({rec['note']}) — {state}")
        return 0
    if not rec["newer"] and not args.force:
        if not args.quiet:
            print(f"teyla {__version__} ({method}) is the latest release ({rec['latest']}).")
            print("post-update steps (--force to run them anyway):")
        if args.wire:
            for line in post_update(quiet=args.quiet):
                print(line)
        return 0
    tag = rec["latest"]
    print(f"teyla {__version__} → {tag} via {method} (python {rec['python_pin']})")
    lines = upgrade(tag, repo, method, pathlib.Path(root) if root else None, python=rec["python_pin"])
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
