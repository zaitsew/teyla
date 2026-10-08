"""`teyla models watch` — did a provider ship a model the ladder or a repo should move to?

`teyla models` answers "is the ladder consistent with the catalogue today". The watch answers the
weekly question behind it: which models appeared since I last looked, which ladder entry would
each replace, and which repos on this machine still name a model that has been superseded.

  known list   ~/.teyla/models-known.json   {"known": {provider: [ids]}, "acked": "YYYY-MM-DD"}
               The first run seeds it from the current catalogue (day one reports nothing new);
               `--ack` moves what was reported into it; `--seed FILE` imports another watcher's list.
  new          catalogue ids (text-output models of the providers in the ladder) not in the list.
  superseded   ids older than a ladder model of their family, found by `git grep -F` in every git
               repo directly under code_root (tracked text files only, no lockfiles, nothing over 1 MB).

Network only with `--refresh` (and, in safe mode, `--allow-network`), as for `teyla models`.
Exit code 1 when there are unacknowledged new models, else 0.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import subprocess

from . import config, models

KNOWN_NAME = "models-known.json"
MAX_FILE_BYTES = 1_000_000
MAX_ROWS = 20
MAX_IDS = 400  # a pattern list longer than this is a catalogue dump, not a migration list
LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json", "cargo.lock",
             "poetry.lock", "uv.lock", "pipfile.lock", "package.resolved", "gemfile.lock",
             "composer.lock", "go.sum", "bun.lockb", "podfile.lock", "flake.lock"}


def known_path() -> pathlib.Path:
    return config.TEYLA_DIR / KNOWN_NAME  # call time: tests and a moved home redirect TEYLA_DIR


# --- the known list ----------------------------------------------------------------------------

def load_known() -> dict | None:
    """{"known": {provider: [ids]}, "acked": date} or None when the file is missing or unreadable."""
    try:
        data = json.loads(known_path().read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("known"), dict):
        return None
    known = {}
    for p, ids in data["known"].items():
        known[str(p)] = sorted({str(i) for i in (ids if isinstance(ids, list) else [])})
    return {"known": known, "acked": str(data.get("acked") or "")}


def save_known(known: dict, today: _dt.date | None = None) -> pathlib.Path:
    p = known_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {"known": {k: sorted(set(v)) for k, v in sorted(known.items())},
            "acked": (today or _dt.date.today()).isoformat()}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, indent=1) + "\n")
    os.replace(tmp, p)
    return p


def read_seed(path: str | os.PathLike) -> dict[str, list[str]]:
    """Another watcher's list: {"known": {provider: [ids...] or {id: ...}}}. Raises ValueError."""
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except OSError as e:
        raise ValueError(f"cannot read {path}: {e.strerror or e}") from e
    except ValueError as e:
        raise ValueError(f"{path} is not JSON: {e}") from e
    src = data.get("known") if isinstance(data, dict) else None
    if not isinstance(src, dict):
        raise ValueError(f'{path}: expected {{"known": {{provider: [ids...] or {{id: ...}}}}}}')
    out: dict[str, list[str]] = {}
    for provider, ids in src.items():
        if isinstance(ids, dict):
            names = list(ids)
        elif isinstance(ids, list):
            names = [i.get("id") if isinstance(i, dict) else i for i in ids]
        else:
            raise ValueError(f"{path}: known.{provider} must be a list or an object")
        out[str(provider)] = sorted({str(n) for n in names if n})
    return out


# --- catalogue facts -----------------------------------------------------------------------------

def _is_text(info: dict) -> bool:
    out = (info.get("modalities") or {}).get("output") or ["text"]
    return "text" in out


def ladder_providers(ladder: dict, models_dev: dict) -> list[str]:
    """The providers the ladder names that the catalogue knows; every known provider if no ladder."""
    named = [p for p in ladder if models.provider_catalogue(models_dev, p)]
    return named or [p for p in models.PROVIDERS if models.provider_catalogue(models_dev, p)]


def family_of(provider: str, mid: str, info: dict | None, name: str | None = None) -> str | None:
    info = info or {}
    return info.get("family") or models._guess_family(name or info.get("name") or "", provider) \
        or models._guess_family(mid, provider)


def _tokens(mid: str) -> set[str]:
    return set(re.findall(r"[a-z]+", mid.lower()))


def _price(info: dict) -> str:
    c = info.get("cost") or {}
    if c.get("input") is None or c.get("output") is None:
        return "price n/a"
    return f"${c['input']}/${c['output']} per 1M in/out"


def ladder_models(ladder: dict, models_dev: dict, cli_ids: dict) -> list[dict]:
    """Every ladder entry that resolves to a concrete id: provider, tier, entry, id, family, date."""
    out = []
    for provider, rows in ladder.items():
        cat = models.provider_catalogue(models_dev, provider)
        for tier in ("orchestrate", "volume", "triage"):
            for name in rows.get(tier, []):
                r = models.resolve_ladder_entry(name, provider, models_dev, cli_ids.get(provider, []))
                if not r or not r.get("id"):
                    continue
                out.append(dict(provider=provider, tier=tier, entry=models._model_name(name), id=r["id"],
                                family=family_of(provider, r["id"], cat.get(r["id"]) or r, name),
                                date=r.get("release_date") or ""))
    return out


def new_models(models_dev: dict, providers: list[str], known: dict, ladder: list[dict]) -> list[dict]:
    """Text-output catalogue ids of `providers` not in `known`, each with the ladder entry it
    would replace (same family, older) or 'new family'. Sorted newest first."""
    rows = []
    for provider in providers:
        have = set(known.get(provider, []))
        for mid, info in sorted(models.provider_catalogue(models_dev, provider).items()):
            if mid in have or not _is_text(info):
                continue
            date = info.get("release_date") or ""
            fam = family_of(provider, mid, info)
            repl = None
            if fam and date:
                older = [m for m in ladder if m["provider"] == provider and m["family"] == fam
                         and m["date"] and m["date"] < date and m["id"] != mid]
                if older:
                    mine = _tokens(mid)
                    def score(m):
                        t = _tokens(m["id"])
                        return (len(t & mine) / len(t | mine), m["date"])
                    repl = max(older, key=score)
            rows.append(dict(provider=provider, id=mid, name=info.get("name") or mid, date=date,
                             price=_price(info), family=fam,
                             replaces=(dict(entry=repl["entry"], id=repl["id"], tier=repl["tier"]) if repl else None)))
    rows.sort(key=lambda r: (r["date"], r["id"]), reverse=True)
    return rows


def superseded_ids(models_dev: dict, ladder: list[dict], new: list[dict]) -> dict[str, str]:
    """{id: why}: ladder entries a new model would replace, and every catalogue text model older
    than a ladder model of its family (ladder ids themselves are current choices, so excluded
    unless a new model replaces them)."""
    out: dict[str, str] = {}
    current = {m["id"] for m in ladder}
    newest: dict[tuple[str, str], tuple[str, str]] = {}
    for m in ladder:
        if m["family"] and m["date"]:
            key = (m["provider"], m["family"])
            if key not in newest or m["date"] > newest[key][0]:
                newest[key] = (m["date"], m["id"])
    for provider, fam in newest:
        date, top = newest[(provider, fam)]
        for mid, info in models.provider_catalogue(models_dev, provider).items():
            if mid in current or not _is_text(info) or family_of(provider, mid, info) != fam:
                continue
            if (info.get("release_date") or "9999") < date:
                out[mid] = f"older than {top}"
    for n in new:
        if n["replaces"]:
            out[n["replaces"]["id"]] = f"replaced by {n['id']}"
    return out


# --- finding superseded ids in repos -------------------------------------------------------------

def _repos(root: pathlib.Path) -> list[pathlib.Path]:
    try:
        return [d for d in sorted(root.iterdir()) if d.is_dir() and (d / ".git").exists()]
    except OSError:
        return []


def _id_regex(ids: list[str]) -> re.Pattern:
    # An id is a whole token: "gpt-5" must not match "gpt-5.5" or "gpt-5-mini" (the next character
    # may continue the id), nor "my-gpt-5" (the previous one may begin another word). A slash before
    # it is fine: provider-qualified ids such as "anthropic/<id>" name the same model.
    alt = "|".join(re.escape(i) for i in sorted(ids, key=len, reverse=True))
    return re.compile(rf"(?<![\w.\-])({alt})(?![\w]|[.\-]\w)")


def grep_repo(repo: pathlib.Path, ids: list[str], timeout: int = 30) -> list[dict]:
    """[{file, ids, lines}] for tracked text files in `repo` naming any of `ids`. One `git grep -F`
    per chunk of ids; exact matching (token boundaries) is then done on the few files it lists."""
    files: set[str] = set()
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        try:
            r = subprocess.run(["git", "-C", str(repo), "-c", "core.quotepath=off", "grep", "-I", "-F", "-l", "-z", "-f", "-"],
                               input="\n".join(chunk) + "\n", capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return []
        if r.returncode not in (0, 1):
            return []
        files.update(f for f in r.stdout.split("\0") if f)
    rx = _id_regex(ids)
    rows = []
    for rel in sorted(files):
        if pathlib.PurePosixPath(rel).name.lower() in LOCKFILES:
            continue
        path = repo / rel
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(errors="replace")
        except OSError:
            continue
        hit, lines = set(), 0
        for line in text.splitlines():
            found = rx.findall(line)
            if found:
                lines += 1
                hit.update(found)
        if lines:
            rows.append(dict(repo=repo.name, file=rel, ids=sorted(hit), lines=lines))
    return rows


def find_superseded(root: pathlib.Path, why: dict[str, str]) -> list[dict]:
    ids = sorted(why)[:MAX_IDS]
    if not ids:
        return []
    rows = []
    for repo in _repos(root):
        rows.extend(grep_repo(repo, ids))
    rows.sort(key=lambda r: (-r["lines"], r["repo"], r["file"]))
    for r in rows:
        r["why"] = {i: why[i] for i in r["ids"]}
    return rows


# --- the report ----------------------------------------------------------------------------------

def _policy_text() -> str:
    from . import policy
    try:
        return policy.POLICY.read_text() if policy.POLICY.exists() else ""
    except OSError:
        return ""


def _cli_ids() -> dict:
    ids = dict(models.cli_available_models())
    ids["anthropic"] = []  # no transcript scan: the watch reads the catalogue, not usage
    return ids


def ladder_edit(models_dev: dict, ladder: dict, cli_ids: dict) -> str | None:
    """The `--write-policy --dry` diff when it would change a model in the ladder, else None.
    A rewrite that only stamps the "reviewed <date>" note is not an edit worth reporting."""
    proposed = models.propose_ladder_rows(ladder, models_dev, cli_ids)
    tiers = ("orchestrate", "volume", "triage")
    if all(proposed.get(p, {}).get(t) == rows.get(t) for p, rows in ladder.items() for t in tiers):
        return None
    try:
        diff, changed = models.write_policy(dry=True, claude_used_models=[], models_dev=models_dev)
    except (OSError, ValueError):
        return None
    return diff if changed else None


def watch(refresh: bool = False, root: pathlib.Path | None = None, today: _dt.date | None = None,
          seed_file: str | None = None, ack: list[str] | None = None) -> dict:
    """Run one watch. Writes the known list only when seeding, importing or acknowledging."""
    today = today or _dt.date.today()
    models_dev, source = models.load_models_dev_catalogue(refresh=refresh)
    ladder_rows = models.parse_ladder(_policy_text())
    providers = ladder_providers(ladder_rows, models_dev)
    notes: list[str] = []
    state = load_known()
    seeded = False

    if seed_file:
        imported = read_seed(seed_file)
        merged = dict((state or {}).get("known", {}))
        for p, ids in imported.items():
            merged[p] = sorted(set(merged.get(p, [])) | set(ids))
        state = {"known": merged, "acked": today.isoformat()}
        save_known(merged, today)
        notes.append(f"imported {sum(len(v) for v in imported.values())} known model(s) from {seed_file}")
    if state is None:
        state = {"known": {p: sorted(models.provider_catalogue(models_dev, p)) for p in providers}, "acked": today.isoformat()}
        save_known(state["known"], today)
        seeded = True
        notes.append(f"first run: seeded {path_str(known_path())} with the current catalogue "
                     f"({', '.join(providers) or 'no providers'}); nothing is new today")
    else:
        added = [p for p in providers if p not in state["known"]]
        if added:  # a provider joined the ladder since the list was written
            for p in added:
                state["known"][p] = sorted(models.provider_catalogue(models_dev, p))
            save_known(state["known"], today)
            notes.append(f"seeded the new ladder provider(s): {', '.join(added)}")

    cli_ids = _cli_ids()
    lm = ladder_models(ladder_rows, models_dev, cli_ids)
    new = new_models(models_dev, providers, state["known"], lm)

    acked: list[str] = []
    if ack is not None:
        targets: list[tuple[str, str]] = []
        if not ack:
            targets = [(n["provider"], n["id"]) for n in new]
        for w in ack:
            prov, _, mid = w.partition(":")
            hit = [(p, w) for p in providers if w in models.provider_catalogue(models_dev, p)]
            if not hit and prov in providers and mid in models.provider_catalogue(models_dev, prov):
                hit = [(prov, mid)]
            if hit:
                targets += hit
            else:
                notes.append(f"not in the catalogue, not acknowledged: {w}")
        for p, mid in targets:
            if mid not in state["known"].setdefault(p, []):
                state["known"][p] = sorted(set(state["known"][p]) | {mid})
                acked.append(f"{p}:{mid}")
        save_known(state["known"], today)
        new = new_models(models_dev, providers, state["known"], lm)

    why = superseded_ids(models_dev, lm, new)
    root = root or config.code_root(config.load())
    sup = find_superseded(root, why)
    return dict(date=today.isoformat(), source=source, providers=providers, seeded=seeded, notes=notes,
                acked=sorted(acked), new=new, superseded=sup, superseded_ids=len(why),
                ladder_edit=ladder_edit(models_dev, ladder_rows, cli_ids), code_root=str(root))


def path_str(p: pathlib.Path) -> str:
    home = str(pathlib.Path.home())
    s = str(p)
    return "~" + s[len(home):] if s.startswith(home + os.sep) else s


def render(rep: dict) -> str:
    L = [f"teyla models watch — {rep['date']}"]
    L += [f"  {n}" for n in rep["notes"]]
    if rep["acked"]:
        L.append(f"  acknowledged {len(rep['acked'])}: {', '.join(rep['acked'])}")
    new = rep["new"]
    L.append("")
    L.append(f"new models ({len(new)}):" if new else "new models: none")
    for n in new:
        rep_s = (f"replaces {n['replaces']['entry']} ({n['replaces']['tier']}, {n['replaces']['id']})"
                 if n["replaces"] else "new family")
        L.append(f"  {n['provider']}:{n['id']}  {n['date'] or 'date n/a'}  {n['price']}  — {rep_s}")
    sup = rep["superseded"]
    L.append("")
    if sup:
        L.append(f"superseded ids in use ({len(sup)} file(s) under {rep['code_root']}; top {min(len(sup), MAX_ROWS)}):")
        for r in sup[:MAX_ROWS]:
            L.append(f"  {r['repo']}/{r['file']}  {r['lines']} line(s)  {', '.join(r['ids'])}")
    else:
        L.append(f"superseded ids in use: none ({rep['superseded_ids']} id(s) checked under {rep['code_root']})")
    L.append("")
    if rep["ladder_edit"]:
        L.append("proposed ladder edit (teyla models --write-policy):")
        L += [f"  {line}" for line in rep["ladder_edit"].splitlines()]
    else:
        L.append("ladder current")
    if new:
        L.append("")
        L.append("acknowledge when handled: teyla models watch --ack   (or --ack ID...)")
    return "\n".join(L) + "\n"


def cmd_watch(args) -> int:
    try:
        rep = watch(refresh=args.refresh, seed_file=args.seed, ack=args.ack)
    except ValueError as e:
        print(f"teyla: {e}")
        return 2
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(render(rep), end="")
    return 1 if rep["new"] else 0


# --- the digest ----------------------------------------------------------------------------------

def digest_candidates() -> list[dict]:
    """One digest line when unacknowledged new models exist. Local only: the cached catalogue and
    the known list; it never seeds, never refreshes and never touches a repo."""
    state = load_known()
    if state is None:
        return []
    models_dev, _ = models.load_models_dev_catalogue(refresh=False)
    ladder_rows = models.parse_ladder(_policy_text())
    new = new_models(models_dev, ladder_providers(ladder_rows, models_dev), state["known"], [])
    if not new:
        return []
    names = ", ".join(f"{n['provider']}:{n['id']}" for n in new[:3]) + (f", +{len(new) - 3}" if len(new) > 3 else "")
    return [dict(rank=4, id="models:new", text=f"models: {len(new)} new ({names})",
                 step="teyla models watch", cmd=True)]
