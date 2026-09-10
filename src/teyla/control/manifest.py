"""The control-plane half of a `[[routine]]` table in `teyla.toml`.

`routines.py` reads the *legacy* routine shape — `kind`/`label`/`every`, a
declaration that something is scheduled elsewhere and a report on whether it is
still loaded. This module reads the shape that Teyla itself **runs**:

    [[routine]]
    name = "morning-digest"
    gate = "A"
    idempotency = "date"
    trigger = { type = "clock", at = "07:00", tz = "Europe/Madrid", days = "mon-fri" }
    step    = { kind = "command", run = "./bin/digest" }
    act     = { kind = "command", run = "./bin/send-digest" }
    capabilities = ["fs.write:runs/**", "shell:git push", "send:telegram"]
    caps    = { max_minutes = 20, max_writes = 50, max_sends = 1 }
    critic  = { harness = "claude", prompt = "Check the draft against the rules." }

The discriminator is `step`: a routine with a `step` is a control-plane routine
and is validated here; a routine without one is legacy and is left entirely to
`routines.py`. Both may sit in the same file, and both may sit in the same
`[[routine]]` array — nothing in the old shape changes meaning.

Everything in here is pure: it parses, validates and normalises, and never
touches the filesystem beyond reading the manifest it was handed. The run
engine (`engine.py`) is the only thing that acts on what comes out.
"""
from __future__ import annotations

import dataclasses
import pathlib
import re
import tomllib

# --- vocabulary ---------------------------------------------------------------

GATES = ("A", "B", "C")
STEP_KINDS = ("command", "agent")
HARNESSES = ("claude", "codex", "grok")
IDEMPOTENCY = ("date", "none", "input-hash")

# Only `clock` is implemented. `event` and `webhook` parse — so a manifest can
# declare the intent and `teyla triggers` can say plainly that it is not built —
# but nothing installs or fires them. See docs/CONTROL-PLANE.md, "Not built".
TRIGGER_TYPES = ("clock", "manual", "event", "webhook")
IMPLEMENTED_TRIGGER_TYPES = ("clock", "manual")

CAPABILITY_SCHEMES = ("fs.write", "shell", "net", "send", "tool")

DEFAULT_CAPS = {
    "max_minutes": 20,
    "max_output_tokens": 200_000,
    "max_writes": 50,
    "max_sends": 0,
    "max_turns": 30,
}
CAP_KEYS = tuple(DEFAULT_CAPS)

DAY_ORDER = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# launchd's Weekday: 0 and 7 are both Sunday, 1 is Monday.
DAY_TO_LAUNCHD = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0}

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ManifestError(ValueError):
    """A control-plane routine that cannot be run as written."""


# --- dataclasses ---------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Trigger:
    type: str
    at: str | None = None
    tz: str | None = None
    days: tuple[str, ...] = ()

    @property
    def implemented(self) -> bool:
        return self.type in IMPLEMENTED_TRIGGER_TYPES

    def as_dict(self) -> dict:
        return {"type": self.type, "at": self.at, "tz": self.tz, "days": list(self.days)}


@dataclasses.dataclass(frozen=True)
class Step:
    kind: str
    run: str | None = None            # command steps
    harness: str | None = None        # agent steps
    skill: str | None = None
    prompt: str | None = None
    context: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "run": self.run, "harness": self.harness,
            "skill": self.skill, "prompt": self.prompt, "context": list(self.context),
        }


@dataclasses.dataclass(frozen=True)
class Critic:
    harness: str
    prompt: str
    skill: str | None = None

    def as_dict(self) -> dict:
        return {"harness": self.harness, "prompt": self.prompt, "skill": self.skill}


@dataclasses.dataclass(frozen=True)
class Routine:
    name: str
    product: str
    repo: pathlib.Path
    gate: str
    trigger: Trigger
    step: Step
    act: Step | None
    critic: Critic | None
    capabilities: tuple[str, ...]
    caps: dict
    idempotency: str

    @property
    def ref(self) -> str:
        return f"{self.product}:{self.name}"

    @property
    def launchd_label(self) -> str:
        return f"com.teyla.{self.product}.{self.name}"

    def context_paths(self) -> tuple[str, ...]:
        """Every path this routine declares as context, across its steps. This is what
        rule globs are matched against — a rule governs a run because it governs the
        material the run reads, not because it happens to sit in the repo."""
        out: list[str] = []
        for s in (self.step, self.act):
            if s is not None:
                out.extend(s.context)
        seen, uniq = set(), []
        for p in out:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        return tuple(uniq)

    def snapshot(self) -> dict:
        """The manifest as it was read, frozen into the receipt and run.json. A receipt
        that only names the routine is worthless six weeks later, when the manifest has
        moved on and nobody can say what the run was actually allowed to do."""
        return {
            "name": self.name,
            "product": self.product,
            "repo": str(self.repo),
            "gate": self.gate,
            "trigger": self.trigger.as_dict(),
            "step": self.step.as_dict(),
            "act": self.act.as_dict() if self.act else None,
            "critic": self.critic.as_dict() if self.critic else None,
            "capabilities": list(self.capabilities),
            "caps": dict(self.caps),
            "idempotency": self.idempotency,
        }


# --- capability strings ---------------------------------------------------------


def parse_capability(cap: str) -> tuple[str, str]:
    """`"fs.write:runs/**"` -> `("fs.write", "runs/**")`.

    Split on the first colon only, because the value half legitimately contains
    colons (`shell:git push`, `tool:mcp__x__y`) and a naive split would silently
    truncate the grant into something broader or narrower than written."""
    if not isinstance(cap, str) or ":" not in cap:
        raise ManifestError(
            f"capability {cap!r} is not `<scheme>:<value>` — schemes: {', '.join(CAPABILITY_SCHEMES)}"
        )
    scheme, value = cap.split(":", 1)
    scheme, value = scheme.strip(), value.strip()
    if scheme not in CAPABILITY_SCHEMES:
        raise ManifestError(f"capability {cap!r} has unknown scheme {scheme!r} — expected one of {CAPABILITY_SCHEMES}")
    if not value:
        raise ManifestError(f"capability {cap!r} has an empty value")
    return scheme, value


def group_capabilities(caps) -> dict[str, list[str]]:
    """`["fs.write:runs/**", "tool:mcp__loco__*"]` -> `{"fs.write": ["runs/**"], ...}`,
    with every scheme present (empty list = nothing granted under it). The hook reads
    this shape; an absent key and an empty list must not mean different things there."""
    out: dict[str, list[str]] = {s: [] for s in CAPABILITY_SCHEMES}
    for c in caps or []:
        scheme, value = parse_capability(c)
        out[scheme].append(value)
    return out


# --- days ------------------------------------------------------------------------


def parse_days(spec) -> tuple[str, ...]:
    """`"mon-fri"`, `"mon,wed,fri"`, `"daily"`, `["mon","tue"]` -> a tuple of day names.

    An empty/absent spec means every day. Ranges are inclusive and must run forward
    through `DAY_ORDER`: `"fri-mon"` is rejected rather than guessed at, because a
    wrapping range is far more often a typo than an intent."""
    if spec is None or spec == "":
        return DAY_ORDER
    if isinstance(spec, (list, tuple)):
        parts = [str(x).strip().lower() for x in spec]
    else:
        s = str(spec).strip().lower()
        if s in ("daily", "*", "everyday", "every-day", "mon-sun"):
            return DAY_ORDER
        parts = [p.strip() for p in s.split(",") if p.strip()]

    out: list[str] = []
    for part in parts:
        if "-" in part:
            a, _, b = part.partition("-")
            if a not in DAY_ORDER or b not in DAY_ORDER:
                raise ManifestError(f"trigger days {spec!r}: {part!r} is not a range of {DAY_ORDER}")
            i, j = DAY_ORDER.index(a), DAY_ORDER.index(b)
            if i > j:
                raise ManifestError(f"trigger days {spec!r}: range {part!r} runs backwards through the week")
            out.extend(DAY_ORDER[i : j + 1])
        else:
            if part not in DAY_ORDER:
                raise ManifestError(f"trigger days {spec!r}: {part!r} is not one of {DAY_ORDER}")
            out.append(part)
    seen, uniq = set(), []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return tuple(sorted(uniq, key=DAY_ORDER.index))


# --- element parsers ---------------------------------------------------------------


def _parse_trigger(raw, where: str) -> Trigger:
    if raw is None:
        return Trigger(type="manual")
    if not isinstance(raw, dict):
        raise ManifestError(f"{where}: `trigger` must be a table, got {type(raw).__name__}")
    ttype = raw.get("type", "manual")
    if ttype not in TRIGGER_TYPES:
        raise ManifestError(f"{where}: trigger type {ttype!r} unknown — expected one of {TRIGGER_TYPES}")
    if ttype != "clock":
        return Trigger(type=ttype)
    at = raw.get("at")
    if not at or not _TIME_RE.match(str(at)):
        raise ManifestError(f"{where}: clock trigger needs `at` as 24h HH:MM, got {at!r}")
    tz = raw.get("tz")
    if not tz:
        raise ManifestError(f"{where}: clock trigger needs an explicit `tz` (e.g. tz = \"Europe/Madrid\")")
    return Trigger(type="clock", at=str(at), tz=str(tz), days=parse_days(raw.get("days")))


def _parse_step(raw, where: str, label: str) -> Step:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where}: `{label}` must be a table, got {type(raw).__name__}")
    kind = raw.get("kind")
    if kind not in STEP_KINDS:
        raise ManifestError(f"{where}: `{label}.kind` must be one of {STEP_KINDS}, got {kind!r}")
    if kind == "command":
        run = raw.get("run")
        if not isinstance(run, str) or not run.strip():
            raise ManifestError(f"{where}: `{label}` of kind 'command' needs a non-empty `run`")
        return Step(kind="command", run=run)
    harness = raw.get("harness")
    if harness not in HARNESSES:
        raise ManifestError(f"{where}: `{label}.harness` must be one of {HARNESSES}, got {harness!r}")
    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ManifestError(f"{where}: `{label}` of kind 'agent' needs a non-empty `prompt`")
    context = raw.get("context") or []
    if not isinstance(context, list) or any(not isinstance(c, str) for c in context):
        raise ManifestError(f"{where}: `{label}.context` must be a list of path strings")
    skill = raw.get("skill")
    if skill is not None and not isinstance(skill, str):
        raise ManifestError(f"{where}: `{label}.skill` must be a string")
    return Step(kind="agent", harness=harness, skill=skill, prompt=prompt, context=tuple(context))


def _parse_critic(raw, where: str) -> Critic:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where}: `critic` must be a table, got {type(raw).__name__}")
    harness = raw.get("harness")
    if harness not in HARNESSES:
        raise ManifestError(f"{where}: `critic.harness` must be one of {HARNESSES}, got {harness!r}")
    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ManifestError(f"{where}: `critic` needs a non-empty `prompt`")
    skill = raw.get("skill")
    if skill is not None and not isinstance(skill, str):
        raise ManifestError(f"{where}: `critic.skill` must be a string")
    return Critic(harness=harness, prompt=prompt, skill=skill)


def _parse_caps(raw, where: str) -> dict:
    caps = dict(DEFAULT_CAPS)
    if raw is None:
        return caps
    if not isinstance(raw, dict):
        raise ManifestError(f"{where}: `caps` must be a table, got {type(raw).__name__}")
    for k, v in raw.items():
        if k not in CAP_KEYS:
            raise ManifestError(f"{where}: unknown cap {k!r} — expected some of {CAP_KEYS}")
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise ManifestError(f"{where}: cap {k!r} must be a non-negative integer, got {v!r}")
        caps[k] = v
    return caps


# --- the routine ----------------------------------------------------------------------


def is_control_routine(raw: dict) -> bool:
    """A `[[routine]]` entry belongs to the control plane iff it declares a `step`."""
    return isinstance(raw, dict) and isinstance(raw.get("step"), dict)


def parse_routine(raw: dict, *, product: str, repo: pathlib.Path, where: str = "teyla.toml") -> Routine:
    name = raw.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ManifestError(f"{where}: routine `name` must be lowercase-with-dashes, got {name!r}")
    w = f"{where}: routine {name!r}"

    gate = raw.get("gate", "A")
    if gate not in GATES:
        raise ManifestError(f"{w}: gate must be one of {GATES}, got {gate!r}")

    step = _parse_step(raw["step"], w, "step")
    act_raw = raw.get("act")
    act = _parse_step(act_raw, w, "act") if act_raw is not None else None
    if gate in ("B", "C") and act is None:
        raise ManifestError(f"{w}: gate {gate} acts on its own and therefore needs an `act` step")
    if gate == "A" and act is not None:
        # Legal and useful: gate A's act step is what `teyla inbox approve` runs.
        pass

    critic_raw = raw.get("critic")
    critic = _parse_critic(critic_raw, w) if critic_raw is not None else None
    if gate == "C" and critic is None:
        raise ManifestError(f"{w}: gate C is delegated review and therefore needs a `critic`")

    caps_list = raw.get("capabilities") or []
    if not isinstance(caps_list, list):
        raise ManifestError(f"{w}: `capabilities` must be a list of `<scheme>:<value>` strings")
    for c in caps_list:
        parse_capability(c)  # validate, raise with the offending string

    idem = raw.get("idempotency", "date")
    if idem not in IDEMPOTENCY:
        raise ManifestError(f"{w}: idempotency must be one of {IDEMPOTENCY}, got {idem!r}")

    return Routine(
        name=name,
        product=product,
        repo=pathlib.Path(repo),
        gate=gate,
        trigger=_parse_trigger(raw.get("trigger"), w),
        step=step,
        act=act,
        critic=critic,
        capabilities=tuple(caps_list),
        caps=_parse_caps(raw.get("caps"), w),
        idempotency=idem,
    )


def load(path) -> list[Routine]:
    """Every control-plane routine in one `teyla.toml`. Legacy routines are skipped
    silently — they are `routines.py`'s business, and a file is allowed to hold both."""
    path = pathlib.Path(path).expanduser()
    if path.is_dir():
        path = path / "teyla.toml"
    if not path.exists():
        raise ManifestError(f"no teyla.toml at {path}")
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"{path}: invalid TOML: {e}") from e

    product = (data.get("product") or {}).get("name")
    if not product:
        raise ManifestError(f"{path}: [product] is missing required key 'name'")

    out = []
    for raw in data.get("routine") or []:
        if not is_control_routine(raw):
            continue
        out.append(parse_routine(raw, product=product, repo=path.parent, where=str(path)))
    return out
