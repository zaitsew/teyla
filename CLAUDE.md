If you were asked to install or set up Teyla for a person, stop reading this file and follow `AGENTS.md`.

# Working on Teyla

Contributor rules live in `CONTRIBUTING.md`. The short version:

- `./check.sh` is the gate (leak check, then pytest). There is no CI on push.
- One PR per logical unit. Merge, never squash. Never force-push.
- Everything in the repo is English. Fixtures are generic: no real names, e-mails, home paths or Cyrillic.
- A new call that leaves the machine needs a row in `docs/PRIVACY.md` and an entry in `tests/test_privacy_calls.py`.
- `AGENTS.md` is the install guide for an agent. Change it when a command or flag it names changes;
  `tests/test_agents_md.py` parses every `teyla ...` line in it.
