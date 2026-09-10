# Contributing

- One PR per logical unit. Merge, don't squash.
- `uv venv && uv pip install -e . pytest && .venv/bin/pytest -q` must pass.
- New adapters: implement `NAME`, `DEFAULT_ROOT`, `load()` in `src/teyla/adapters/<harness>.py`; raise `FileNotFoundError` when the store is absent; never read credentials files; add a synthetic fixture test.
- New advice rules: one function block in `advise.py` with an id, a severity, an evidence line built from numbers in the metrics dict, and one imperative action. If you cannot point at a number, it is not a rule.
- Nothing in this repo sends data anywhere. Keep it that way.
