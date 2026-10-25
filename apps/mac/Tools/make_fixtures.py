#!/usr/bin/env python3
"""Regenerates the Mac app's JSON fixtures (apps/mac/TeylaTests/Fixtures) from the real `teyla` CLI.

    python3 apps/mac/Tools/make_fixtures.py [--keep]

It builds a throwaway HOME with made-up sessions, products and notes (nothing from this machine),
runs `teyla start --json`, `teyla product show --json` and `teyla state --json` against it, and writes
the output. `--keep` leaves the fake HOME in place and prints its path, so the app can be run on it
for screenshots (`HOME=<path> open -n ...`). Needs `uv sync` or `pip install -e .` for the `teyla` package.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = ROOT / "apps" / "mac" / "TeylaTests" / "Fixtures"
NOW = dt.datetime.now(dt.timezone.utc)


def ts(minutes: float) -> str:
    return (NOW - dt.timedelta(days=2) + dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def reply(minutes: float, mid: str, cache_read: int, model: str = "claude-opus-5-5") -> dict:
    return {"type": "assistant", "timestamp": ts(minutes), "message": {
        "id": mid, "role": "assistant", "model": model,
        "usage": {"input_tokens": 100, "output_tokens": 600, "cache_read_input_tokens": cache_read,
                  "cache_creation_input_tokens": 3000},
        "content": [{"type": "text", "text": "Done."}]}}


def write_session(home: pathlib.Path, repo: str, sid: str, title: str, start: float, turns: int = 60,
                  question: str = "") -> None:
    folder = home / ".claude" / "projects" / f"-sample-repos-{repo}"
    folder.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "user", "timestamp": ts(start), "cwd": str(home / "repos" / repo),
              "message": {"role": "user", "content": title}}]
    lines.append({"type": "custom-title", "customTitle": title})
    for i in range(turns):
        lines.append(reply(start + 0.1 + i * 0.4, f"{sid}-{i}", 300_000 + i * 10_000))
        lines.append({"type": "user", "timestamp": ts(start + 0.3 + i * 0.4), "message": {"role": "user", "content": "Go on."}})
    if question:
        lines.pop()                                  # the last "Go on." would count as an answer
        lines[-1]["message"]["content"] = [{"type": "text", "text": question}]
    (folder / f"{sid}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def build_home(home: pathlib.Path) -> None:
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text("{}\n")
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text('model = "gpt-6.1-sol"\n')
    sessions = [("sample-app", "Add a login button", ""),
                ("sample-app", "Fix the settings crash", "Should the login button use the system accent colour?"),
                ("sample-tool", "Write the export command", "")]
    for i, (repo, title, question) in enumerate(sessions):
        write_session(home, repo, f"00000000-0000-4000-8000-00000000000{i + 1}", title, start=i * 90, question=question)
    # Real git checkouts, so the registry has something to attribute to.
    code = home / "repos"
    for repo in ("sample-app", "sample-tool"):
        (code / repo / ".git").mkdir(parents=True)
    teyla_home = home / ".teyla"
    teyla_home.mkdir()
    (teyla_home / "products.toml").write_text(
        '[product.sample-app]\nname = "Sample App"\nrepos = ["~/repos/sample-app"]\naliases = ["sampleapp"]\n'
        'stage = "beta"\nprimary = "ios"\nfocus = true\n\n'
        '[product.sample-tool]\nname = "Sample Tool"\nrepos = ["~/repos/sample-tool"]\nstage = "building"\n'
        'primary = "macos"\nfocus = false\n')
    (teyla_home / "config.toml").write_text('code_root = "~/repos"\n\n[state]\nmodel_brief = false\n')


def run(home: pathlib.Path, *args: str) -> str:
    env = {**os.environ, "HOME": str(home), "TEYLA_HOME": str(home / ".teyla"), "TEYLA_SAFE": "1", "NO_COLOR": "1",
           "PYTHONPATH": str(ROOT / "src")}
    done = subprocess.run([sys.executable, "-m", "teyla", *args], capture_output=True, text=True, env=env, cwd=str(home))
    if done.returncode != 0:
        sys.exit(f"teyla {' '.join(args)} failed ({done.returncode}): {done.stderr.strip()}")
    return done.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--keep", action="store_true", help="keep the fake HOME and print its path")
    keep = ap.parse_args().keep
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="teyla-mac-fixtures-")).resolve()
    home = tmp / "home"
    home.mkdir()
    build_home(home)
    run(home, "note", "Dark mode for the settings screen", "--product", "sample-app")
    run(home, "note", "An idea that belongs nowhere yet")
    (OUT / "start.v1.json").write_text(run(home, "start", "--json"))
    (OUT / "product.v1.json").write_text(run(home, "product", "show", "sample-app", "--json"))
    # The screenshots run the app on this state; the notes sample sits beside it, as the app expects.
    (OUT / "state.sample.v2.json").write_text(run(home, "state", "--json"))
    (OUT / "notes.v1.json").write_text(run(home, "notes", "--json"))
    empty = tmp / "empty"
    empty.mkdir()
    (empty / ".teyla").mkdir()
    (OUT / "start.empty.v1.json").write_text(run(empty, "start", "--json"))
    (OUT / "state.empty.v1.json").write_text(run(empty, "state", "--json"))
    print(f"wrote {OUT}")
    if keep:
        print(f"fake HOME: {home}\nempty HOME: {empty}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
