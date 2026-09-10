"""Per-token prices, USD per million tokens. EDIT THIS TABLE — it is data, not a claim.

Values marked verified=False were not checked against a vendor price page at the time of writing.
`teyla monitor` computes cost only for models present here and labels the total "estimate".
Tiers: which rung of the model ladder a model sits on (orchestrate / volume / triage), per POLICY.md.

`~/.teyla/prices.json`, written by `teyla models --write-prices` from the models.dev catalogue,
overrides this table when present (`effective_prices()`); PRICES itself is always the fallback so
a fresh install with no cache still prices something. `teyla models` flags a >20% gap between the
two, or a model missing from PRICES, as PRICE-STALE.
"""
import json
import pathlib

PRICES = {
    # model prefix: (input, cache_write, cache_read, output, tier, verified)  — USD per 1M tokens
    # Anthropic, per finout.io / tminusai.com 2026-09 (not from the vendor page): verify before quoting.
    "claude-fable-5": (10.0, 12.5, 0.25, 50.0, "orchestrate", False),
    "claude-opus-5": (5.0, 6.25, 0.5, 25.0, "volume", False),
    "claude-opus-4": (5.0, 6.25, 0.5, 25.0, "volume", False),
    "claude-sonnet-5": (2.0, 2.5, 0.2, 10.0, "volume", False),
    "claude-sonnet-4": (3.0, 3.75, 0.3, 15.0, "volume", False),
    "claude-haiku-4": (1.0, 1.25, 0.1, 5.0, "triage", False),
    # OpenAI, per cloudzero / layer3labs 2026-09
    "gpt-6-astra": (10.0, 10.0, 2.5, 50.0, "orchestrate", False),
    "gpt-5.6-sol": (4.0, 4.0, 1.0, 20.0, "volume", False),
    "gpt-5.6-terra": (2.0, 2.0, 0.5, 12.0, "volume", False),
    "gpt-5.6-luna": (0.2, 0.2, 0.05, 1.2, "triage", False),
    "gpt-5.5": (5.0, 5.0, 1.25, 30.0, "volume", False),
    # xAI, per mem0 / layer3labs 2026-09 (single public tier)
    "grok-4.5": (2.0, 2.0, 0.5, 6.0, "volume", False),
    "grok-4.6": (2.0, 2.0, 0.5, 6.0, "orchestrate", False),
}


OVERRIDE_PATH = pathlib.Path.home() / ".teyla" / "prices.json"


def _load_overrides() -> dict:
    """~/.teyla/prices.json -> {prefix: (input, cache_write, cache_read, output, tier, verified)}.
    Malformed or absent -> {} so PRICES alone still works; each row is validated independently so
    one bad entry doesn't take down the rest."""
    try:
        raw = json.loads(OVERRIDE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for prefix, row in (raw or {}).items():
        try:
            out[prefix] = (row["input"], row.get("cache_write", row["input"]), row.get("cache_read", 0.0),
                           row["output"], row.get("tier", "unknown"), bool(row.get("verified", True)))
        except (KeyError, TypeError):
            continue
    return out


def effective_prices() -> dict:
    """PRICES with ~/.teyla/prices.json layered on top (override wins per prefix). Reloaded on
    every call — cheap (a small local file) and picks up a fresh --write-prices without a restart."""
    merged = dict(PRICES)
    merged.update(_load_overrides())
    return merged


def lookup(model: str):
    """Longest-prefix match so 'claude-opus-5-20260401' resolves to 'claude-opus-5'."""
    prices = effective_prices()
    best = None
    for k in prices:
        if model.startswith(k) and (best is None or len(k) > len(best)):
            best = k
    return prices.get(best) if best else None


def tier(model: str) -> str:
    p = lookup(model)
    return p[4] if p else "unknown"


def cost_usd(model: str, usage: dict) -> float | None:
    p = lookup(model)
    if not p:
        return None
    i, cw, cr, o = p[:4]
    return (usage.get("input_tokens", 0) * i + usage.get("cache_creation_input_tokens", 0) * cw
            + usage.get("cache_read_input_tokens", 0) * cr + usage.get("output_tokens", 0) * o) / 1e6
