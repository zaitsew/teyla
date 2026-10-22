# Directory listing pack

Everything the maintainer pastes into the two plugin directories, and the steps in order. The text
below matches `plugin/.claude-plugin/plugin.json` and `plugin/README.md`; when they change, change
this file in the same PR.

Sources read for this pack (checked 2026-10-23):

- Claude: <https://claude.com/docs/directory/publish.md>, <https://claude.com/docs/plugins/submit.md>,
  <https://claude.com/docs/plugins/platform-support.md>,
  <https://claude.com/docs/directory/submission-status.md>
- Claude policy: <https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy>
- OpenAI: <https://developers.openai.com/plugins/guides/submit-claude-plugin.md>

## 1. Listing text

| Field | Value |
|---|---|
| Name | Teyla |
| Plugin path in the repo | `plugin` |
| Repository | <https://github.com/zaitsew/teyla> (public, Apache-2.0) |
| Version | 0.29.0 |
| Install line | `/plugin install teyla --marketplace zaitsew/teyla` |
| Category | Developer tools (if the portal offers Productivity, use it as the second choice) |
| Keywords | routines, corrections, rules, skills, code-review, adoption |
| Documentation URL | <https://github.com/zaitsew/teyla/blob/main/plugin/README.md> |
| Support URL | <https://github.com/zaitsew/teyla/issues> |
| Privacy policy URL | <https://github.com/zaitsew/teyla/blob/main/plugin/README.md#privacy> |
| Contact email | the maintainer's address (portal field; not stored in the repo) |

**Short description** (matches `plugin.json`):

> Turn repeated work into skills and rules. Harvest skills from past sessions, record corrections, review a diff, tidy rule files. Nothing is uploaded: transcripts, prompts and rules stay on your machine.

**Long description:**

> Teyla turns repeated work into skills and rules. It reads the sessions you already ran, proposes a skill from what you did the same way every time, and records your corrections outside the repo so they never reach a commit.
>
> What you get:
> - `harvest`: turns sessions that repeatedly touched a path into a draft skill, candidate rules, a routine and a done-test. It never overwrites a skill or a rules file.
> - `review`: one review pass on the branch diff, P1 and P2 findings only, at most two rounds.
> - `tidy`: proposes edits that shorten CLAUDE.md, AGENTS.md, rule files and memory files. You approve each diff.
> - `wiki-pass`: files this session's facts into a markdown wiki, marked agent-drafted until a person confirms them.
> - `adoption-review`: reads the last 30 days of usage and turns the top three findings into concrete changes.
> - `/teyla:rule` and `/teyla:correct`: record a one-sentence rule or a scrubbed correction.
> - Optional hooks: a kill switch, a correction and intent capture, and a machine-load guard.
>
> Everything is a local file. There is no server, no account and no upload. The `harvest`, `tidy`, `wiki-pass` and `adoption-review` skills and `/teyla:correct` use the separate open-source Teyla CLI; without it each prints one install line and stops. Apache-2.0.

## 2. Data handling answers (Claude portal)

The portal asks these in the Data handling step. The answers are true to the code on the
`plugin-directory` branch; `tests/test_plugin_directory.py` pins the claims that a grep can pin.

| Question | Answer |
|---|---|
| Does it read personal data? | Yes, on the user's own machine only. It reads the prompt text and tool input each hook receives, the user's Claude Code session transcripts (`harvest`, `adoption-review`), and the user's rule and memory files. |
| Does it store personal data? | Yes, locally. Corrections and long prompts go to `~/.teyla/` (mode 0600), with tokens, keys and `password=` values replaced by `[redacted]`. Both capture hooks write only when the Teyla CLI is installed, because the scrubber lives in it. The README lists every path written. |
| Does it send data anywhere? | No, from the plugin's own files (hooks, skills, commands): they contain no network call. Three disclosed exceptions, all in the README under Network. (1) `review` runs a `codex-review` or `claude-review` script when one is on PATH, and that script sends the diff to the provider it wraps. (2) `wiki-pass` pushes a branch with `gh` or `glab` to the user's own git host. (3) On a machine where `~/.teyla/config.toml` exists, the hook can start the Teyla CLI's daily checks, one of which reads the latest release from `api.github.com` and sends no session data. `TEYLA_SAFE=1` stops the CLI's network use. |
| Retention | No automatic expiry and no copy leaves the machine. The user deletes `~/.teyla/` to remove it. `teyla uninstall --dry` lists everything. |
| Under 18 | Not directed at people under 18. It is a developer tool and collects no account or profile data. |
| Third-party processors | None operated by the maintainer. |
| Telemetry / analytics | None. |

## 3. Acknowledgements and review expectations (Claude)

The portal's Compliance step asks for a contact email and four acknowledgements. Their exact text is
not in the documentation pages above, so it is not reproduced here and is **not verified**. From the
published policy, expect them to cover: agreement to the Software Directory Terms and design
guidelines; ownership or control of every endpoint, domain or UI the plugin connects to (the plugin
connects to none); that the privacy policy link is supplied and accurate; and ongoing compliance with
policy changes. Read each one in the portal before ticking it.

What the scan and a reviewer will see, so none of it surprises the maintainer:

- The hooks live in a subfolder plugin. The docs say scripts with inline Python, command substitution,
  non-shell files or `../src` fallbacks are held for a human reviewer rather than blocked. Expect a
  hold on `plugin/hooks/context-budget.py` (a Python file) and on `$(...)` and `python3 -c` in several
  scripts. The README documents each hook, its default and what it writes.
- Hooks do not run in Claude chat on the web. Skills and commands do load there.
- A passing version is not live until the card says **Published**. **Approved** is not installable.
- Contact for a held or failed submission: the portal's **Get help**, or the directory team address on the submission-status page.

## 4. Starter prompts (at most 128 characters each)

1. `Review the diff on this branch before I merge it. P1 and P2 findings only.` (74)
2. `Harvest a draft skill from the sessions where I repeated the same steps in this repo.` (85)
3. `/teyla:rule Never edit generated files under dist/; change the source and rebuild.` (82)

`tests/test_plugin_directory.py` checks the length limit when these change.

## 5. Which skills work where

| Component | Claude Code | Cowork | Claude chat (web) | ChatGPT and Codex (skills-only upload) |
|---|---|---|---|---|
| `review`, `/teyla:rule` | yes | yes | skills and commands load | yes, no CLI needed |
| `harvest` | yes | yes | needs local transcripts, so little use | needs the CLI and local files; falls back to `grep` and `python3` |
| `tidy`, `wiki-pass`, `adoption-review`, `/teyla:correct` | yes, with the CLI | yes, with the CLI | print the install line | print the install line and stop |
| Hooks | yes | yes | ignored | not carried over |

Hooks do not run in ChatGPT, and Codex does not run prompt or agent hook handlers, so the OpenAI
archive drops `hooks/` entirely. The Claude `platform-support` page is the source for the first three
columns; the Cowork column follows its statement that hooks run there and has not been tried.

## 6. OpenAI plugin directory, skills-only

The guide accepts a Claude Code plugin as a skills-only upload when the archive root, or its single
top-level folder, holds `.claude-plugin/plugin.json` with a non-empty `description` and at least one
`skills/<name>/SKILL.md`. The portal then generates `.codex-plugin/plugin.json` itself, so this repo
carries no Codex manifest.

Build the archive:

```sh
scripts/build_openai_plugin.py                  # portable profile: review + rule  -> dist/teyla-openai-portable-0.29.0.zip
scripts/build_openai_plugin.py --profile full   # all skills and commands          -> dist/teyla-openai-full-0.29.0.zip
```

| Carries over | Does not |
|---|---|
| `skills/<name>/SKILL.md` | `hooks/` (all of it) |
| `commands/*.md`, converted to skills with a `name:` | Claude argument placeholders (`$ARGUMENTS`, `$1`), replaced with plain words; the build fails on any left over |
| `LICENSE`, a profile-specific `README.md`, `.claude-plugin/plugin.json` | `.claude-plugin/marketplace.json` |

Submit the **portable** profile first. The guide says to contact an OpenAI partner when the core value
needs local execution or arbitrary file access; `harvest` and `adoption-review` read local transcripts
and `tidy` edits local files, so they are in the `full` profile only. Upload `full` only after the
portable plugin is accepted, and say in the description that those skills need the Teyla CLI.

Steps:

1. Run the script. It checks the guide's requirements and writes a byte-for-byte reproducible zip.
2. Open <https://platform.openai.com/plugins>, choose **Create plugin**, choose **Skills only**, upload the zip.
3. Review the generated `.codex-plugin/plugin.json`. Check name, description and the three starter prompts above.
4. Test the plugin in a clean environment: `review` on a small diff, `/teyla:rule` in an empty repo.
5. Submit for review.

The account needs completed identity verification and write access in Apps Management. Both are in
the checklist below.

## 7. Morning checklist (the maintainer)

Claude directory, about 15 minutes:

1. Merge the PR for this branch after review. The directory scans the repo's default branch.
2. Check the repo is public: <https://github.com/zaitsew/teyla/settings> (it is, as of this writing).
3. Sign in at <https://claude.ai/directory/manage> and choose **Plugin bundle**.
4. **Source:** connect GitHub on claude.ai when the portal asks. If the repo were private, install the
   Claude GitHub App on `zaitsew/teyla` first; for a public repo the portal needs no app. Enter the plugin path `plugin`.
5. **Validate:** wait for the check. A failure names the file and the fix.
6. **Listing details:** paste section 1 above.
7. **Data handling:** paste section 2.
8. **Compliance:** enter the contact email, read the four acknowledgements, tick them.
9. **Review and submit:** choose the push-webhook trigger if offered (otherwise the scheduled check).
   Leave auto-publish off for the first version, so a reviewer's approval does not publish by surprise.
10. Watch the status: Scanning, In review, Approved, Published. Fix a **Needs changes** result from the plugin's page.

OpenAI directory, about 10 minutes:

1. Complete individual verification at <https://platform.openai.com/settings/organization/general>.
2. Confirm the account has write access under Apps Management in the same organization settings.
3. Run `scripts/build_openai_plugin.py`, then follow section 6 from step 2.

## 8. Versioning

This PR already sets 0.29.0 in `pyproject.toml`, `src/teyla/__init__.py`, `uv.lock` and
`plugin/.claude-plugin/plugin.json`. `scripts/release.sh` refuses a version equal to the current one,
so after the merge tag by hand (`git tag -a v0.29.0 -m 0.29.0`, push the tag, `gh release create v0.29.0`),
or run `scripts/release.sh 0.29.1` for the next change. Bump `version` whenever the plugin's behaviour
changes, so installs from the cache update.
