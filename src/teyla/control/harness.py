"""Running one step — a shell command, or a model behind a CLI.

This is the *inside* of the loop's Draft box and nowhere else. The engine decides
what runs, in what order, and what happens to the output; this file only knows
how to start a process, hold it to a wall-clock cap, and read back what it said.
That separation is the whole design: the model is called here, so it cannot skip
the gate that is decided there.

Three harnesses, and they are not equally enforceable — which is worth stating
plainly rather than burying:

    claude   `claude -p --output-format json` — every tool call goes through the
             PreToolUse hook, so all five capability schemes are enforced per call,
             and usage and cost come back in the JSON.
    codex    `codex exec --sandbox read-only|workspace-write` — one sandbox flag
             derived from whether any `fs.write:` grant exists. Coarse.
    grok     `grok -p --output-format plain --deny ...` — a deny list derived from
             the ungranted schemes. Coarser still.

Only Claude Code gets per-capability enforcement. For the other two the grant list
is an intent, and the sandbox flag is the enforcement. Do not read a `send:`-free
manifest as proof a Codex step could not send.
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import shutil
import subprocess
import time

# Built-in tools every agent step gets, because a step that cannot read cannot draft.
BASELINE_TOOLS = ("Read", "Grep", "Glob", "TodoWrite")


@dataclasses.dataclass
class StepResult:
    ok: bool
    output: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration_s: float = 0.0
    tokens: dict | None = None
    cost_usd: float | None = None
    error: str | None = None
    argv: list = dataclasses.field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "exit_code": self.exit_code, "duration_s": round(self.duration_s, 2),
            "tokens": self.tokens, "cost_usd": self.cost_usd, "error": self.error,
            "argv": [str(a) for a in self.argv[:2]],
        }


def step_env(base: dict | None, *, run_id: str, grants_path, run_dir, repo) -> dict:
    """The environment every step runs under. `TEYLA_GRANTS` is the one that matters:
    hook commands inherit the environment of the process that spawned the harness, so
    setting it here is what arms the PreToolUse hook for this run and nothing else."""
    env = dict(base if base is not None else os.environ)
    env["TEYLA_RUN_ID"] = str(run_id)
    env["TEYLA_GRANTS"] = str(grants_path)
    env["TEYLA_RUN_DIR"] = str(run_dir)
    env["TEYLA_REPO"] = str(repo)
    env["TEYLA_UNDO"] = str(pathlib.Path(run_dir) / "undo.md")
    return env


# --- prompts -------------------------------------------------------------------------


def build_prompt(step, rules_block: str, *, repo, draft: str | None = None, critic: bool = False) -> str:
    """The agent prompt: rules first, then context, then the task.

    Rules go first and are labelled as non-negotiable because they are the part the
    model is most likely to reason its way out of when it appears last, under the
    task, as one consideration among several."""
    parts = [
        "You are running as one step of a Teyla routine. The loop around you is code: "
        "it decided that you run now, it will decide what happens to your output, and it "
        "will write a receipt. Do the step and nothing else.",
        "",
        "## Rules in force (non-negotiable)",
        rules_block,
    ]
    context = list(step.context or ())
    if context:
        parts += ["", "## Context paths (read these first)"]
        parts += [f"- {c}" for c in context]
        parts += ["", f"They are relative to the repository root: {repo}"]
    if step.skill:
        parts += ["", "## Skill", f"Follow the `{step.skill}` skill. Do not improvise a procedure around it."]
    if draft is not None:
        parts += ["", "## Draft under review", "```", draft.strip(), "```"]
    parts += ["", "## Task", step.prompt.strip()]
    if critic:
        parts += [
            "",
            "## Output contract",
            "The FIRST line of your reply must be exactly `PASS` or `FAIL` and nothing else. "
            "Write `FAIL` if the draft breaks any rule above, or if you cannot verify that it does not. "
            "Everything after the first line is your reasoning, one short paragraph.",
        ]
    else:
        parts += ["", "## Output contract",
                  "Write the finished artifact to stdout. No preamble, no commentary, no questions."]
    return "\n".join(parts)


def allowed_tools(grants: dict) -> list[str]:
    """`--allowedTools` for `claude -p`, derived from the grants.

    Belt and braces: the hook is the enforcement, and this list is the same policy
    stated up front so the model is not repeatedly proposing calls that will be
    refused. Disagreement between the two is always resolved by the hook."""
    out = list(BASELINE_TOOLS)
    if grants.get("fs.write"):
        out += ["Write", "Edit", "MultiEdit"]
    if grants.get("shell"):
        out.append("Bash")
    if grants.get("net"):
        out += ["WebFetch", "WebSearch"]
    out += list(grants.get("tool") or [])
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def deny_list(grants: dict) -> list[str]:
    """`--deny` for grok: the schemes this run was *not* granted."""
    out = []
    if not grants.get("shell"):
        out.append("shell")
    if not grants.get("fs.write"):
        out.append("write")
    if not grants.get("net"):
        out.append("net")
    if not grants.get("send"):
        out.append("send")
    return out


# --- execution -------------------------------------------------------------------------


def _run(argv, *, cwd, env, timeout_s, stdin_text=None) -> tuple[int | None, str, str, float, str | None]:
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            [str(a) for a in argv], cwd=str(cwd), env=env, input=stdin_text,
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or "") if isinstance(e.stdout, str) else "", "", time.monotonic() - t0, \
               f"timed out after {timeout_s:.0f}s (caps.max_minutes)"
    except (OSError, ValueError) as e:
        return None, "", "", time.monotonic() - t0, f"could not start {argv[0]!r}: {e}"
    return proc.returncode, proc.stdout or "", proc.stderr or "", time.monotonic() - t0, None


def run_command_step(step, *, cwd, env, timeout_s) -> StepResult:
    argv = ["/bin/sh", "-c", step.run]
    rc, out, err, dur, error = _run(argv, cwd=cwd, env=env, timeout_s=timeout_s)
    return StepResult(
        ok=(error is None and rc == 0), output=out, stderr=err, exit_code=rc,
        duration_s=dur, error=error or (None if rc == 0 else f"command exited {rc}"),
        argv=["/bin/sh", "-c"],
    )


def run_agent_step(step, *, cwd, env, timeout_s, grants: dict, caps: dict, prompt: str,
                   out_path=None) -> StepResult:
    harness = step.harness
    binary = shutil.which(harness)
    if binary is None:
        return StepResult(
            ok=False,
            error=(f"the routine asks for the {harness!r} harness and no `{harness}` binary is on PATH. "
                   f"Install it, or change this step's `harness` in teyla.toml."),
        )

    if harness == "claude":
        argv = [binary, "-p", prompt, "--output-format", "json",
                "--max-turns", str(caps.get("max_turns", 30))]
        tools = allowed_tools(grants)
        if tools:
            argv += ["--allowedTools", ",".join(tools)]
        rc, out, err, dur, error = _run(argv, cwd=cwd, env=env, timeout_s=timeout_s)
        text, usage, cost, is_error = _parse_claude_json(out)
        return StepResult(
            ok=(error is None and rc == 0 and not is_error),
            output=text if text is not None else out, stderr=err, exit_code=rc, duration_s=dur,
            tokens=usage, cost_usd=cost,
            error=error or (f"claude exited {rc}" if rc not in (0, None) else ("claude reported an error result" if is_error else None)),
            argv=[binary, "-p"],
        )

    if harness == "codex":
        sandbox = "workspace-write" if grants.get("fs.write") or grants.get("shell") else "read-only"
        out_path = pathlib.Path(out_path) if out_path else None
        argv = [binary, "exec", "--sandbox", sandbox]
        if out_path:
            argv += ["-o", str(out_path)]
        argv.append(prompt)
        rc, out, err, dur, error = _run(argv, cwd=cwd, env=env, timeout_s=timeout_s)
        text = out
        if out_path and out_path.exists():
            try:
                got = out_path.read_text(errors="replace")
                if got.strip():
                    text = got
            except OSError:
                pass
        return StepResult(
            ok=(error is None and rc == 0), output=text, stderr=err, exit_code=rc, duration_s=dur,
            error=error or (None if rc == 0 else f"codex exited {rc}"), argv=[binary, "exec"],
        )

    # grok
    argv = [binary, "-p", prompt, "--output-format", "plain"]
    for d in deny_list(grants):
        argv += ["--deny", d]
    rc, out, err, dur, error = _run(argv, cwd=cwd, env=env, timeout_s=timeout_s)
    return StepResult(
        ok=(error is None and rc == 0), output=out, stderr=err, exit_code=rc, duration_s=dur,
        error=error or (None if rc == 0 else f"grok exited {rc}"), argv=[binary, "-p"],
    )


def _parse_claude_json(raw: str):
    """`claude -p --output-format json` -> (text, usage, cost_usd, is_error).

    Defensive on purpose: the shape has changed before, and a routine that dies
    because a cost field was renamed is worse than a routine with no cost in its
    receipt. Anything unparseable falls back to the raw text with no usage."""
    raw = (raw or "").strip()
    if not raw:
        return None, None, None, False
    try:
        data = json.loads(raw)
    except ValueError:
        return None, None, None, False
    if isinstance(data, list):
        data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), None) \
               or (data[-1] if data and isinstance(data[-1], dict) else {})
    if not isinstance(data, dict):
        return None, None, None, False
    text = data.get("result")
    if not isinstance(text, str):
        text = None
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
    if usage:
        usage = {k: v for k, v in usage.items() if isinstance(v, (int, float))}
    cost = data.get("total_cost_usd") or data.get("cost_usd")
    cost = cost if isinstance(cost, (int, float)) else None
    return text, usage, cost, bool(data.get("is_error"))
