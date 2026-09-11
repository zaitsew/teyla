"""`teyla models` — keep the model ladder and prices current.

Reads (read-only, local-first; presence only for credentials, never a value):

  1. models.dev catalogue   ~/.hermes/models_dev_cache.json  (provider_id -> {models: {id: {...}}})
                             falls back to ~/.teyla/models_dev.json, written by `--refresh`.
  2. Grok CLI cache          ~/.grok/models_cache.json        (models this session can use)
  3. Codex cache + config    ~/.codex/models_cache.json, `model =` in ~/.codex/config.toml
  4. Claude Code usage       models actually used in the last N days, from the same Session
                             objects `teyla monitor` already loaded (no extra disk scan when
                             called from monitor.py; a fresh scan via adapters.load_all() when
                             called standalone as `teyla models`).
  5. Credentials/subscriptions (presence only) — env vars, ~/.codex/auth.json,
     ~/.grok/auth.json keys, and the Claude Code keychain item's exit code.

Everything here is read-only except `--write-policy` (rewrites the ladder table between the
`<!-- ladder:start -->` / `<!-- ladder:end -->` markers in ~/.agents/POLICY.md, nothing else in
the file) and `--write-prices` (writes ~/.teyla/prices.json, which pricing.py then prefers over
its built-in table). Network access happens only when `--refresh` is passed and the models.dev
cache is missing or older than CACHE_MAX_AGE_DAYS — never otherwise, so `drift()` is safe to call
from the monitor's hot path.

`--write-policy --drop-absent` also removes the ladder row for any provider with neither a
credential nor a CLI cache entry — a row `teyla models` cannot verify is even reachable. Without
`--drop-absent`, that row is left alone and a one-line warning is printed instead, naming the
provider and the flag that would remove it.
"""
from __future__ import annotations

import datetime as _dt
import difflib
import json
import os
import pathlib
import re
import subprocess

PROVIDERS = ("anthropic", "openai", "xai")
PROVIDER_LABEL = {"anthropic": "Anthropic", "openai": "OpenAI", "xai": "xAI"}
PROVIDER_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "xai": "XAI_API_KEY", "google": "GEMINI_API_KEY"}

HOME = pathlib.Path.home()
MODELS_DEV_CACHE = HOME / ".hermes" / "models_dev_cache.json"
MODELS_DEV_FALLBACK = HOME / ".teyla" / "models_dev.json"
GROK_CACHE = HOME / ".grok" / "models_cache.json"
GROK_AUTH = HOME / ".grok" / "auth.json"
CODEX_CACHE = HOME / ".codex" / "models_cache.json"
CODEX_CONFIG = HOME / ".codex" / "config.toml"
CODEX_AUTH = HOME / ".codex" / "auth.json"
HERMES_AUTH = HOME / ".hermes" / "auth.json"
PRICES_OUT = HOME / ".teyla" / "prices.json"

CACHE_MAX_AGE_DAYS = 7
MODELS_DEV_URL = "https://models.dev/api.json"

LADDER_START = "<!-- ladder:start"
LADDER_END = "<!-- ladder:end -->"

# A ladder-table cell is prose, not a machine-readable id ("GPT-6 standard tier"). A phrase built
# only from these words carries no model claim, so an unresolved match on it is not LADDER-UNKNOWN.
_FILLER_WORDS = {"tier", "standard", "the", "hardest", "tasks", "work", "and", "or", "for", "any",
                  "a", "on", "subscription", "worker", "none", "published", "use", "cheaper",
                  "provider", "smaller", "agent", "type", "throwaway", "triage", "volume", "orchestrate"}

# Best-effort keyword -> family map, used only by --write-policy to propose a replacement when a
# ladder entry resolves to nothing at all (a genuinely retired/renamed model). Not used for drift.
_FAMILY_KEYWORDS = {
    "anthropic": {"fable": "claude-fable", "opus": "claude-opus", "sonnet": "claude-sonnet", "haiku": "claude-haiku"},
    "openai": {"sol": "gpt-sol", "terra": "gpt-terra", "luna": "gpt-luna", "mini": "gpt-mini", "nano": "gpt-nano", "pro": "gpt-pro"},
    "xai": {"grok": "grok"},
}


# --- reading the sources -----------------------------------------------------

def _read_json(path) -> dict | list | None:
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _cache_age_days(path: pathlib.Path) -> float | None:
    try:
        return (_dt.datetime.now().timestamp() - path.stat().st_mtime) / 86400
    except OSError:
        return None


def load_models_dev_catalogue(refresh: bool = False) -> tuple[dict, str | None]:
    """(catalogue, source-description). Prefers the live ~/.hermes cache; network only when
    `refresh` is True and that cache is missing or stale — default is always network-free."""
    age = _cache_age_days(MODELS_DEV_CACHE)
    stale = age is None or age > CACHE_MAX_AGE_DAYS
    if MODELS_DEV_CACHE.exists() and not (stale and refresh):
        data = _read_json(MODELS_DEV_CACHE)
        if data is not None:
            return data, f"{MODELS_DEV_CACHE}" + (f" ({age:.1f}d old, stale)" if stale else "")
    if stale and refresh:
        try:
            import urllib.request
            req = urllib.request.Request(MODELS_DEV_URL, headers={"User-Agent": "teyla-models/1"})
            from .update import ssl_context  # same trust store as the GitHub call (truststore / SSL_CERT_FILE)
            with urllib.request.urlopen(req, timeout=20, context=ssl_context()) as r:  # noqa: S310 — opt-in, explicit --refresh only
                data = json.loads(r.read().decode())
            MODELS_DEV_FALLBACK.parent.mkdir(parents=True, exist_ok=True)
            MODELS_DEV_FALLBACK.write_text(json.dumps(data))
            return data, f"{MODELS_DEV_URL} (fetched just now)"
        except Exception:  # noqa: BLE001 — network is best-effort; fall back below
            pass
    data = _read_json(MODELS_DEV_FALLBACK)
    if data is not None:
        return data, str(MODELS_DEV_FALLBACK)
    data = _read_json(MODELS_DEV_CACHE)
    if data is not None:
        return data, f"{MODELS_DEV_CACHE} (stale, no network)"
    return {}, None


def provider_catalogue(models_dev: dict, provider: str) -> dict:
    """id -> model info, for one provider, from the models.dev catalogue."""
    return ((models_dev or {}).get(provider) or {}).get("models") or {}


def newest_models(models_dev: dict, provider: str, n: int = 3) -> list[dict]:
    """The `n` newest catalogue entries for a provider, by release_date, with cost in/out."""
    rows = []
    for mid, info in provider_catalogue(models_dev, provider).items():
        cost = info.get("cost") or {}
        rows.append(dict(id=mid, name=info.get("name") or mid, family=info.get("family"),
                          release_date=info.get("release_date") or "", cost_in=cost.get("input"), cost_out=cost.get("output")))
    rows.sort(key=lambda r: r["release_date"], reverse=True)
    return rows[:n]


def cli_available_models() -> dict:
    """provider -> sorted model ids/slugs this machine's own CLI caches say are usable now."""
    out = {"openai": [], "xai": []}
    d = _read_json(GROK_CACHE)
    if isinstance(d, dict):
        out["xai"] = sorted((d.get("models") or {}).keys())
    d = _read_json(CODEX_CACHE)
    if isinstance(d, dict):
        models = d.get("models")
        if isinstance(models, list):
            out["openai"] = sorted(m.get("slug") for m in models if isinstance(m, dict) and m.get("slug"))
        elif isinstance(models, dict):
            out["openai"] = sorted(models.keys())
    return out


def hermes_active_provider() -> str | None:
    """Which provider Hermes is currently signed into — the top-level `active_provider` key only,
    never a token/credential value."""
    d = _read_json(HERMES_AUTH)
    return d.get("active_provider") if isinstance(d, dict) else None


def codex_config_model() -> str | None:
    """The `model =` line in ~/.codex/config.toml, if present."""
    if not CODEX_CONFIG.exists():
        return None
    try:
        text = CODEX_CONFIG.read_text()
    except OSError:
        return None
    m = re.search(r'(?m)^\s*model\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else None


def claude_used_models_from_disk(days: int | None = 30) -> list[str]:
    """Anthropic model ids used in Claude Code sessions in the last `days` — a fresh scan via
    adapters.load_all(). Only call this standalone (`teyla models`); when a caller already has
    Sessions in hand (monitor.metrics()), build the list from those instead and pass it in."""
    from .adapters import load_all
    sessions = [s for s in load_all() if s.harness == "claude-code" and not s.sidechain]
    if days:
        cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        sessions = [s for s in sessions if (s.first or "")[:19] >= cutoff]
    used = set()
    for s in sessions:
        used.update(s.usage.keys())
    return sorted(used)


def credentials() -> dict:
    """provider -> bool. Presence only — never reads or returns a secret value."""
    cred = {"anthropic": False, "openai": False, "xai": False, "google": False}
    if os.environ.get(PROVIDER_ENV["anthropic"]):
        cred["anthropic"] = True
    else:
        try:
            r = subprocess.run(["security", "find-generic-password", "-s", "Claude Code-credentials"],
                                capture_output=True, timeout=5)
            cred["anthropic"] = r.returncode == 0
        except Exception:  # noqa: BLE001 — no `security` (non-macOS), or it hung/errored: treat as absent
            pass
    codex_auth = _read_json(CODEX_AUTH)
    cred["openai"] = bool(os.environ.get(PROVIDER_ENV["openai"])) or bool(isinstance(codex_auth, dict) and codex_auth)
    grok_auth = _read_json(GROK_AUTH)
    cred["xai"] = bool(os.environ.get(PROVIDER_ENV["xai"])) or bool(isinstance(grok_auth, dict) and grok_auth)
    cred["google"] = bool(os.environ.get(PROVIDER_ENV["google"]))
    return cred


# --- the ladder: parse ~/.agents/POLICY.md between the markers --------------

def _find_ladder_span(text: str) -> tuple[int, int] | None:
    """(content_start, content_end): the span strictly between the marker lines. None if absent."""
    if LADDER_START not in text or LADDER_END not in text:
        return None
    s = text.index(LADDER_START)
    nl = text.index("\n", s)
    e = text.index(LADDER_END, nl)
    return nl + 1, e


def _split_ladder_cell(cell: str) -> list[str]:
    """'Grok 4.6, Grok 4.5' -> ['Grok 4.6', 'Grok 4.5']; 'GPT-5.6 Sol/Terra' -> ['GPT-5.6 Sol',
    'GPT-5.6 Terra'] (the leading words before the last, slash-joined token are treated as a
    shared prefix)."""
    out = []
    for part in cell.split(","):
        part = part.strip()
        if not part or part in ("—", "-", "–"):
            continue
        tokens = part.split()
        if tokens and "/" in tokens[-1]:
            prefix = " ".join(tokens[:-1])
            out.extend(f"{prefix} {alt}".strip() for alt in tokens[-1].split("/") if alt)
        else:
            out.append(part)
    return out


def parse_ladder(text: str) -> dict:
    """{provider_id: {"orchestrate": [names], "volume": [names], "triage": [names], "note": str}}."""
    span = _find_ladder_span(text)
    if span is None:
        return {}
    block = text[span[0]:span[1]]
    rows: dict = {}
    provider_map = {v.lower(): k for k, v in PROVIDER_LABEL.items()}
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        head = cells[0].lower()
        if head in ("provider", "") or set(cells[0]) <= {"-"}:
            continue
        pid = provider_map.get(head, head)
        rows[pid] = dict(
            orchestrate=_split_ladder_cell(cells[1]),
            volume=_split_ladder_cell(cells[2]),
            triage=_split_ladder_cell(cells[3]),
            note=cells[4] if len(cells) > 4 else "",
        )
    return rows


# --- matching a ladder entry name to a real catalogue/cache id --------------

def _normalize(name: str, provider: str) -> str:
    s = re.sub(r"[()]", " ", name.lower())
    s = re.sub(r"[.\s_/]+", "-", s).strip("-")
    s = re.sub(r"-+", "-", s)
    prefix = {"anthropic": "claude", "openai": "gpt", "xai": "grok"}.get(provider)
    if prefix and not s.startswith(prefix):
        s = f"{prefix}-{s}"
    return s


def _is_descriptive_only(name: str) -> bool:
    """True for prose with no digit and no word outside the filler list — not a model claim."""
    if re.search(r"\d", name):
        return False
    words = set(re.findall(r"[a-z]+", name.lower()))
    return bool(words) and words <= (_FILLER_WORDS | {"gpt"})


def resolve_ladder_entry(name: str, provider: str, models_dev: dict, cli_ids: list[str]) -> dict | None:
    """Map a human ladder-table entry ('Grok 4.6', 'Claude Fable 5.1', 'GPT-6 Astra') to a concrete
    id. Returns {'id', 'family', 'release_date', 'cost', 'source'} or None — None is LADDER-UNKNOWN.
    A pure-prose entry with no model claim in it (no digit, no non-filler word) resolves to a
    descriptive placeholder rather than None, so it never causes a false LADDER-UNKNOWN."""
    norm = _normalize(name, provider)
    cat = provider_catalogue(models_dev, provider)

    def _pack(mid, info, source):
        return dict(id=mid, family=info.get("family"), release_date=info.get("release_date"), cost=info.get("cost") or {}, source=source)

    for mid, info in cat.items():
        if _normalize(mid, provider) == norm:
            return _pack(mid, info, "models.dev")
    for mid in cli_ids:
        if _normalize(mid, provider) == norm:
            return dict(id=mid, family=None, release_date=None, cost={}, source="cli-cache")

    # A coarse major-version prefix ('gpt-6' out of 'GPT-6 standard tier') is enough to say "this
    # generation exists" without claiming a specific model — this is what lets prose like that
    # resolve. Requiring a digit in the prefix is deliberate: a bare family name with no digit
    # ('claude-opus' out of 'Opus 3', a version that does not exist) must NOT match here, or
    # LADDER-UNKNOWN could never catch a fabricated version number.
    tok = "-".join(norm.split("-")[:2])
    if tok and any(ch.isdigit() for ch in tok):
        cands = [(mid, info) for mid, info in cat.items() if _normalize(mid, provider).startswith(tok)]
        if cands:
            mid, info = max(cands, key=lambda kv: kv[1].get("release_date") or "")
            return _pack(mid, info, "models.dev (prefix match)")
        for mid in cli_ids:
            if _normalize(mid, provider).startswith(tok):
                return dict(id=mid, family=None, release_date=None, cost={}, source="cli-cache (prefix match)")

    if _is_descriptive_only(name):
        return dict(id=None, family=None, release_date=None, cost={}, source="descriptive")
    return None


def _guess_family(name: str, provider: str) -> str | None:
    words = re.findall(r"[a-z]+", name.lower())
    kw = _FAMILY_KEYWORDS.get(provider, {})
    for w in words:
        if w in kw:
            return kw[w]
    return None


# --- the snapshot + drift rules ----------------------------------------------

def _cli_ids_by_provider(claude_used_models: list[str] | None, days: int) -> dict:
    ids = dict(cli_available_models())
    ids["anthropic"] = list(claude_used_models) if claude_used_models is not None else claude_used_models_from_disk(days)
    return ids


def snapshot(days: int = 30, refresh: bool = False, claude_used_models: list[str] | None = None) -> dict:
    """Everything `teyla models` reports, gathered once. Pass `claude_used_models` (a list of
    model ids already known to a caller, e.g. monitor.metrics()) to skip a second session scan."""
    models_dev, source = load_models_dev_catalogue(refresh=refresh)
    from . import policy as _policy
    policy_text = _policy.POLICY.read_text() if _policy.POLICY.exists() else ""
    ladder = parse_ladder(policy_text)
    cli_ids = _cli_ids_by_provider(claude_used_models, days)
    cred = credentials()
    codex_model = codex_config_model()
    hermes_provider = hermes_active_provider()

    providers = {}
    for p in PROVIDERS:
        providers[p] = dict(
            credential=cred.get(p, False),
            available=sorted(set(cli_ids.get(p, []))),
            newest=newest_models(models_dev, p, n=5),
            ladder=ladder.get(p) or {"orchestrate": [], "volume": [], "triage": [], "note": ""},
        )
    return dict(
        days=days, generated=_dt.date.today().isoformat(), models_dev_source=source,
        codex_config_model=codex_model, hermes_provider=hermes_provider,
        providers=providers, ladder=ladder, credentials=cred,
    )


def _is_dated_variant(prefix: str, model_id: str) -> bool:
    """Same rule pricing.lookup() relies on (a prefix match), but stricter: 'claude-opus-5-20260401'
    is a dated variant of 'claude-opus-5' (suffix is digits/hyphens only); 'gpt-5.5-pro' is a
    different, more expensive SKU and must NOT be treated as a variant of the bare 'gpt-5.5'."""
    if model_id == prefix:
        return True
    if not model_id.startswith(prefix):
        return False
    suffix = model_id[len(prefix):]
    return bool(suffix) and re.fullmatch(r"-[\d-]+", suffix) is not None


def _pct_diff(a, b) -> float:
    if not b:
        return 0.0
    return abs(a - b) / abs(b)


def drift(snap: dict) -> list[dict]:
    """Pure function over a snapshot — no IO, no network. Flags: LADDER-UNKNOWN, NEWER-AVAILABLE,
    NO-CREDENTIAL, UNLISTED-PROVIDER, PRICE-STALE."""
    from . import pricing

    flags = []
    ladder = snap.get("ladder") or {}
    providers = snap.get("providers") or {}
    cred = snap.get("credentials") or {}

    # LADDER-UNKNOWN / NEWER-AVAILABLE need the real catalogue for family + release_date lookups.
    # Read-only, local cache only (refresh=False) — this is the network-free guarantee A11 relies on.
    md, _ = load_models_dev_catalogue(refresh=False)

    for provider, rows in ladder.items():
        cli_ids = providers.get(provider, {}).get("available", [])
        cat = provider_catalogue(md, provider)
        for tier_name in ("orchestrate", "volume", "triage"):
            # ids already named in this tier: a newer model listed beside an older one is not drift
            tier_ids = {r.get("id") for r in (resolve_ladder_entry(n, provider, md, cli_ids) for n in rows.get(tier_name, [])) if r}
            for name in rows.get(tier_name, []):
                resolved = resolve_ladder_entry(name, provider, md, cli_ids)
                if resolved is None:
                    flags.append(dict(flag="LADDER-UNKNOWN", provider=provider, tier=tier_name, entry=name,
                                       detail=f"'{name}' matches no model in any catalogue or cache"))
                    continue
                if tier_name in ("orchestrate", "volume") and resolved.get("family") and resolved.get("release_date"):
                    fam, rd = resolved["family"], resolved["release_date"]
                    def _text_model(info):
                        out = (info.get("modalities") or {}).get("output") or ["text"]
                        return "text" in out
                    newer = [(mid, info) for mid, info in cat.items()
                             if info.get("family") == fam and (info.get("release_date") or "") > rd
                             and mid not in tier_ids and _text_model(info)]
                    if newer:
                        mid, info = max(newer, key=lambda kv: kv[1].get("release_date") or "")
                        flags.append(dict(flag="NEWER-AVAILABLE", provider=provider, tier=tier_name, entry=name,
                                           detail=f"ladder has '{name}' ({rd}); catalogue has {mid} ({info.get('release_date')})"))

    # NO-CREDENTIAL: a ladder row for a provider we have no credential for.
    for provider in ladder:
        if not cred.get(provider, False):
            flags.append(dict(flag="NO-CREDENTIAL", provider=provider, tier=None, entry=None,
                               detail=f"{PROVIDER_LABEL.get(provider, provider)} has a ladder row but no credential/env/CLI auth found"))

    # UNLISTED-PROVIDER: a credential we have, with no ladder row at all.
    for provider in ("anthropic", "openai", "xai", "google"):
        if cred.get(provider) and provider not in ladder:
            flags.append(dict(flag="UNLISTED-PROVIDER", provider=provider, tier=None, entry=None,
                               detail=f"a credential is present for {provider} but POLICY.md's ladder has no row for it"))

    # PRICE-STALE: pricing.py entries vs. the catalogue, and ladder-referenced models missing from pricing.py.
    prices = pricing.effective_prices()
    for prefix, row in prices.items():
        in_price, _cw, _cr, out_price = row[:4]
        best = None
        for provider in PROVIDERS:
            for mid, info in provider_catalogue(md, provider).items():
                if _is_dated_variant(prefix, mid):
                    if best is None or (info.get("release_date") or "") > (best.get("release_date") or ""):
                        best = info
        if not best:
            continue
        cost = best.get("cost") or {}
        ci, co = cost.get("input"), cost.get("output")
        if ci is None or co is None:
            continue
        if _pct_diff(in_price, ci) > 0.2 or _pct_diff(out_price, co) > 0.2:
            flags.append(dict(flag="PRICE-STALE", provider=None, tier=None, entry=prefix,
                               detail=f"pricing.py '{prefix}' is in ${in_price}/out ${out_price}; "
                                      f"catalogue is in ${ci}/out ${co} per 1M tokens"))
    for provider, rows in ladder.items():
        cli_ids = providers.get(provider, {}).get("available", [])
        for tier_name in ("orchestrate", "volume", "triage"):
            # ids already named in this tier: a newer model listed beside an older one is not drift
            tier_ids = {r.get("id") for r in (resolve_ladder_entry(n, provider, md, cli_ids) for n in rows.get(tier_name, [])) if r}
            for name in rows.get(tier_name, []):
                resolved = resolve_ladder_entry(name, provider, md, cli_ids)
                if resolved and resolved.get("id") and pricing.lookup(resolved["id"]) is None:
                    flags.append(dict(flag="PRICE-STALE", provider=provider, tier=tier_name, entry=name,
                                       detail=f"'{name}' ({resolved['id']}) has no entry in pricing.py"))

    return flags


# --- rendering ----------------------------------------------------------------

def render_table(snap: dict, flags: list[dict]) -> str:
    L = [f"teyla models — {snap.get('generated')} (window: {snap.get('days')}d)", ""]
    if snap.get("codex_config_model"):
        L.append(f"codex config model: {snap['codex_config_model']}")
    if snap.get("hermes_provider"):
        L.append(f"hermes active provider: {snap['hermes_provider']}")
    for p in PROVIDERS:
        row = snap["providers"][p]
        L.append(f"\n{PROVIDER_LABEL[p]}")
        L.append(f"  credential: {'yes' if row['credential'] else 'no'}")
        L.append(f"  available on this machine: {', '.join(row['available']) or '(none seen)'}")
        L.append("  newest in catalogue:")
        for m in row["newest"]:
            cost = f"in ${m['cost_in']}/out ${m['cost_out']} per 1M" if m["cost_in"] is not None else "cost n/a"
            L.append(f"    {m['id']:32} {m['release_date'] or '?':10} {cost}")
        ladder = row["ladder"]
        L.append(f"  ladder: orchestrate={', '.join(ladder['orchestrate']) or '—'} | "
                  f"volume={', '.join(ladder['volume']) or '—'} | triage={', '.join(ladder['triage']) or '—'}")
        if ladder.get("note"):
            L.append(f"  note: {ladder['note']}")
    L.append(f"\ndrift ({len(flags)}):")
    if not flags:
        L.append("  none")
    for f in flags:
        where = " ".join(x for x in (f.get("provider"), f.get("tier")) if x)
        L.append(f"  [{f['flag']}] {where + ': ' if where else ''}{f['detail']}")
    return "\n".join(L) + "\n"


def render_json(snap: dict, flags: list[dict]) -> dict:
    return dict(snapshot=snap, drift=flags)


# --- --write-policy: rewrite the ladder table between the markers -----------

def absent_providers(credentials: dict, cli_ids_by_provider: dict) -> list[str]:
    """Providers with neither a credential nor anything in a local CLI cache — nothing says
    this provider is actually usable here. Used by --write-policy to decide what --drop-absent
    would remove, and to warn about it when the flag isn't passed."""
    return [p for p in PROVIDERS if not credentials.get(p) and not cli_ids_by_provider.get(p)]


def propose_ladder_rows(ladder: dict, models_dev: dict, cli_ids_by_provider: dict,
                         credentials: dict | None = None, drop_absent: bool = False) -> dict:
    """{provider: {"orchestrate": [...], "volume": [...], "triage": [...], "note": str}} — keeps
    every entry that still resolves to something; replaces one that resolves to nothing with the
    newest model of a keyword-guessed family, if any; otherwise leaves it as a manual TODO.

    With `drop_absent`, a provider in `absent_providers()` (no credential, no CLI cache) is left
    out of the result entirely — `_render_ladder_table_text` then renders no row for it at all."""
    out = {}
    absent = set(absent_providers(credentials or {}, cli_ids_by_provider)) if drop_absent else set()
    for provider in PROVIDERS:
        if provider in absent:
            continue
        rows = ladder.get(provider) or {"orchestrate": [], "volume": [], "triage": [], "note": ""}
        cli_ids = cli_ids_by_provider.get(provider, [])
        cat = provider_catalogue(models_dev, provider)
        new_rows = {}
        for tier_name in ("orchestrate", "volume", "triage"):
            new_names = []
            for name in rows.get(tier_name) or []:
                if resolve_ladder_entry(name, provider, models_dev, cli_ids) is not None:
                    new_names.append(name)
                    continue
                fam = _guess_family(name, provider)
                same_fam = [(mid, info) for mid, info in cat.items() if fam and info.get("family") == fam]
                if same_fam:
                    _, info = max(same_fam, key=lambda kv: kv[1].get("release_date") or "")
                    new_names.append(info.get("name") or _)
                else:
                    new_names.append(f"{name} [unverified — no match in any catalogue/cache]")
            new_rows[tier_name] = new_names
        new_rows["note"] = rows.get("note", "")
        out[provider] = new_rows
    return out


def _render_ladder_table_text(rows_by_provider: dict, reviewed_date: str) -> str:
    lines = ["| provider | orchestrate / hardest tasks | volume work | throwaway / triage | note |",
             "|---|---|---|---|---|"]
    for provider in PROVIDERS:
        if provider not in rows_by_provider:
            continue
        row = rows_by_provider[provider]
        base_note = re.sub(r"\s*—\s*reviewed \d{4}-\d{2}-\d{2} by teyla models\s*$", "", row.get("note") or "").strip()
        note = f"{base_note} — reviewed {reviewed_date} by teyla models" if base_note else f"reviewed {reviewed_date} by teyla models"
        lines.append("| {} | {} | {} | {} | {} |".format(
            PROVIDER_LABEL[provider],
            ", ".join(row["orchestrate"]) or "—",
            ", ".join(row["volume"]) or "—",
            ", ".join(row["triage"]) or "—",
            note,
        ))
    return "\n".join(lines) + "\n"


def write_policy(path: pathlib.Path | None = None, dry: bool = False, days: int = 30,
                  claude_used_models: list[str] | None = None, drop_absent: bool = False) -> tuple[str, bool]:
    """Rewrite the ladder table strictly between the markers in `path` (default ~/.agents/POLICY.md).
    Returns (unified diff, changed). Nothing outside the span between the marker lines is touched.
    `drop_absent` removes the row for any provider with no credential and no CLI cache; without
    it those rows are kept as-is (call `absent_providers()` to warn about them instead)."""
    from . import policy as _policy
    target = path or _policy.POLICY
    text = target.read_text()
    span = _find_ladder_span(text)
    if span is None:
        raise ValueError(f"{target}: no {LADDER_START} .. {LADDER_END} markers found")
    cs, ce = span
    old_block = text[cs:ce]

    ladder = parse_ladder(text)
    models_dev, _source = load_models_dev_catalogue(refresh=False)
    cli_ids = _cli_ids_by_provider(claude_used_models, days)
    cred = credentials()
    proposed = propose_ladder_rows(ladder, models_dev, cli_ids, credentials=cred, drop_absent=drop_absent)
    new_block = _render_ladder_table_text(proposed, _dt.date.today().isoformat())

    new_text = text[:cs] + new_block + text[ce:]
    diff = "\n".join(difflib.unified_diff(
        old_block.splitlines(), new_block.splitlines(),
        fromfile=f"{target} (current ladder)", tofile=f"{target} (proposed)", lineterm=""))
    changed = new_text != text
    if changed and not dry:
        target.write_text(new_text)
    return diff, changed


# --- --write-prices: ~/.teyla/prices.json, loaded by pricing.py -------------

def build_prices_dict(models_dev: dict, ladder: dict, cli_ids_by_provider: dict) -> dict:
    """prefix -> {input, cache_write, cache_read, output, tier, verified, source, date}. Scoped to
    the three ladder providers (the same scope pricing.PRICES already covers). Tier comes from
    whichever ladder row (if any) the model resolves under; "unknown" otherwise."""
    today = _dt.date.today().isoformat()
    tier_by_id: dict[str, str] = {}
    for provider, rows in (ladder or {}).items():
        cli_ids = cli_ids_by_provider.get(provider, [])
        for tier_name in ("orchestrate", "volume", "triage"):
            for name in rows.get(tier_name, []):
                resolved = resolve_ladder_entry(name, provider, models_dev, cli_ids)
                if resolved and resolved.get("id"):
                    tier_by_id[resolved["id"]] = tier_name
    out = {}
    for provider in PROVIDERS:
        for mid, info in provider_catalogue(models_dev, provider).items():
            cost = info.get("cost") or {}
            if cost.get("input") is None or cost.get("output") is None:
                continue
            out[mid] = dict(
                input=cost["input"], cache_write=cost.get("cache_write", cost["input"]),
                cache_read=cost.get("cache_read", 0), output=cost["output"],
                tier=tier_by_id.get(mid, "unknown"), verified=True, source="models.dev", date=today,
            )
    return out


def write_prices(path: pathlib.Path | None = None, days: int = 30,
                  claude_used_models: list[str] | None = None) -> pathlib.Path:
    target = path or PRICES_OUT
    models_dev, _source = load_models_dev_catalogue(refresh=False)
    from . import policy as _policy
    text = _policy.POLICY.read_text() if _policy.POLICY.exists() else ""
    ladder = parse_ladder(text)
    cli_ids = _cli_ids_by_provider(claude_used_models, days)
    data = build_prices_dict(models_dev, ladder, cli_ids)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return target


# --- CLI ----------------------------------------------------------------------

def cmd_models(args):
    snap = snapshot(days=args.days, refresh=args.refresh)
    flags = drift(snap)
    if args.write_policy:
        drop_absent = getattr(args, "drop_absent", False)
        diff, changed = write_policy(dry=args.dry, days=args.days, drop_absent=drop_absent)
        print(diff or "(no changes)")
        if changed:
            from . import policy as _policy
            print(("(dry run — not written) " if args.dry else "wrote ") + str(_policy.POLICY))
        if not drop_absent:
            for p in PROVIDERS:
                if p in snap["ladder"] and not snap["providers"][p]["credential"] and not snap["providers"][p]["available"]:
                    print(f"provider {PROVIDER_LABEL[p]} has no credential — pass --drop-absent to remove its row")
        return 0
    if args.write_prices:
        path = write_prices(days=args.days)
        print(f"wrote {path}")
        return 0
    if args.json:
        print(json.dumps(render_json(snap, flags), indent=2, default=str))
    else:
        print(render_table(snap, flags))
    return 1 if flags else 0


def register(sp):
    """Add `teyla models` to an argparse subparsers object."""
    q = sp.add_parser("models", help="model ladder + price drift report; fixes with --write-policy/--write-prices")
    q.set_defaults(fn=cmd_models)
    q.add_argument("--days", type=int, default=30, help="window for 'used in Claude Code' models (default: 30)")
    q.add_argument("--json", action="store_true")
    q.add_argument("--refresh", action="store_true", help="fetch models.dev/api.json if the local cache is missing/stale (opt-in network)")
    q.add_argument("--write-policy", action="store_true", help="rewrite the ladder table in ~/.agents/POLICY.md, between the markers only")
    q.add_argument("--write-prices", action="store_true", help="write ~/.teyla/prices.json from the models.dev catalogue")
    q.add_argument("--dry", action="store_true", help="with --write-policy: print the diff, don't write")
    q.add_argument("--drop-absent", action="store_true",
                    help="with --write-policy: remove ladder rows for providers with no credential and no CLI cache")
    return q
