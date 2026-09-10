"""Where the control plane keeps its state, and the two append-only logs.

Three locations, and the split between them is deliberate:

    ~/.teyla/KILL              the kill switch — one file, machine-wide
    ~/.teyla/inbox.jsonl       every item that needs a human, append-only
    ~/.teyla/receipts.jsonl    one line per run, append-only
    ~/.teyla/promotions.jsonl  one line per gate promotion, append-only
    ~/.teyla/hmac.key          0600; signs every line the hook writes
    ~/.teyla/active-runs/<id>  one file per run in flight, holding its pid
    ~/.teyla/runs/<run-id>/    the run's **control** files — see below
    <repo>/runs/<date>/<routine>/<run-id>/   the run's readable artifacts
    <repo>/.teyla/corrections.jsonl          rejections, as rule candidates

Machine-wide state (the switch, the queue, the history) lives under `~/.teyla`
because it spans products: one kill switch that only stops one repo is not a
kill switch.

**Why the control files moved.** They used to sit in the product's `runs/`
directory, next to the draft — which is exactly the directory a routine granted
`fs.write:runs/**` can write to. A run could therefore rewrite its own
`grants.json` to widen itself, or its own `actions.jsonl` so the receipt would
lie about what it did. The policy a run is judged by cannot live inside the
blast radius of that run, so `grants.json`, `grants-state.json`,
`actions.jsonl`, `run.json` and the canonical `receipt.json` are here, under
`~/.teyla/runs/<run-id>/`, which the hook refuses to write to under any grant.
The product's `runs/` directory keeps what a human reads — `draft.md`,
`undo.md`, and a *copy* of the receipt the engine writes after the run.

Every log here is append-only and state changes are new records, never edits.
An inbox item that was approved is two lines, not one mutated line — otherwise
"who approved this and when" is a question the file cannot answer.

`TEYLA_HOME` overrides `~/.teyla` (tests set it; so can a second profile).
`TEYLA_REPO_ROOTS` overrides `~/repos` as the search path for products,
colon-separated.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import pathlib
import secrets
import tomllib

# The filenames that decide what a run was allowed to do and what it did. No tool
# call may write one, anywhere, under any grant: a routine that can rewrite these
# is a routine that grades its own exam. Checked by basename rather than by path
# because the check has to survive a symlink, a relative path and a `cd`.
CONTROL_BASENAMES = frozenset({
    "grants.json", "grants-state.json", "actions.jsonl", "run.json", "receipt.json",
    "hmac.key", "KILL", "inbox.jsonl", "receipts.jsonl", "promotions.jsonl",
})

# Compared case-insensitively: this runs on a filesystem where `Grants.json` opens
# `grants.json`, so a check that only knew one spelling was a check with a spelling
# for a bypass.
_CONTROL_BASENAMES_LOWER = frozenset(n.lower() for n in CONTROL_BASENAMES)


def home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("TEYLA_HOME") or (pathlib.Path.home() / ".teyla")).expanduser()


def kill_path() -> pathlib.Path:
    return home() / "KILL"


def inbox_path() -> pathlib.Path:
    return home() / "inbox.jsonl"


def receipts_path() -> pathlib.Path:
    return home() / "receipts.jsonl"


def promotions_path() -> pathlib.Path:
    return home() / "promotions.jsonl"


def control_runs_root() -> pathlib.Path:
    return home() / "runs"


def control_run_dir(run_id: str) -> pathlib.Path:
    """Where one run's policy and evidence live. Outside every product repo on
    purpose — see the module docstring."""
    return control_runs_root() / str(run_id)


def active_runs_dir() -> pathlib.Path:
    return home() / "active-runs"


def hmac_key_path() -> pathlib.Path:
    return home() / "hmac.key"


def is_control_path(target) -> bool:
    """True if reading or writing `target` would touch the control plane's own state:
    anything under `~/.teyla`, or anything whose basename is a control filename,
    matched **case-insensitively** because the filesystem is."""
    try:
        p = pathlib.Path(str(target)).expanduser()
        real = pathlib.Path(os.path.realpath(str(p)))
    except (OSError, ValueError):
        return True  # unreadable path, treated as control: refuse rather than guess
    if real.name.lower() in _CONTROL_BASENAMES_LOWER or p.name.lower() in _CONTROL_BASENAMES_LOWER:
        return True
    h = pathlib.Path(os.path.realpath(str(home())))
    for cand in (real, pathlib.Path(os.path.normpath(str(p.absolute())))):
        try:
            cand.relative_to(h)
            return True
        except ValueError:
            continue
    return False


def repo_roots() -> list[pathlib.Path]:
    raw = os.environ.get("TEYLA_REPO_ROOTS")
    if raw:
        return [pathlib.Path(p).expanduser() for p in raw.split(":") if p]
    return [pathlib.Path.home() / "repos"]


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def stamp() -> str:
    return now().isoformat(timespec="seconds")


# --- jsonl ---------------------------------------------------------------------


def append_jsonl(path: pathlib.Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def read_jsonl(path: pathlib.Path) -> list[dict]:
    """Malformed lines are skipped, not fatal. These files are appended to by a hook
    that may be killed mid-write; one torn line must not make the whole history
    unreadable."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


# --- the signed action log ------------------------------------------------------------

# `actions.jsonl` is what the receipt's "actions taken" is built from, so a run that
# can append to it can make the receipt say anything. Moving the file under ~/.teyla
# (where the hook refuses every write) is the first half of the fix; this is the
# second. Each line carries an HMAC over its own content, keyed by a file only the
# hook and the engine read. A line that does not verify is not counted — and the
# receipt says how many were dropped, because silently ignoring a forged line is
# how a tampered log becomes a clean receipt.


def hmac_key() -> bytes:
    """The signing key, created 0600 on first use. Never printed, never copied."""
    p = hmac_key_path()
    try:
        return p.read_bytes()
    except OSError:
        pass
    p.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    return key


def _canonical(record: dict) -> bytes:
    body = {k: v for k, v in record.items() if k != "hmac"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")


def sign_record(record: dict) -> dict:
    out = {k: v for k, v in record.items() if k != "hmac"}
    out["hmac"] = hmac.new(hmac_key(), _canonical(out), hashlib.sha256).hexdigest()
    return out


def verify_record(record: dict) -> bool:
    got = record.get("hmac")
    if not isinstance(got, str):
        return False
    want = hmac.new(hmac_key(), _canonical(record), hashlib.sha256).hexdigest()
    return hmac.compare_digest(got, want)


def append_signed_jsonl(path: pathlib.Path, record: dict) -> None:
    append_jsonl(path, sign_record(record))


def read_signed_jsonl(path: pathlib.Path) -> tuple[list[dict], int]:
    """`(verified rows, number of lines that failed verification)`. A torn last line
    counts as tampered too — the caller cannot tell the difference and neither
    should the receipt."""
    rows, bad = [], 0
    if not path.exists():
        return rows, bad
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if not isinstance(rec, dict) or not verify_record(rec):
            bad += 1
            continue
        rows.append(rec)
    return rows, bad


# --- runs in flight ---------------------------------------------------------------------

# A nested session — a `claude -p` the agent spawns itself — may reach the hook with
# no TEYLA_GRANTS in its environment, and the hook's "no grants means an ordinary
# session" rule would wave it through. These markers let the hook tell the two apart:
# while any run is in flight on this machine, a session with no grants is not an
# ordinary session, it is an escape, and it is refused.


def mark_run_active(run_id: str) -> pathlib.Path:
    d = active_runs_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / str(run_id)
    p.write_text(f"{os.getpid()}\n{stamp()}\n")
    return p


def clear_run_active(run_id: str) -> None:
    try:
        (active_runs_dir() / str(run_id)).unlink()
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def active_runs(prune: bool = True) -> list[str]:
    """The runs actually in flight. A marker whose process is gone is stale — a run
    that crashed — and is pruned rather than left to deny every session on this
    machine until someone finds the file."""
    d = active_runs_dir()
    if not d.is_dir():
        return []
    live = []
    for p in sorted(d.iterdir()):
        if not p.is_file():
            continue
        pid = None
        try:
            first = p.read_text(errors="replace").splitlines()[0].strip()
            pid = int(first)
        except (OSError, IndexError, ValueError):
            pid = None
        if pid is not None and not _pid_alive(pid):
            if prune:
                try:
                    p.unlink()
                except OSError:
                    pass
            continue
        live.append(p.name)
    return live


# --- the kill switch --------------------------------------------------------------


def kill_on(reason: str | None = None) -> str:
    p = kill_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    text = f"{reason or 'no reason given'}\n{stamp()}\n"
    p.write_text(text)
    return f"kill switch ON — {p}"


def kill_off() -> str:
    p = kill_path()
    if not p.exists():
        return f"kill switch already off ({p} does not exist)"
    p.unlink()
    return f"kill switch OFF — removed {p}"


def kill_reason() -> str | None:
    """The reason line if the switch is on, otherwise None. Never raises: a switch whose
    status check can fail is a switch that fails open."""
    p = kill_path()
    try:
        if not p.exists():
            return None
        lines = p.read_text(errors="replace").splitlines()
    except OSError:
        return "unreadable KILL file — refusing anyway"
    return (lines[0].strip() if lines else "") or "no reason given"


def kill_status() -> list[str]:
    p = kill_path()
    if not p.exists():
        return [f"kill switch: OFF ({p} absent)"]
    lines = p.read_text(errors="replace").splitlines()
    out = [f"kill switch: ON  ({p})"]
    if lines:
        out.append(f"  reason: {lines[0].strip()}")
    if len(lines) > 1:
        out.append(f"  since:  {lines[1].strip()}")
    out.append("  `teyla run` refuses and every tool call is denied while this file exists.")
    return out


# --- products ------------------------------------------------------------------------


def find_product_manifests() -> list[pathlib.Path]:
    """Every `teyla.toml` one level under a configured repo root."""
    out = []
    for root in repo_roots():
        if not root.is_dir():
            continue
        for p in sorted(root.iterdir()):
            if (p / "teyla.toml").exists():
                out.append(p / "teyla.toml")
    return out


def product_name(manifest_path: pathlib.Path) -> str | None:
    try:
        data = tomllib.loads(manifest_path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return (data.get("product") or {}).get("name")


def split_ref(ref: str) -> tuple[str, str]:
    """`"combra:morning-digest"` -> `("combra", "morning-digest")`."""
    if ":" not in ref:
        raise ValueError(f"routine reference {ref!r} must be <product>:<routine>")
    product, _, routine = ref.partition(":")
    if not product or not routine:
        raise ValueError(f"routine reference {ref!r} must be <product>:<routine>")
    return product, routine


# --- run identity ---------------------------------------------------------------------


def new_run_id(when: dt.datetime | None = None) -> str:
    when = when or now()
    return f"{when.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(3)}"


def run_dir_for(repo: pathlib.Path, routine: str, run_id: str, when: dt.datetime | None = None) -> pathlib.Path:
    """The *readable* half of a run: draft, undo, prompts, and a copy of the receipt.
    The policy half lives in `control_run_dir(run_id)` and is not writable by the
    run itself."""
    when = when or now()
    return pathlib.Path(repo) / "runs" / when.strftime("%Y-%m-%d") / routine / run_id


# --- receipts -----------------------------------------------------------------------

# A receipt with one of these outcomes means the work for that idempotency key is
# done. `blocked` and `failed` do not: a run that a critic rejected, or that died,
# must be allowed to run again on the next trigger without --force.
DONE_OUTCOMES = ("ok", "needs-you")
OUTCOMES = ("ok", "blocked", "failed", "skipped", "needs-you")


def record_receipt(receipt: dict) -> None:
    append_jsonl(receipts_path(), receipt)


def receipts_for(ref: str | None = None) -> list[dict]:
    rows = read_jsonl(receipts_path())
    if ref is None:
        return rows
    return [r for r in rows if r.get("routine") == ref]


def receipt_for_key(key: str) -> dict | None:
    """The most recent *done* receipt carrying this idempotency key, if any."""
    for r in reversed(read_jsonl(receipts_path())):
        if r.get("key") == key and r.get("outcome") in DONE_OUTCOMES:
            return r
    return None


def receipt_for_run(run_id: str) -> dict | None:
    """The receipt for one run, from `~/.teyla/receipts.jsonl` — the copy a run could
    not have edited. Approve reads the draft's capabilities from here, never from the
    copy sitting in the product repo."""
    for r in reversed(read_jsonl(receipts_path())):
        if r.get("run_id") == run_id:
            return r
    return None


def last_outcome(ref: str) -> str | None:
    rows = receipts_for(ref)
    return rows[-1].get("outcome") if rows else None


# --- the inbox ------------------------------------------------------------------------


def add_inbox_item(*, run_id: str, ref: str, gate: str, state: str, summary: str,
                   run_dir: str, repo: str, extra: dict | None = None) -> dict:
    rec = {
        "ts": stamp(), "type": "item", "id": run_id, "routine": ref, "gate": gate,
        "state": state, "summary": summary, "run_dir": run_dir, "repo": repo,
    }
    if extra:
        rec.update(extra)
    append_jsonl(inbox_path(), rec)
    return rec


def add_inbox_decision(*, run_id: str, decision: str, note: str | None = None, extra: dict | None = None) -> dict:
    rec = {"ts": stamp(), "type": decision, "id": run_id, "note": note}
    if extra:
        rec.update(extra)
    append_jsonl(inbox_path(), rec)
    return rec


def fold_inbox() -> dict[str, dict]:
    """Replay the append-only log into current state per item id, in insertion order.

    An `item` record creates or replaces the item; `approve`/`reject` records set its
    decision. The log is the truth; this is just the view."""
    items: dict[str, dict] = {}
    for rec in read_jsonl(inbox_path()):
        rid = rec.get("id")
        if not rid:
            continue
        kind = rec.get("type")
        if kind == "item":
            prior = items.get(rid, {})
            merged = dict(rec)
            for k in ("decision", "decision_ts", "note", "acted_run_id"):
                if k in prior:
                    merged[k] = prior[k]
            items[rid] = merged
        elif kind in ("approve", "reject"):
            item = items.setdefault(rid, {"id": rid, "type": "item", "state": "unknown"})
            item["decision"] = kind + "d" if kind == "approve" else "rejected"
            item["decision_ts"] = rec.get("ts")
            item["note"] = rec.get("note")
            if rec.get("acted_run_id"):
                item["acted_run_id"] = rec["acted_run_id"]
    return items


def inbox_item(run_id: str) -> dict | None:
    return fold_inbox().get(run_id)


# --- corrections (product repo) ----------------------------------------------------------


def record_correction(repo, *, ref: str, run_id: str, note: str, draft_excerpt: str = "") -> pathlib.Path:
    """A rejection with a note is a candidate rule. It lands in the product repo's
    `.teyla/corrections.jsonl` — the same file `/teyla:correct` writes — so it reaches
    the harvest with everything else that was corrected by hand."""
    path = pathlib.Path(repo) / ".teyla" / "corrections.jsonl"
    append_jsonl(path, {
        "ts": stamp(),
        "source": "inbox-reject",
        "routine": ref,
        "run_id": run_id,
        "text": note,
        "draft_excerpt": draft_excerpt[:500],
    })
    return path
