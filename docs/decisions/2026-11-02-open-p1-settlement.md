# Open P1s on merged PRs #300–#314: all 19 are fixed on main

Checked 2026-11-02 against `main` at `dab5aef`. `teyla attention` listed 9 merged PRs whose newest
cross-provider review still reported a P1: #300, #301, #302, #303, #304, #305, #307, #312, #314, 19 P1s
in all. Every one was a round-2 finding. Each PR was fixed in a commit after that review and merged;
POLICY §2 caps a PR at two rounds, so the fix commits never got a third review.

**Result: 19 of 19 are fixed on `main`. None is still real. None is false.**

## How this was checked

- **The finding text.** `~/.cache/review-ledger.tsv` keeps counts and a commit SHA, not text. The
  `codex-review` cache keeps the last review per diff, and none of the 31 October reviews is in it.
  The text that survives is the one-line summary of each P1 in the PR's review comment (or body for
  #314). The table quotes those summaries. The original wording is not recorded anywhere, so a fix
  is judged against the summary, not against the reviewer's full explanation.
- **No new review.** POLICY §2 forbids a third round, so `codex-review` was not rerun.
- **Fixed on main.** `tests/test_hosts.py tests/test_shield.py tests/test_shield_identity.py
  tests/test_mcp_probe.py tests/test_deps.py tests/test_leak.py tests/test_leak_guard_hook.py`: 467
  passed on `main`.
- **The test pins the fix.** For each code fix, the fix was undone on `main` (the commit's source
  hunk reverted, or the one line it added disabled) and the tests were run again. The column
  "Fails without the fix" names what failed. The tree was restored after each run.

## The 19

| PR | P1 (summary from the PR) | Fixed in | Evidence on main | Fails without the fix |
|---|---|---|---|---|
| #300 | The worker token is a token of the owner's account, so it inherits the owner's bypass rights | `361ed39` | `docs/SHIELD.md:429`, "A worker identity that is not the owner" (GitHub App token or machine account, no bypass entry) | docs only; the check that enforces it landed in #312 |
| #300 | The fail-open / fail-closed line is a classifier | `361ed39` | `docs/SHIELD.md:196`, "a fixed string match, not a classifier"; `test_a_broken_scanner_still_lets_a_plain_command_through_and_stops_a_publication` (`tests/test_leak_guard_hook.py:335`) | docs only |
| #301 | `chr()` crashes on a Unicode escape above U+10FFFF | `38630e5` | `src/teyla/hosts.py:317`; `tests/test_hosts.py:434` | `test_round_two_fixes` |
| #302 | Quoted identifiers are case-folded in the RLS replay | `2f5b02b` | `src/teyla/shield.py:572`; `tests/test_shield.py:590` | `test_round_two_fixes` |
| #303 | A token with a backslash survives JSON escaping, so the scrub misses it | `1a9f65d` | `src/teyla/mcp_probe.py:64` (`TOKEN_RE`), `:941` (refused up front); `tests/test_mcp_probe.py:771` | `test_round_two_fixes` |
| #304 | A yarn URL specifier carries userinfo into the package name | `8b0d5c9` | `src/teyla/deps.py:162`; `tests/test_deps.py:588` | `test_yarn_url_specifier_never_carries_credentials_into_the_name` |
| #305 | A wildcard in the rule field of `.leak-allow` walks round the secret-family check | `927ef09` | `scripts/leak_check.py:321`; `test_an_exception_rule_must_be_an_exact_known_name` | 5 match-all tests (an unknown-rule check stays as a second layer) |
| #305 | `.leak-allow` is read unguarded (size, symlink) | `927ef09` | `scripts/leak_check.py:159` (`read_capped`); `test_an_allow_list_over_the_cap_or_a_symlink_is_unreadable` | that test |
| #305 | The fingerprint of a finding whose line was not read is value-independent, so an exception silences it | `927ef09` | `src/teyla/leak.py:1176` (`lh and ...`); `test_an_exception_never_applies_when_the_matched_line_was_not_read` | that test |
| #305 | `--text` over the gitleaks size limit is skipped silently | `927ef09` | `src/teyla/leak.py:1101`; `test_a_text_over_the_gitleaks_limit_is_a_coverage_gap` | that test |
| #307 | ANSI-C quoting (`$'...'`) spells the program or path | `32505af` | `test_ansi_c_quoting_spells_the_program_and_the_path` (`tests/test_leak_guard_hook.py:767`), `test_an_executable_that_comes_from_an_expansion_is_refused` (`:780`) | both |
| #307 | `..` is applied before the links are followed | `32505af` | `test_dot_dot_is_applied_after_the_links_are_followed` (`:789`) | that test |
| #307 | `env -S` is not parsed like a command line | `32505af` | `test_env_split_string_is_parsed_like_a_command_line` (`:801`) | that test |
| #307 | `gh api --input -` reads its payload from stdin | `32505af` | `test_api_input_from_stdin_is_read_for_a_visibility_change` (`:814`) | that test |
| #307 | An attached `-Cdir` changes the directory | `32505af` | `test_attached_git_directory_options_change_the_directory` (`:830`) | that test |
| #307 | A `cd` inside a pipeline changes nothing after it | `32505af` | `test_a_cd_in_a_pipeline_or_the_background_changes_nothing_after_it` (`:846`) | that test |
| #307 | Substitutions reach a publication through stdin | `32505af` | `test_expansions_in_text_that_reaches_a_publication_through_stdin_are_refused` (`:860`) | that test |
| #312 | A custom repository role can carry "bypass branch protections", so a push restriction alone proves nothing for it | `3ef4512` | `src/teyla/shield.py:909` (`STANDARD_ROLES`), `:925`; `tests/test_shield_identity.py:241` | `test_a_push_restriction_proves_nothing_for_a_custom_role[release-bot-NOTE]` |
| #314 | A relative `./teyla` (a `.` on PATH) and `..` in a shebang escape the trusted-root check | `001598a` | `plugin/hooks/leak-guard.sh:146` (canonical-path block, after the shebang is read); `tests/test_leak_guard_hook.py:361` | `test_the_python_behind_teyla_is_used_when_python3_lacks_the_package` when the canonical-path block is removed. The explicit `.`/`..` rejection alone is a second layer: removing only it changes nothing, because `pwd -P` resolves the path before the root check |

Not verified: the fixes in this table were never reviewed by a second provider. Their tests pin the
behaviour in each summary; they do not prove the reviewer found everything in that area. The P2s of
the same reviews are out of scope here.

## Why attention still lists them

`teyla attention` reads `reviews.classify`. A PR is `open_p1` while its newest ledger row has a P1
and no later row has none. A logged skip outranks that (`reviews.py`, "a logged skip outranks an open
P1: it says why"), and only `review-gate` writes skips, at `gh pr merge`.

PRs #305 and #307 say in their comments that they merged with `REVIEW_SKIP`. The ledger has no skip
row for any of the nine. #306 and #294, merged the same night, have one. Why these nine have none is
not known: the merge may have run through a path the hook did not see.

So nothing can settle these nine today, except a hand-written ledger row, and a hand-edited ledger
is what this check must not rely on.

## Proposal: `teyla reviews settle`

A merged PR needs a way to say "this P1 was handled, here is how", checked by code.

```
teyla reviews settle <owner/repo>#<n> --outcome fixed|false \
    --commit <sha> --decision docs/decisions/<file>.md --reason "<one line>"
```

- Refuses unless the PR is merged, its newest review has a P1, and `--decision` exists in the
  repo's default branch and names the PR number. The evidence lives in git, in English, reviewed in
  a PR, not in `~/.cache`.
- For `fixed`, `--commit` must be an ancestor of the default branch and contain the PR's merge commit
  or a later one. For `false`, `--reason` is required.
- Appends one `skip:`-shaped row for the PR URL, written by the command, with the outcome and the
  decision path in the reason. `classify` already turns that into `skipped`, and `attention` drops
  the row.
- It does not touch `review-gate`: the gate ignores `skip` rows when it looks for a review (`review-gate`, line 85).
- Tests: refused on an open PR, on a PR without a P1, on a missing decision file; accepted row
  round-trips through `classify`.

Cost: about 80 lines plus tests and a `docs/COMMANDS.md` entry. No network call beyond `gh`, which
`reviews` already uses.

The alternative is to leave the nine on the list. That is honest but permanent: `attention` keeps an
"act" row for work that is done.

**Default if you say nothing:** build `settle` in its own PR; do not append ledger rows by hand.
