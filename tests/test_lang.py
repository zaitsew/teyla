"""teyla lang — tmp git repos under a tmp code_root and a tmp HOME. Non-Latin text is built from
\\u escapes: the repo's own leak check flags literal Cyrillic outside allow-listed files."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess

import pytest

from teyla import cli, config, digest, lang, routine_install

RU = "\u041f\u0440\u0438\u0432\u0435\u0442 \u043c\u0438\u0440"  # two Cyrillic words
RU_BYTES = RU.encode("utf-8")
ZH = "\u4f60\u597d\u4e16\u754c"
GR = "\u03b1\u03b2\u03b3\u03b4\u03b5"
HE = "\u05e9\u05dc\u05d5\u05dd"
AR = "\u0645\u0631\u062d\u0628\u0627"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@example.com",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


def make_repo(root: pathlib.Path, name: str, files: dict[str, str | bytes], message: str = "initial") -> pathlib.Path:
    repo = root / name
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    write(repo, files)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return repo


def write(repo: pathlib.Path, files: dict[str, str | bytes]):
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    code, ops = tmp_path / "code", tmp_path / "ops"
    code.mkdir()
    ops.mkdir()
    (home / ".teyla" / "config.toml").write_text(f'code_root = "{code}"\nops_root = "{ops}"\n')

    class E:
        pass
    e = E()
    e.home, e.code = home, code
    return e


def kinds(rep: dict) -> dict[str, str]:
    return {f["path"]: f["kind"] for f in rep["files"]}


def run(argv, capsys):
    code = cli.main(argv)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


# --- classification ----------------------------------------------------------------------------

def test_kinds_doc_comment_string_fixture_other(env):
    repo = make_repo(env.code, "app", {
        "README.md": f"# Title\n\n{RU}\n",
        "docs/guide.rst": f"Guide\n\n{RU}\n",
        "src/main.py": f'x = 1  # {RU}\nlabel = "{RU}"\n',
        "src/util.swift": f"// {RU}\nlet a = 1\n",
        "src/style.css": f"/* {RU} */\n",
        "tests/test_main.py": f'EXPECTED = "{RU}"\n',
        "notes.txt": f"{RU}\n",
        "page.html": f"<!-- {ZH} -->\n<p>{ZH}</p>\n",
    })
    rep = lang.scan_repo(repo)
    k = kinds(rep)
    assert k["README.md"] == "doc" and k["docs/guide.rst"] == "doc"
    assert rep["files"][0]["lines"] >= 1 and "src/main.py" in k
    by_line = {(f["path"], h["line"]): h["kind"] for f in rep["files"] for h in f["hits"]}
    assert by_line[("src/main.py", 1)] == "comment"
    assert by_line[("src/main.py", 2)] == "string"
    assert by_line[("src/util.swift", 1)] == "comment"
    assert by_line[("src/style.css", 1)] == "comment"
    assert by_line[("tests/test_main.py", 1)] == "fixture"
    assert k["notes.txt"] == "other"
    assert by_line[("page.html", 1)] == "comment" and by_line[("page.html", 2)] == "other"
    assert rep["counts"]["doc"] == dict(files=2, lines=2)
    assert rep["counts"]["comment"]["files"] == 4  # main.py, util.swift, style.css, page.html


def test_block_comments_docstrings_and_a_comment_in_a_test(env):
    repo = make_repo(env.code, "app", {
        "a.ts": f"/*\n * {RU}\n */\nconst s = `{RU}`;\n",
        "b.py": f'"""\n{RU}\n"""\nQUERY = """\n{RU}\n"""\n',
        "tests/test_c.py": f"# {RU}\nX = '{RU}'\n",
        "sql/q.sql": f"-- {RU}\nSELECT 1;\n",
    })
    by_line = {(f["path"], h["line"]): h["kind"] for f in lang.scan_repo(repo)["files"] for h in f["hits"]}
    assert by_line[("a.ts", 2)] == "comment" and by_line[("a.ts", 4)] == "string"
    assert by_line[("b.py", 2)] == "comment"      # a docstring
    assert by_line[("b.py", 5)] == "string"       # a multi-line string constant
    assert by_line[("tests/test_c.py", 1)] == "comment" and by_line[("tests/test_c.py", 2)] == "fixture"
    assert by_line[("sql/q.sql", 1)] == "comment"


def test_a_comment_token_inside_a_string_does_not_make_a_comment(env):
    repo = make_repo(env.code, "app", {"u.py": f'url = "http://x/#{RU}"\nok = "{RU}"  # fine\n'})
    (f,) = lang.scan_repo(repo)["files"]
    assert {h["line"]: h["kind"] for h in f["hits"]} == {1: "string", 2: "string"}


def test_line_with_a_string_and_a_comment_counts_both(env):
    repo = make_repo(env.code, "app", {"m.py": f'x = "{RU}"  # {RU}\n'})
    (f,) = lang.scan_repo(repo)["files"]
    assert sorted(h["kind"] for h in f["hits"]) == ["comment", "string"] and f["lines"] == 1


def test_every_non_latin_script_is_found_and_latin_text_is_not(env):
    repo = make_repo(env.code, "app", {
        "a.md": f"{ZH}\n", "b.md": f"{GR}\n", "c.md": f"{HE}\n", "d.md": f"{AR}\n", "e.md": f"{RU}\n",
        "latin.md": "Hola, ¿cómo estás? Straße, naïve café, ça va.\n",
        "math.md": "latency 5 \u03bcs, \u0394t = 2, \u03c0 ≈ 3.14, \u03bb\n",
    })
    rep = lang.scan_repo(repo)
    scripts = {f["path"]: f["scripts"] for f in rep["files"]}
    assert scripts == {"a.md": ["cjk"], "b.md": ["greek"], "c.md": ["hebrew"], "d.md": ["arabic"], "e.md": ["cyrillic"]}


def test_one_line_with_two_scripts_reports_both(env, capsys):
    repo = make_repo(env.code, "app", {"mix.md": f"{RU} / {ZH}\n", "plain.md": f"{ZH}\n"})
    rep = lang.scan_repo(repo)
    mix = next(f for f in rep["files"] if f["path"] == "mix.md")
    assert mix["scripts"] == ["cjk", "cyrillic"]
    (hit,) = mix["hits"]
    assert sorted(hit["scripts"]) == ["cjk", "cyrillic"] and hit["script"] in hit["scripts"]
    out = json.loads(run(["lang", "app", "--json"], capsys)[1])
    assert next(f for f in out["repos"][0]["files"] if f["path"] == "mix.md")["scripts"] == ["cjk", "cyrillic"]


def test_template_literals_keep_their_string_state_across_lines(env):
    body = ("const s = `\n" f"{RU}\n" f" * {RU}\n" "esc \\` still inside ${x}\n" f"{RU}\n" "`;\n"
            f"// {RU}\n" f"const t = '{RU}';\n")
    repo = make_repo(env.code, "app", {"t.ts": body})
    (f,) = lang.scan_repo(repo)["files"]
    assert {h["line"]: h["kind"] for h in f["hits"]} == {2: "string", 3: "string", 5: "string", 7: "comment", 8: "string"}


# --- exceptions --------------------------------------------------------------------------------

def test_localization_paths_are_exempt_by_default(env):
    files = {p: f"{RU}\n" for p in (
        "App/ru.lproj/Localizable.strings", "App/Strings.xcstrings", "web/locales/ru.json", "i18n/ru.ts",
        "src/l10n/ru.dart", "translations/ru.yaml", "po/ru.po", "x/y/Localizable.stringsdict",
        "app/messages/ru.json", "a.strings")}
    files["src/real.py"] = f"# {RU}\n"
    repo = make_repo(env.code, "app", files)
    rep = lang.scan_repo(repo)
    assert [f["path"] for f in rep["files"]] == ["src/real.py"] and rep["exempt"] == 10


def test_android_resource_qualifiers_and_string_catalogs_are_exempt_by_default(env):
    xml = f'<resources><string name="title">{RU}</string></resources>\n'
    files = {p: xml for p in (
        "android/app/src/main/res/values-ru/strings.xml", "app/src/main/res/values-pt-rBR/plurals.xml",
        "res/values-zh/arrays.xml", "mobile/android/src/main/res/values-ru-rRU/strings.xml")}
    files.update({"Tools/strings/access.json": f'{{"a": "{RU}"}}\n', "tools/strings/deep.json": f'{{"a": "{RU}"}}\n'})
    # not localization resources: still findings
    files.update({"app/src/main/res/values-ru/notes.xml": xml, "app/src/main/res/layout/main.xml": xml,
                  "src/strings/helper.py": f"# {RU}\n", "values-ru/strings.xml": xml})
    repo = make_repo(env.code, "app", files)
    rep = lang.scan_repo(repo)
    assert sorted(f["path"] for f in rep["files"]) == [
        "app/src/main/res/layout/main.xml", "app/src/main/res/values-ru/notes.xml", "src/strings/helper.py",
        "values-ru/strings.xml"]
    assert rep["exempt"] == 6


def test_help_documents_the_per_repo_exemption_list(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["lang", "--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert ".teyla/lang-allow" in out and "lang.allow" in out and "res/values-*" in out


def test_repo_allow_file_and_config_allow(env):
    repo = make_repo(env.code, "app", {
        ".teyla/lang-allow": "# the lexicon is language data\nsrc/lexicon.py   # trailing note\ndata/ru/**\n",
        "src/lexicon.py": f'WORDS = ["{RU}"]\n',
        "data/ru/a.txt": f"{RU}\n",
        "data/en/a.txt": f"{RU}\n",
        "notes/archive.md": f"{RU}\n",
        "src/other.py": f"# {RU}\n",
    })
    assert sorted(kinds(lang.scan_repo(repo))) == ["data/en/a.txt", "notes/archive.md", "src/other.py"]
    config.set_value("lang.allow", "notes/**, data/en")
    assert config.load()["lang"]["allow"] == ["notes/**", "data/en"]
    assert sorted(kinds(lang.scan_repo(repo))) == ["src/other.py"]


def test_glob_semantics():
    m = lambda g, p: bool(lang.glob_regex(g).match(p))  # noqa: E731
    assert m("*.po", "a/b/c.po") and not m("*.po", "c.pot")
    assert m("**/locales/**", "locales/x.json") and m("**/locales/**", "a/b/locales/c/x.json")
    assert m("docs/ru", "docs/ru/a/b.md") and not m("docs/ru", "docs/rus/a.md")
    assert m("/docs/**", "docs/a.md") and not m("/docs/**", "x/docs/a.md")
    assert m("*.lproj/**", "App/en.lproj/Main.strings") and not m("*.lproj/**", "App/en.lprojx/Main.strings")
    assert not m("**/messages/*.json", "messages/a/b.json")


def test_leak_allow_cyrillic_section_exempts_cyrillic_only(env):
    repo = make_repo(env.code, "app", {
        ".leak-allow": "cyrillic:\n  src/lexicon.py   # a lexicon\npaths:\n  vendor_notes/**\n",
        "src/lexicon.py": f"# {RU} {ZH}\n",
        "vendor_notes/a.md": f"{RU}\n",
    })
    rep = lang.scan_repo(repo)
    (f,) = rep["files"]
    assert f["path"] == "src/lexicon.py" and f["scripts"] == ["cjk"]


LEAK_CHECK = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "leak_check.py"


def _leak_module():
    spec = importlib.util.spec_from_file_location("leak_check_under_test", LEAK_CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_leak_allow_globs_mean_what_the_leak_guard_means(env):
    repo = make_repo(env.code, "app", {
        ".leak-allow": "cyrillic:\n  docs/*.md    # * crosses /\n  README.md\npaths:\n  gen/*.txt\n",
        "docs/top.md": f"{RU}\n", "docs/a/b.md": f"{RU}\n",
        "README.md": f"{RU}\n", "pkg/README.md": f"{RU}\n",
        "gen/x/y.txt": f"{RU}\n", "other/gen/z.txt": f"{RU}\n",
    })
    # exempt exactly where fnmatchcase on the repo-relative path says so; nothing is matched at any depth
    assert sorted(kinds(lang.scan_repo(repo))) == ["other/gen/z.txt", "pkg/README.md"]
    leak = _leak_module()
    cfg = leak.Config()
    leak.load_allow(cfg, repo)
    assert lang._leak_allow(repo)["cyrillic"] == cfg.allow["cyrillic"]
    assert lang._leak_allow(repo)["paths"] == cfg.allow["paths"]
    for glob in ("docs/*.md", "README.md", "*.md", "a/**", "x?y", "[ab]/c"):
        for path in ("docs/top.md", "docs/a/b.md", "README.md", "pkg/README.md", "a/b/c", "xzy", "a/c"):
            assert lang.leak_glob(path, [glob]) == leak._glob(path, [glob]), (glob, path)


# --- what is read ------------------------------------------------------------------------------

def test_untracked_binary_big_lock_and_vendored_files_are_skipped(env):
    repo = make_repo(env.code, "app", {
        "bin.dat": b"\x00\x01" + RU_BYTES,
        "big.txt": RU_BYTES * 200_000,
        "package-lock.json": f'{{"x": "{RU}"}}',
        "node_modules/pkg/index.js": f"// {RU}\n",
        "Pods/x/y.m": f"// {RU}\n",
        "ok.py": f"# {RU}\n",
    })
    write(repo, {"untracked.py": f"# {RU}\n"})
    (repo / "ok.py").write_text("# fine\n")
    git(repo, "add", "ok.py")  # still tracked, now English
    write(repo, {"later.py": f"# {RU}\n"})
    assert [f["path"] for f in lang.scan_repo(repo)["files"]] == []
    # a tracked file is read from the working tree; a deleted one is just skipped
    write(repo, {"ok.py": f"# {RU}\n"})
    (repo / "bin.dat").unlink()
    assert [f["path"] for f in lang.scan_repo(repo)["files"]] == ["ok.py"]


def test_not_a_git_repo_is_an_error_row(env, tmp_path):
    plain = tmp_path / "plain"
    (plain / ".git").mkdir(parents=True)
    rep = lang.scan_repo(plain)
    assert rep["error"] and rep["files"] == []


def test_retained_hits_are_capped_per_file_and_in_total(env, capsys, monkeypatch):
    monkeypatch.setattr(lang, "MAX_SAMPLES", 40)
    files = {f"docs/d{i:03}.md": (f"{RU}\n" * 20) for i in range(60)}
    repo = make_repo(env.code, "app", files)
    rep = lang.report([repo])
    rows = rep["repos"][0]["files"]
    assert len(rows) == 60 and rep["files"] == 60 and rep["lines"] == 1200       # nothing is miscounted
    assert all(f["lines"] == 20 and f["hits_total"] == 20 for f in rows)
    assert all(len(f["hits"]) <= 5 for f in rows)
    assert sum(len(f["hits"]) for f in rows) == 40                                 # the global cap
    assert rep["repos"][0]["counts"]["doc"] == dict(files=60, lines=1200)
    # the default JSON output is capped the same way; --quiet keeps none at all
    out = json.loads(run(["lang", "app", "--json"], capsys)[1])
    assert sum(len(f["hits"]) for f in out["repos"][0]["files"]) == 40
    quiet = lang.report([repo], samples=False)
    assert sum(len(f["hits"]) for f in quiet["repos"][0]["files"]) == 0 and quiet["lines"] == 1200


# --- commit messages ---------------------------------------------------------------------------

def test_commits_flag_scans_messages_on_the_default_branch(env, capsys):
    repo = make_repo(env.code, "app", {"a.py": "x = 1\n"}, message=f"{RU}\n\nbody line")
    write(repo, {"a.py": "x = 2\n"})
    git(repo, "commit", "-q", "-am", "English fix")
    code, out, _ = run(["lang", "app", "--commits", "5", "--json"], capsys)
    rep = json.loads(out)
    assert code == 0
    (c,) = rep["repos"][0]["commits"]
    assert c["lines"] == 1 and len(c["sha"]) == 7 and RU in c["subject"]
    assert rep["commits"] == 1 and rep["files"] == 0
    # only the last N: the Russian one is the second newest
    assert json.loads(run(["lang", "app", "--commits", "1", "--json"], capsys)[1])["commits"] == 0
    # off by default
    assert json.loads(run(["lang", "app", "--json"], capsys)[1])["commits"] == 0
    code, out, _ = run(["lang", "app", "--commits", "5"], capsys)
    assert "1 commit message(s)" in out and "commit " in out


# --- the command -------------------------------------------------------------------------------

def test_human_output_counts_and_top_files(env, capsys):
    files = {f"docs/d{i}.md": f"{RU}\n" * (i + 1) for i in range(7)}
    files["src/a.py"] = f'x = "{RU}"\n'
    make_repo(env.code, "app", files)
    make_repo(env.code, "clean", {"a.py": "x = 1\n"})
    code, out, _ = run(["lang"], capsys)
    assert code == 0
    assert "non-English text: 8 file(s) in 1 repo(s)" in out
    assert "app: 8 file(s) — doc 7 file(s)/28 line(s), string 1 file(s)/1 line(s) (check: localization?)" in out
    assert "docs/d6.md  [doc]  7 line(s)" in out and f'"{RU}"' in out
    assert "and 3 more file(s)" in out
    assert "clean:" not in out
    assert "Latin-script languages" in out


def test_clean_repos_say_so_and_quiet_prints_nothing(env, capsys):
    make_repo(env.code, "app", {"a.py": "x = 1\n"})
    code, out, _ = run(["lang"], capsys)
    assert code == 0 and "no non-Latin text in the tracked files of 1 repo(s)" in out
    assert run(["lang", "--quiet"], capsys) == (0, "", "")


def test_quiet_is_one_line_per_repo(env, capsys):
    make_repo(env.code, "app", {"README.md": f"{RU}\n", "b.py": f"# {RU}\n"})
    make_repo(env.code, "other", {"README.md": f"{RU}\n"})
    code, out, _ = run(["lang", "--quiet"], capsys)
    assert code == 0
    assert out.splitlines() == ["non-English text: 3 file(s) in 2 repo(s)",
                                "app: 2 file(s) — doc 1 file(s)/1 line(s), comment 1 file(s)/1 line(s)",
                                "other: 1 file(s) — doc 1 file(s)/1 line(s)"]


def test_json_has_every_hit_and_exit_is_zero(env, capsys):
    make_repo(env.code, "app", {"a.py": f"# {RU}\ny = '{RU}'\n"})
    code, out, _ = run(["lang", "app", "--json"], capsys)
    rep = json.loads(out)
    assert code == 0 and rep["scanned"] == 1 and rep["repos_with_text"] == 1 and rep["files"] == 1 and rep["lines"] == 2
    (f,) = rep["repos"][0]["files"]
    assert [(h["line"], h["kind"], h["script"]) for h in f["hits"]] == [(1, "comment", "cyrillic"), (2, "string", "cyrillic")]


def test_repo_arguments_names_paths_and_usage_errors(env, capsys, tmp_path):
    repo = make_repo(env.code, "app", {"a.md": f"{RU}\n"})
    make_repo(env.code, "zzz", {"a.md": f"{RU}\n"})
    assert json.loads(run(["lang", "app", "--json"], capsys)[1])["scanned"] == 1
    assert json.loads(run(["lang", str(repo), "--json"], capsys)[1])["scanned"] == 1
    code, out, err = run(["lang", "nope"], capsys)
    assert code == 2 and "nope: not a git repository" in err and out == ""
    assert run(["lang", "--commits", "-1"], capsys)[0] == 2
    # without arguments: every repo under code_root and ops_root
    make_repo(tmp_path / "ops", "tool", {"a.md": f"{RU}\n"})
    assert json.loads(run(["lang", "--json"], capsys)[1])["scanned"] == 3


# --- weekly routine and digest -----------------------------------------------------------------

def _wrapper(watch_line='"$TEYLA" models watch --refresh'):
    return routine_install.WRAPPER_TEMPLATE.format(teyla_bin="/x/teyla", env_sh="", stamp="/s.last", label="l",
                                                   runs_root=routine_install._runs_root(), models_watch_line=watch_line)


def test_weekly_wrapper_runs_lang_before_the_digest(env):
    text = _wrapper()
    assert '"$TEYLA" lang --quiet > "$OUT_DIR/lang.md" 2>&1\n' in text
    assert text.index("lang --quiet") < text.index("digest --write")


def test_a_wrapper_without_the_lang_line_is_stale(env, monkeypatch):
    w = env.home / ".teyla" / "weekly.sh"
    monkeypatch.setattr(routine_install, "WRAPPER_PATH", w)
    w.write_text(_wrapper(routine_install._watch_line()))
    assert not routine_install._wrapper_stale(w, "/x/teyla")
    w.write_text(_wrapper(routine_install._watch_line()).replace('"$TEYLA" lang --quiet > "$OUT_DIR/lang.md" 2>&1\n', ""))
    assert routine_install._wrapper_stale(w, "/x/teyla")  # written before `teyla lang`


def test_digest_line_comes_from_the_weekly_counts(env, capsys):
    assert lang.digest_candidates() == []  # nothing has run yet
    make_repo(env.code, "app", {"a.md": f"{RU}\n", "b.md": f"{RU}\n"})
    make_repo(env.code, "other", {"a.md": f"{RU}\n"})
    run(["lang", "app", "--quiet"], capsys)
    assert lang.digest_candidates() == []  # a run on named repos is not the weekly picture
    run(["lang", "--quiet"], capsys)
    (c,) = lang.digest_candidates()
    assert c["text"] == "non-English text: 3 file(s) in 2 repo(s)" and c["step"] == "teyla lang"
    lines, _ = digest.build([], [], [], {}, extra=[c])
    assert any("non-English text: 3 file(s) in 2 repo(s)" in line and "`teyla lang`" in line for line in lines)


def test_digest_line_is_silent_when_clean_or_old(env, capsys):
    make_repo(env.code, "app", {"a.py": "x = 1\n"})
    run(["lang", "--quiet"], capsys)
    assert lang.digest_candidates() == []
    lang.cache_path().write_text(json.dumps(dict(at="2020-01-01T00:00:00+00:00", files=4, repos=2)))
    assert lang.digest_candidates() == []  # months old: not this week's news
    lang.cache_path().write_text("not json")
    assert lang.digest_candidates() == []


def test_digest_write_includes_the_line(env, capsys, monkeypatch):
    make_repo(env.code, "app", {"a.md": f"{RU}\n"})
    run(["lang", "--quiet"], capsys)
    lines = digest.write(findings=[], doctor_checks=[], reports=[], notify_now=False)
    assert any("non-English text: 1 file(s) in 1 repo(s)" in line for line in lines)


# --- quoted labels in English prose ------------------------------------------------------------

LQ, RQ = "«", "»"
LDQ, RDQ, LOW = "“", "”", "„"


def _hits(env, files):
    repo = make_repo(env.code, "app", files)
    return {(f["path"], h["line"]): h["kind"] for f in lang.scan_repo(repo)["files"] for h in f["hits"]}


def test_quoted_non_latin_text_in_comments_and_docs_is_not_a_finding(env):
    quoted = [f"{LQ}{RU}{RQ}", f"{LDQ}{RU}{RDQ}", f"{LOW}{RU}{LDQ}", f'"{RU}"', f"'{RU}'", f"`{RU}`"]
    comments = "".join(f"// the {q} sheet closes\n" for q in quoted)
    docs = "".join(f"The {q} button.\n" for q in quoted)
    assert _hits(env, {"a.swift": comments, "docs/guide.md": docs, "b.py": f'x = 1  # tap {LQ}{RU}{RQ}\n'}) == {}


def test_a_non_latin_run_in_english_prose_is_not_a_finding_but_a_mostly_non_latin_line_is(env):
    hits = _hits(env, {
        "a.ts": f"// this sheet closes after the {RU} label is tapped\n"       # 8 Latin words, 1 non-Latin
                f"// {RU} {RU} make build\n"                                   # 3 Latin words, 4 non-Latin
                f"// {RU}\n"
                f"// don't touch it: {RU} {RU} {RU} ok\n",                     # apostrophe is not a quote
        "docs/n.md": f"Open the {RU} screen from the menu bar.\n{RU} {RU} the menu\n",
    })
    assert hits == {("a.ts", 2): "comment", ("a.ts", 3): "comment", ("a.ts", 4): "comment", ("docs/n.md", 2): "doc"}


def test_strings_and_fixtures_are_classified_as_before(env):
    hits = _hits(env, {
        "a.py": f'label = "{RU}"  # the {RU} label of the sheet\n',
        "tests/test_a.py": f'EXPECTED = "{RU}"\n',
        "b.ts": f'const s = "{RU}"; // see the "{RU}" sheet\n',
    })
    assert hits == {("a.py", 1): "string", ("tests/test_a.py", 1): "fixture", ("b.ts", 1): "string"}


def test_only_the_comment_part_of_a_line_decides(env):
    # English code around the comment must not turn a Russian comment into prose
    hits = _hits(env, {"a.py": f"def open_the_sheet(a, b, c):  # {RU} {RU}\n    pass\n"})
    assert hits == {("a.py", 1): "comment"}


def test_help_says_quoted_labels_are_not_counted(capsys):
    with pytest.raises(SystemExit):
        cli.main(["lang", "--help"])
    out = capsys.readouterr().out
    assert "Quoted labels in English prose are not counted" in out and "never fetches" in out


# --- stale clones ------------------------------------------------------------------------------

def _clone_behind(env, name="app", commit_date=None, fetch=True):
    """An origin, a clone of it, and `commits_ahead` more commits on origin; returns (clone, origin)."""
    origin = env.code.parent / "origins" / f"{name}.git"
    origin.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    author = env.code.parent / "author"
    subprocess.run(["git", "clone", "-q", str(origin), str(author)], check=True, capture_output=True)
    envv = dict(__import__("os").environ)
    if commit_date:
        envv.update(GIT_AUTHOR_DATE=commit_date, GIT_COMMITTER_DATE=commit_date)

    def commit(msg, date=True):
        subprocess.run(["git", "-C", str(author), "-c", "user.name=T", "-c", "user.email=t@example.com",
                        "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", msg],
                       check=True, env=envv if date else dict(__import__("os").environ))
    commit("one")
    git(author, "push", "-q", "origin", "main")
    clone = env.code / name
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    commit("two", date=False)
    commit("three", date=False)
    git(author, "push", "-q", "origin", "main")
    if fetch:
        git(clone, "fetch", "-q")
    return clone, origin


def test_a_clone_behind_its_upstream_is_flagged_from_the_refs_it_has(env, capsys):
    clone, _ = _clone_behind(env)
    b = lang.behind_upstream(clone)
    assert b["upstream"] == "origin/main" and b["commits"] == 2 and b["old"] is False
    code, out, _ = run(["lang", "app"], capsys)
    assert code == 0
    assert "app: clone is 2 commits behind origin/main — results are for the local tree; git pull first" in out
    code, out, _ = run(["lang", "app", "--quiet"], capsys)
    assert out.splitlines() == ["app: clone is 2 commits behind origin/main — results are for the local tree; git pull first"]
    rep = json.loads(run(["lang", "app", "--json"], capsys)[1])
    assert rep["stale"] == ["app"] and rep["repos"][0]["behind"]["commits"] == 2


def test_an_old_last_commit_on_a_behind_clone_says_so(env, capsys):
    clone, _ = _clone_behind(env, commit_date="2020-01-01T00:00:00Z")
    b = lang.behind_upstream(clone)
    assert b["old"] is True and b["last_commit_days"] > 30
    assert "last local commit" in run(["lang", "app", "--quiet"], capsys)[1]


def test_no_fetch_no_warning_and_a_current_clone_is_quiet(env, capsys, monkeypatch):
    clone, origin = _clone_behind(env, fetch=False)
    assert lang.behind_upstream(clone) is None           # origin is ahead, but the refs do not know it
    assert run(["lang", "app", "--quiet"], capsys) == (0, "", "")
    assert git_out(clone, "rev-parse", "origin/main") != git_out(origin, "rev-parse", "main")  # nothing fetched
    git(clone, "pull", "-q")
    assert lang.behind_upstream(clone) is None
    assert json.loads(run(["lang", "app", "--json"], capsys)[1])["stale"] == []


def test_the_check_runs_no_network_git_commands(env, monkeypatch):
    clone, _ = _clone_behind(env)
    seen = []
    real = lang._git
    monkeypatch.setattr(lang, "_git", lambda repo, *a, **k: seen.append(a[0]) or real(repo, *a, **k))
    lang.behind_upstream(clone)
    assert seen and not {"fetch", "pull", "remote", "ls-remote", "push"} & set(seen)


def test_a_branch_without_an_upstream_is_compared_with_origin_default_only_on_the_default_branch(env):
    clone, _ = _clone_behind(env)
    git(clone, "branch", "--unset-upstream")
    assert lang.behind_upstream(clone)["commits"] == 2    # on main: origin/main is the comparison
    git(clone, "checkout", "-q", "-b", "feature")
    assert lang.behind_upstream(clone) is None            # a feature branch is not a stale clone


def git_out(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()
