# Contributing

- One PR per logical unit. Merge, don't squash.
- `./check.sh` must pass (it creates `.venv` on first run). There is no CI on push: the laptop is the gate.
- New adapters: implement `NAME`, `DEFAULT_ROOT`, `load()` in `src/teyla/adapters/<harness>.py`; raise `FileNotFoundError` when the store is absent; never read credentials files; add a synthetic fixture test.
- New advice rules: one function block in `advise.py` with an id, a severity, an evidence line built from numbers in the metrics dict, and one imperative action. If you cannot point at a number, it is not a rule.
- Nothing in this repo sends data anywhere. Keep it that way.

## Keeping the public repo clean

Everything here is public and English. `scripts/leak_check.py` (run by `./check.sh` and the pre-push hook) fails on private terms, real-looking e-mail addresses and home paths, secret-shaped strings, and Cyrillic outside the files listed in `.leak-allow`.

- Enable the hook once per clone: `git config core.hooksPath .githooks`. It scans the tree and the commits being pushed (messages, author and committer names and e-mails).
- Private terms never live in the repo. Write `~/.config/teyla/private-terms.txt` (or point `$TEYLA_PRIVATE_TERMS` at a file): one case-insensitive term per line (your names, employers, products, hostnames), `#` comments, and `allow <term> in <glob>` to permit a term in matching paths, e.g. `allow yourname in commit:*:author` for your git author line. A term matches only between non-alphanumerics, so `-Users-yourname-repos-app` matches `yourname` and `app`. Without the file only the generic rules run, with a note.
- A PR body is not in the tree: check it before `gh pr create` with `python3 scripts/leak_check.py --text body.md` (`-` reads stdin).
- A genuine exception (a Russian lexicon, a fake key in a scrubber test) goes in `.leak-allow` as a path glob with a comment saying why. Never put a private name there.
