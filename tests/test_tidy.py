"""teyla tidy — every finding type, the protected regions, --apply, the weekly line and the digest
line. A tmp HOME holds the "global" files and a tmp code_root the repos; nothing here reads the
real ~/.claude, ~/.agents or ~/.teyla (TEYLA_HOME is a tmp dir from conftest)."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib

import pytest

from teyla import cli, config, digest, policy, routine_install, tidy

TODAY = dt.date(2026, 10, 8)
RU = "".join(map(chr, (0x41F, 0x440, 0x438, 0x432, 0x435, 0x442)))  # Cyrillic, built from code points so this file stays ASCII


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    code = tmp_path / "code"
    (home / ".agents").mkdir(parents=True)
    (home / ".claude").mkdir()
    code.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path / "teyla-home"))
    config.CONFIG_PATH.write_text(f'code_root = "{code}"\nops_root = "{tmp_path / "ops"}"\n')

    class E:
        pass
    e = E()
    e.home, e.code, e.tmp = home, code, tmp_path
    e.backups = tmp_path / "teyla-home" / "tidy-backup"
    return e


def put(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def repo(env, name="app"):
    r = env.code / name
    (r / ".git").mkdir(parents=True)
    return r


def scan_files(*paths, today=TODAY):
    docs, notes = tidy.load([pathlib.Path(p) for p in paths])
    assert not notes
    return tidy.scan(docs, today=today)


def rules(findings):
    return sorted((f["rule"], f["line"]) for f in findings)


def of(findings, rule):
    return [f for f in findings if f["rule"] == rule]


# --- duplicates ----------------------------------------------------------------------------------

def test_exact_duplicate_bullet_is_reported_with_the_first_line_and_is_auto_fixable(env):
    p = put(env.code / "a.md", "# T\n\n- Always run the gate before pushing a branch.\n- Something else entirely, ok.\n"
                              "- Always  run the gate  before pushing a branch.\n")
    (f,) = of(scan_files(p), "dup-line")
    # reported (whitespace-insensitive) but not auto: the text is not identical to the character
    assert f["line"] == 5 and "line 3" in f["message"] and f["auto"] is False and f["file"] == str(p)
    q = put(env.code / "b.md", "- Always run the gate before pushing a branch.\n- Another long rule, kept here.\n"
                              "- Always run the gate before pushing a branch.  \n")
    (g,) = of(scan_files(q), "dup-line")
    assert g["line"] == 3 and g["auto"] is True


def test_dup_that_is_wrapped_or_a_paragraph_is_reported_but_not_auto(env):
    p = put(env.code / "a.md", "- A long bullet that wraps onto the next line\n  and continues here.\n\n"
                              "- A long bullet that wraps onto the next line\n  and continues here.\n\n"
                              "Plain paragraph line that repeats itself exactly.\n\nPlain paragraph line that repeats itself exactly.\n")
    fs = of(scan_files(p), "dup-line")
    assert [f["line"] for f in fs] == [4, 9] and not any(f["auto"] for f in fs)


def test_short_lines_headings_and_tables_are_not_duplicates(env):
    p = put(env.code / "a.md", "## Setup\n\n- ok\n\n## Setup\n\n- ok\n\n**Structure and size, per area**\n\n**Structure and size, per area**\n\n| a | b |\n| a | b |\n---\n---\n")
    assert of(scan_files(p), "dup-line") == []


def test_near_duplicate_bullets(env):
    p = put(env.code / "a.md",
            "- Never force-push to main or to a shared branch, not even just this once.\n"
            "- Never force-push to main or to a shared branch, not even just this time.\n"
            "- Something unrelated that is long enough to be compared with the others.\n")
    (f,) = of(scan_files(p), "near-dup")
    assert f["line"] == 2 and "line 1" in f["message"] and f["auto"] is False


def test_policy_claude_cross_file_duplicates(env):
    pol = put(env.home / ".agents" / "POLICY.md", "- Merge, never squash, and never force-push anywhere.\n"
                                                  "- Keep every pull request to one logical unit of review.\n")
    cla = put(env.home / ".claude" / "CLAUDE.md", "- Merge, never squash, and never force-push anywhere.\n"
                                                  "- Keep every pull request to one logical unit of reviews.\n")
    fs = scan_files(pol, cla)
    assert [(f["rule"], f["line"], pathlib.Path(f["file"]).name) for f in fs] == [
        ("dup-line", 1, "CLAUDE.md"), ("near-dup", 2, "CLAUDE.md")]
    assert "POLICY.md:1" in fs[0]["message"] and not any(f["auto"] for f in fs)


def test_nothing_is_reported_inside_fences_or_protect_regions(env):
    block = "- Never force-push to main or to a shared branch, not even just this once.\n"
    text = (block + block.replace("once", "time") + block +
            "```\n" + block * 2 + "```\n"
            "<!-- teyla:protect -->\n" + block * 2 + "   \n\n\n\n<!-- /teyla:protect -->\n")
    p = put(env.code / "a.md", text)
    fs = scan_files(p)
    assert {f["line"] for f in fs if f["rule"] in ("dup-line", "near-dup")} == {2, 3}
    assert [f for f in fs if f["line"] > 3] == []


# --- references and memory ------------------------------------------------------------------------

def test_broken_import_and_link_and_code_span_exceptions(env):
    r = repo(env)
    put(r / "docs" / "real.md", "x\n")
    p = put(r / "CLAUDE.md", "@docs/real.md\n@docs/gone.md\nSee [real](docs/real.md) and [gone](docs/gone.md#top) and "
                             "[web](https://example.com/x) and [anchor](#top).\nIn code: `@docs/nope.md` and `[x](nope.md)`.\n"
                             "Mail me@example.com or use @property or @scope/pkg or @in.example.ai here.\n@~/does/not/exist.md\n")
    fs = scan_files(p)
    assert rules(fs) == [("broken-import", 2), ("broken-import", 6), ("broken-link", 3)]
    assert "docs/gone.md" in of(fs, "broken-link")[0]["message"]


def test_links_inside_a_fence_are_not_checked(env):
    p = put(env.code / "a.md", "```\n@missing/file.md\n[x](nope.md)\n```\n")
    assert scan_files(p) == []


def _memdir(env, key="-Users-x-repos-app"):
    return env.home / ".claude" / "projects" / key / "memory"


def test_memory_index_unlisted_frontmatter_and_memory_links(env):
    m = _memdir(env)
    put(m / "MEMORY.md", "- [Proxy](proxy.md) — the proxy setup\n- [Gone](gone.md) — deleted long ago\n")
    put(m / "proxy.md", "---\nname: proxy\ndescription: d\ntype: project\n---\nSee [[sprint]] and [[nope]] and [[proxy]].\n")
    put(m / "sprint.md", "---\nname: sprint\ndescription: s\n---\nbody\n")
    put(m / "orphan.md", "no frontmatter at all\n")
    docs, _ = tidy.load(sorted(m.glob("*.md")))
    fs = tidy.scan(docs, today=TODAY)
    by = {(pathlib.Path(f["file"]).name, f["rule"]): f for f in fs}
    assert by[("MEMORY.md", "memory-index")]["line"] == 2 and "gone.md" in by[("MEMORY.md", "memory-index")]["message"]
    unlisted = sorted(f["message"].split()[0] for f in fs if f["rule"] == "memory-unlisted")
    assert unlisted == ["orphan.md", "sprint.md"]
    assert "type" in by[("sprint.md", "memory-frontmatter")]["message"]
    assert "no frontmatter" in by[("orphan.md", "memory-frontmatter")]["message"]
    (ml,) = of(fs, "broken-memory-link")
    assert ml["line"] == 6 and "nope" in ml["message"]


def test_memory_links_outside_a_memory_dir_are_not_judged(env):
    p = put(env.code / "wiki.md", "A wiki page about [[anything]].\n")
    assert scan_files(p) == []


# --- size, whitespace, language, stale dates -------------------------------------------------------

def test_size_budget_follows_config_and_long_index_lines(env):
    p = put(env.code / "big.md", "x" * 3000 + "\n")
    assert of(scan_files(p), "size") == []
    config.CONFIG_PATH.write_text(config.CONFIG_PATH.read_text() + "[tidy]\nmax_kb = 2\n")
    (f,) = of(scan_files(p), "size")
    assert "budget" in f["message"] and "2 KB" in f["message"]
    m = _memdir(env)
    put(m / "MEMORY.md", "- [A](a.md) — " + "y" * 220 + "\n")
    put(m / "a.md", "---\nname: a\ndescription: d\ntype: user\n---\n")
    (g,) = [f for f in scan_files(m / "MEMORY.md") if f["rule"] == "size"]
    assert g["line"] == 1 and "index line" in g["message"]


def test_whitespace_findings_and_the_hard_break_exception(env):
    p = put(env.code / "a.md", "clean line\ntrailing   \n\nhard break  \nnext line\nhard break three   \nnext\n\n\n\n\nafter blanks\n- item\n\t- tabbed child\n"
                              "last line with trailing tab\t\n")
    fs = scan_files(p)
    # 2 or more trailing spaces before a following text line is a markdown hard break: kept
    assert rules(fs) == [("blank-run", 8), ("tab-list", 14), ("trailing-ws", 2), ("trailing-ws", 15)]
    assert all(f["auto"] for f in fs)


def test_non_english_is_reported_only_for_files_inside_a_repo(env):
    r = repo(env)
    p = put(r / "CLAUDE.md", f"English line\n{RU}\n{RU}\nmore English\n{RU}\n")
    g = put(env.home / ".claude" / "CLAUDE.md", f"{RU}\n")
    fs = scan_files(p, g)
    assert [(f["line"], pathlib.Path(f["file"]).parent.name) for f in fs if f["rule"] == "non-english"] == [(2, "app"), (5, "app")]
    assert "lines 2-3" in of(fs, "non-english")[0]["message"]


def test_stale_dates_need_an_old_date_and_a_temporary_word(env):
    p = put(env.code / "a.md",
            "- Use the old proxy until 2026-03-01 when the migration lands.\n"       # stale
            "- Use the old proxy until 2026-09-20 when the migration lands.\n"       # recent
            "- (2026-02-01: it broke once on a Friday, so we always run the gate.)\n"  # old, no keyword
            "- TODO from 2025-12-31: split this file.\n"                              # stale
            "- Until further notice, nothing changes (no date here at all).\n")
    assert [f["line"] for f in of(scan_files(p), "stale-date")] == [1, 4]
    config.CONFIG_PATH.write_text(config.CONFIG_PATH.read_text() + "[tidy]\nstale_days = 10\n")
    assert [f["line"] for f in of(scan_files(p), "stale-date")] == [1, 2, 4]


# --- --apply ---------------------------------------------------------------------------------------

PROTECTED_FENCE = ("- Merge without asking ONLY in a repo on this list.\n\n"
                   "  ```\n  MERGE-APPROVED REPOS\n    org/one   \n\t\n    org/one   \n\n\n\n    org/two\n  ```\n")
PROTECTED_REGION = "<!-- teyla:protect -->\nkeep   \n\n\n\n\tas is\n- A twice repeated bullet inside the protected region.\n- A twice repeated bullet inside the protected region.\n<!-- /teyla:protect -->\n"


def _dirty():
    return ("# Rules   \n\n" + PROTECTED_FENCE + "\n- First rule, stated once and clearly here.   \n\n\n\n\n"
            "- First rule, stated once and clearly here.\n- Second rule, with a tab-indented child:\n\t- child\n\n" + PROTECTED_REGION +
            "tail  \n")


def test_apply_fixes_the_mechanical_parts_and_keeps_protected_blocks_byte_identical(env):
    r = repo(env)
    p = put(r / "CLAUDE.md", _dirty())
    before = p.read_bytes()
    assert tidy.run([str(p)])["summary"]["auto_fixable"] > 0
    assert p.read_bytes() == before  # read-only by default
    res = tidy.run([str(p)], apply_fixes=True, today=TODAY)
    assert res["refused"] == [] and len(res["applied"]) == 1
    after = p.read_text()
    assert PROTECTED_FENCE in after and PROTECTED_REGION in after  # byte-identical blocks
    assert after.startswith("# Rules\n\n")
    assert "stated once and clearly here.   " not in after and after.count("First rule, stated once") == 1
    assert "\n    - child\n" in after and "\t- child" not in after
    assert "tail\n" in after and "tail  \n" not in after
    # the rest is untouched and a second run finds nothing mechanical
    again = tidy.run([str(p)], apply_fixes=True)
    assert again["applied"] == [] and again["summary"]["auto_fixable"] == 0
    # backup holds the original bytes, named for the flattened path
    (backup,) = [pathlib.Path(res["applied"][0]["backup"])]
    assert backup.read_bytes() == before and backup.parent.parent == env.backups
    assert backup.name == str(p.absolute()).lstrip("/").replace("/", "__")
    assert oct(backup.stat().st_mode & 0o777) == "0o600"


def test_apply_changes_only_what_it_reports_as_fixable(env):
    r = repo(env)
    text = "- Keep this near duplicate bullet, which is long enough to compare, one.\n- Keep this near duplicate bullet, which is long enough to compare, two.\n"
    p = put(r / "AGENTS.md", text + f"{RU}\n[x](nope.md)\n")
    res = tidy.run([str(p)], apply_fixes=True, today=TODAY)
    assert res["applied"] == [] and p.read_text() == text + f"{RU}\n[x](nope.md)\n"
    assert {f["rule"] for f in res["findings"]} == {"near-dup", "non-english", "broken-link"}


def test_apply_does_not_delete_a_duplicate_bullet_that_has_children(env):
    p = put(env.code / "a.md", "- A parent bullet that is stated twice in this file.\n- A parent bullet that is stated twice in this file.\n  - nested detail\n")
    res = tidy.run([str(p)], apply_fixes=True)
    assert res["applied"] == [] and [f["auto"] for f in res["findings"]] == [False]


def test_apply_removes_the_blank_a_deleted_bullet_leaves_behind(env):
    p = put(env.code / "a.md", "- First rule that stays put, long enough to count.\n\n- Duplicated rule that is repeated below here.\n\n"
                              "- Duplicated rule that is repeated below here.\n\n- Last rule.\n")
    tidy.run([str(p)], apply_fixes=True)
    assert p.read_text() == ("- First rule that stays put, long enough to count.\n\n- Duplicated rule that is repeated below here.\n\n"
                             "- Last rule.\n")


def test_apply_keeps_crlf_endings(env):
    p = put(env.code / "a.md", "line one   \r\n\r\nline two\r\n")
    tidy.run([str(p)], apply_fixes=True)
    assert p.read_bytes() == b"line one\r\n\r\nline two\r\n"


def test_apply_refuses_a_symlink_and_writes_nothing_through_it(env):
    real = put(env.tmp / "real" / "CLAUDE.md", "dirty   \n")
    r = repo(env)
    link = r / "CLAUDE.md"
    link.symlink_to(real)
    res = tidy.run([str(link)], apply_fixes=True)
    assert [x["reason"][:12] for x in res["refused"]] == ["is a symlink"]
    assert real.read_text() == "dirty   \n" and link.is_symlink() and not env.backups.exists()
    assert cli.main(["tidy", str(link), "--apply"]) == 1
    # the target itself, given directly, is tidied
    assert tidy.run([str(real)], apply_fixes=True)["refused"] == [] and real.read_text() == "dirty\n"


def test_apply_refuses_files_policy_sync_generated(env):
    for name, head in (("a.md", policy.AGENTS_MARKER + " from ~/.agents/POLICY.md -->"),
                       ("b.md", "---\nname: x\n---\n\n<!-- generated by `teyla harness sync` (teyla 0.1) from x -->")):
        p = put(env.code / name, head + "\ndirty   \n")
        before = p.read_bytes()
        res = tidy.run([str(p)], apply_fixes=True)
        assert len(res["refused"]) == 1 and "generated" in res["refused"][0]["reason"]
        assert p.read_bytes() == before
    assert not env.backups.exists()


def test_unclosed_fence_protects_to_the_end(env):
    p = put(env.code / "a.md", "text   \n\n```\nunclosed   \n\n\n\n\nstill code\n")
    tidy.run([str(p)], apply_fixes=True)
    assert p.read_text() == "text\n\n```\nunclosed   \n\n\n\n\nstill code\n"


def test_generated_regions_are_protected_too(env):
    body = "<!-- teyla:cloud:start — generated by `teyla cloud prep` -->\nline   \n\n\n\n<!-- teyla:cloud:end -->\n"
    p = put(env.code / "AGENTS.md", body + "mine   \n")
    tidy.run([str(p)], apply_fixes=True)
    assert p.read_text() == body + "mine\n"


# --- targets and CLI --------------------------------------------------------------------------------

def test_default_targets_cover_global_files_memory_and_repos_once(env):
    pol = put(env.home / ".agents" / "POLICY.md", "x\n")
    cla = put(env.home / ".claude" / "CLAUDE.md", "x\n")
    mem = put(_memdir(env) / "MEMORY.md", "x\n")
    r = repo(env)
    put(r / "CLAUDE.md", "x\n")
    (r / "AGENTS.md").symlink_to(r / "CLAUDE.md")
    put(r / ".claude" / "rules" / "one.md", "x\n")
    put(r / "README.md", "not a governance file\n")
    not_repo = env.code / "plain"
    put(not_repo / "CLAUDE.md", "no .git here\n")
    got = {str(p) for p in tidy.default_targets()}
    assert got == {str(pol), str(cla), str(mem), str(r / "CLAUDE.md"), str(r / ".claude" / "rules" / "one.md")}


def test_cli_json_quiet_and_errors(env, capsys):
    r = repo(env)
    put(r / "CLAUDE.md", "dirty   \n")
    assert cli.main(["tidy", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"] == {"findings": 1, "files": 1, "auto_fixable": 1} and out["findings"][0]["rule"] == "trailing-ws"
    assert cli.main(["tidy", str(r / "CLAUDE.md"), "--apply", "--quiet"]) == 0
    assert "applied to" in capsys.readouterr().out
    assert cli.main(["tidy", "--quiet"]) == 0 and capsys.readouterr().out == ""
    assert cli.main(["tidy"]) == 0 and "clean (1 file(s) scanned)" in capsys.readouterr().out
    assert cli.main(["tidy", str(env.tmp / "missing.md")]) == 2
    assert "no such file" in capsys.readouterr().err


def test_text_report_names_file_line_rule_and_fix(env, capsys):
    p = put(env.code / "CLAUDE.md", "ok\n- a   \n")
    assert cli.main(["tidy", str(p)]) == 0
    out = capsys.readouterr().out
    assert "# teyla tidy: 1 finding(s) in 1 file(s)" in out and f"## {p}" in out
    assert "- line 2 [trailing-ws] trailing whitespace → strip it (auto-fixable)" in out and "teyla tidy --apply" in out


# --- the weekly routine and the digest ---------------------------------------------------------------

def _wrapper(watch_line="\"$TEYLA\" models watch --refresh"):
    return routine_install.WRAPPER_TEMPLATE.format(teyla_bin="/x/teyla", env_sh="", stamp="/s.last", label="l",
                                                   runs_root=routine_install._runs_root(), models_watch_line=watch_line)


def test_weekly_wrapper_runs_tidy_report_only_and_an_older_wrapper_is_stale(env, monkeypatch):
    text = _wrapper()
    assert '"$TEYLA" tidy --quiet > "$OUT_DIR/tidy.md" 2>&1' in text and "--apply" not in text
    w = env.tmp / "weekly.sh"
    monkeypatch.setattr(routine_install, "WRAPPER_PATH", w)
    w.write_text(text)
    assert not routine_install._wrapper_stale(w, "/x/teyla")
    w.write_text(text.replace('"$TEYLA" tidy --quiet > "$OUT_DIR/tidy.md" 2>&1\n', ""))
    assert routine_install._wrapper_stale(w, "/x/teyla")  # written before `teyla tidy`


def test_digest_gets_one_line_only_when_there_are_findings(env):
    assert tidy.digest_candidates() == []
    r = repo(env)
    put(r / "CLAUDE.md", "dirty   \n")
    put(r / "AGENTS.md", "- also dirty   \n\n- and   \n")
    put(env.home / ".claude" / "CLAUDE.md", "fine\n")
    (c,) = tidy.digest_candidates()
    assert c["text"] == "md tidy: 3 finding(s) in 2 file(s)" and c["step"] == "teyla tidy" and c["cmd"] is True
    lines, _ = digest.build([], [], [], {}, extra=[c])
    assert any("md tidy: 3 finding(s) in 2 file(s)" in line and "`teyla tidy`" in line for line in lines)
    lines = digest.write([], [], [], today=TODAY, notify_now=False)
    assert any("md tidy: 3 finding(s) in 2 file(s)" in line for line in lines)


# --- review round: races, temp files, whole-item duplicates, code spans, quotes, links, hard breaks ----

def _edit_during_apply(monkeypatch, target, new_bytes, touch_only=False):
    """Simulate an editor saving `target` in the window after tidy read it: the first chmod of
    tidy's temp file (made after the read, before the replace, in any version) saves the file."""
    real = os.chmod
    state = {"done": False}

    def chmod(p, mode, *a, **k):
        if ".tidy-tmp" in os.fspath(p) and not state["done"]:
            state["done"] = True
            if touch_only:
                st = os.stat(target)
                os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
            else:
                pathlib.Path(target).write_bytes(new_bytes)
        return real(p, mode, *a, **k)
    monkeypatch.setattr(os, "chmod", chmod)
    return state


def test_apply_refuses_when_the_file_is_saved_after_it_was_read(env, monkeypatch):
    r = repo(env)
    p = put(r / "CLAUDE.md", "dirty   \n\nmine\n")
    editor = b"dirty   \n\nmine, plus a line written a moment ago\n"
    state = _edit_during_apply(monkeypatch, p, editor)
    res = tidy.run([str(p)], apply_fixes=True)
    assert state["done"] and p.read_bytes() == editor  # the editor's save survives
    assert res["applied"] == [] and "changed while tidy ran" in res["refused"][0]["reason"]
    assert not list(r.glob(".*tidy-tmp")) and not list(env.backups.rglob("*CLAUDE.md*"))  # no temp, no stray backup


def test_apply_refuses_when_only_the_mtime_changed(env, monkeypatch):
    p = put(env.code / "a.md", "dirty   \n\nmine\n")
    state = _edit_during_apply(monkeypatch, p, b"", touch_only=True)
    res = tidy.run([str(p)], apply_fixes=True)
    assert state["done"] and p.read_bytes() == b"dirty   \n\nmine\n"
    assert res["applied"] == [] and "changed while tidy ran" in res["refused"][0]["reason"]


def test_apply_refuses_a_file_changed_between_scan_and_apply_and_backs_up_what_it_replaces(env):
    p = put(env.code / "a.md", "dirty   \n\nmine\n")
    docs, _ = tidy.load([p])
    p.write_bytes(b"edited   \n\nafter the scan\n")
    applied, refused = tidy.apply(docs)
    assert applied == [] and len(refused) == 1 and p.read_bytes() == b"edited   \n\nafter the scan\n"
    docs, _ = tidy.load([p])
    applied, _ = tidy.apply(docs)
    assert pathlib.Path(applied[0]["backup"]).read_bytes() == b"edited   \n\nafter the scan\n"


def test_apply_never_opens_a_planted_temp_name(env):
    victim = put(env.tmp / "victim.txt", "precious content\n")
    p = put(env.code / "CLAUDE.md", "dirty   \n")
    os.link(victim, env.code / ".CLAUDE.md.tidy-tmp")  # the name an older version used
    res = tidy.run([str(p)], apply_fixes=True)
    assert res["refused"] == [] and p.read_text() == "dirty\n"
    assert victim.read_text() == "precious content\n"
    assert (env.code / ".CLAUDE.md.tidy-tmp").read_text() == "precious content\n"
    assert not [x for x in env.code.iterdir() if x.name.endswith(".tidy-tmp") and x.name != ".CLAUDE.md.tidy-tmp"]


def test_apply_keeps_the_file_mode(env):
    p = put(env.code / "a.md", "dirty   \n")
    os.chmod(p, 0o640)
    tidy.run([str(p)], apply_fixes=True)
    assert p.read_text() == "dirty\n" and (p.stat().st_mode & 0o777) == 0o640


def test_a_duplicate_is_not_deleted_when_the_first_copy_has_a_continuation(env):
    text = ("- Never touch the generated copies of a file.\n  Except the docs folder, which is hand written.\n\n"
            "- Never touch the generated copies of a file.\n")
    p = put(env.code / "a.md", text)
    res = tidy.run([str(p)], apply_fixes=True)
    assert res["applied"] == [] and p.read_text() == text
    assert [f["auto"] for f in res["findings"] if f["rule"] == "dup-line"] == [False]
    # a nested child under the first copy counts as part of it too
    q = put(env.code / "b.md", "- Always run the full gate first.\n  - except for docs\n\n- Always run the full gate first.\n")
    assert tidy.run([str(q)], apply_fixes=True)["applied"] == []


def test_code_span_spacing_is_part_of_the_item(env):
    text = "- Print it with `printf 'a  b'` exactly.\n- Print it with `printf 'a b'` exactly.\n"
    p = put(env.code / "a.md", text)
    res = tidy.run([str(p)], apply_fixes=True)
    assert of(res["findings"], "dup-line") == [] and p.read_text() == text
    # outside a span, spacing still does not matter for the report, but only an identical line is deleted
    q = put(env.code / "b.md", "- Print it with `x` exactly.\n- Print  it with `x` exactly.\n")
    (f,) = of(scan_files(q), "dup-line")
    assert f["auto"] is False


def test_a_fence_inside_a_blockquote_is_protected(env):
    text = "> note   \n>\n> ```\n> kept   \n>\n>\n>\n>\n> - A repeated bullet inside the quoted fence.\n> - A repeated bullet inside the quoted fence.\n> ```\n\ntail   \n"
    p = put(env.code / "a.md", text)
    res = tidy.run([str(p)], apply_fixes=True)
    assert res["findings"] == []
    assert p.read_text() == text.replace("tail   \n", "tail\n")  # only the line outside the quote moved
    assert "> note   \n" in p.read_text()  # followed by a quoted line: a hard break, kept


def test_apply_refuses_a_file_below_a_symlinked_directory(env):
    r = repo(env)
    shared = env.tmp / "shared-rules"
    put(shared / "one.md", "dirty   \n")
    (r / ".claude").mkdir()
    (r / ".claude" / "rules").symlink_to(shared)
    res = tidy.run([str(r)], apply_fixes=True)
    assert [x["reason"][:21] for x in res["refused"]] == ["sits below a symlinke"]
    assert (shared / "one.md").read_text() == "dirty   \n" and not env.backups.exists()
    # the real directory, given directly (no repository around it), is tidied
    assert tidy.run([str(shared / "one.md")], apply_fixes=True)["refused"] == []
    assert (shared / "one.md").read_text() == "dirty\n"


def test_two_or_more_trailing_spaces_before_text_are_a_hard_break_and_are_kept(env):
    text = "first line   \nsecond line  \nthird\n\nlast   \n"
    p = put(env.code / "a.md", text)
    res = tidy.run([str(p)], apply_fixes=True)
    assert p.read_text() == "first line   \nsecond line  \nthird\n\nlast\n"
    assert [f["line"] for f in res["findings"]] == []


# --- round two: fence closers, symlinked checkouts ---------------------------------------------------

def test_a_quote_marker_line_inside_a_plain_fence_does_not_close_it(env):
    dup = "- A repeated bullet that is only an example inside the code.\n"
    text = f"intro   \n\n```md\n> ```\n{dup}{dup}```\n\ntail   \n"
    p = put(env.code / "a.md", text)
    res = tidy.run([str(p)], apply_fixes=True)
    assert p.read_text() == text.replace("intro   ", "intro").replace("tail   ", "tail")  # the fence is byte-identical
    assert res["findings"] == [] and res["refused"] == []


def test_a_quoted_fence_closes_only_at_its_own_quote_depth(env):
    text = "> ```\n> kept   \n> > ```\n> still kept   \n> ```\n\nout   \n"
    p = put(env.code / "a.md", text)
    tidy.run([str(p)], apply_fixes=True)
    assert p.read_text() == text.replace("out   ", "out")
    # a plain fence is not closed by a shorter or different fence either
    q = put(env.code / "b.md", "````\n```\nkept   \n~~~\nkept   \n````\nout   \n")
    tidy.run([str(q)], apply_fixes=True)
    assert q.read_text() == "````\n```\nkept   \n~~~\nkept   \n````\nout\n"


def test_a_quoted_fence_ends_with_its_blockquote(env):
    # An unclosed quoted fence must not swallow the plain fence after it and close at its `> ``` line.
    dup = "- A repeated bullet that is only an example inside the code.\n"
    text = f"> ```\n> quoted code\n\n```md\n> ```\n{dup}{dup}```\n\ntail   \n"
    p = put(env.code / "a.md", text)
    res = tidy.run([str(p)], apply_fixes=True)
    assert p.read_text() == text.replace("tail   ", "tail")
    assert res["refused"] == [] and not any("duplicate" in str(f).lower() for f in res["findings"])


def test_apply_refuses_a_dangling_dot_git_link_and_one_at_home(env):
    r = env.code / "dangling-git"
    r.mkdir()
    (r / ".git").symlink_to(env.tmp / "gone")
    p = put(r / "CLAUDE.md", "dirty   \n")
    assert len(tidy.run([str(p)], apply_fixes=True)["refused"]) == 1 and p.read_text() == "dirty   \n"
    home = pathlib.Path(os.environ["HOME"])
    (home / ".git").symlink_to(env.tmp)
    q = put(home / "CLAUDE.md", "dirty   \n")
    assert len(tidy.run([str(q)], apply_fixes=True)["refused"]) == 1 and q.read_text() == "dirty   \n"


def test_apply_refuses_a_directory_that_is_another_checkout_reached_by_a_link(env):
    r = repo(env)
    other = env.tmp / "other-checkout"
    (other / ".git").mkdir(parents=True)
    put(other / "CLAUDE.md", "dirty   \n")
    (r / "vendor").symlink_to(other)
    res = tidy.run([str(r / "vendor" / "CLAUDE.md")], apply_fixes=True)
    assert [x["reason"][:21] for x in res["refused"]] == ["sits below a symlinke"]
    assert (other / "CLAUDE.md").read_text() == "dirty   \n" and not env.backups.exists()
    # the checkout itself, given by its real path, is tidied
    assert tidy.run([str(other / "CLAUDE.md")], apply_fixes=True)["refused"] == []
    assert (other / "CLAUDE.md").read_text() == "dirty\n"


def test_apply_refuses_a_repository_whose_dot_git_is_a_link(env):
    r = env.code / "linked-git"
    r.mkdir()
    (r / ".git").symlink_to(env.tmp)  # any directory: it only has to exist
    p = put(r / "CLAUDE.md", "dirty   \n")
    res = tidy.run([str(p)], apply_fixes=True)
    assert len(res["refused"]) == 1 and p.read_text() == "dirty   \n"
