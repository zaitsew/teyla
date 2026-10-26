"""The App Store listing files under apps/store/listing and the script that sends them. No network:
the tests read files, import the script and run `--help`."""
from __future__ import annotations

import importlib.util
import pathlib
import struct
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "apps" / "store" / "app-store.py"
LISTING = ROOT / "apps" / "store" / "listing"
PLATFORMS = ("ios", "macos")
FIELDS = ("name", "subtitle", "promotional_text", "description", "keywords", "whats_new",
          "review_notes", "support_url", "privacy_url")

spec = importlib.util.spec_from_file_location("app_store", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)


def read(platform: str, field: str) -> str:
    return (LISTING / platform / "en-US" / f"{field}.txt").read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize("field", FIELDS)
def test_every_field_exists_and_is_not_empty(platform, field):
    assert read(platform, field)


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize("field,limit", [("name", 30), ("subtitle", 30), ("promotional_text", 170),
                                         ("keywords", 100), ("description", 4000), ("whats_new", 4000),
                                         ("review_notes", 4000)])
def test_apple_character_limits(platform, field, limit):
    assert len(read(platform, field)) <= limit


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize("field", ("name", "subtitle", "promotional_text", "description", "keywords", "whats_new"))
def test_no_model_provider_in_the_listing(platform, field):
    text = read(platform, field).lower()
    for banned in ("openai", "chatgpt", "claude", "anthropic", "gemini", "grok", "codex"):
        assert banned not in text, f"{platform}/{field} names {banned}"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_review_notes_carry_the_sections_a_reviewer_asks_for(platform):
    notes = read(platform, "review_notes")
    for section in ("HOW TO SEE EVERYTHING", "DECLARED CAPABILITIES", "PRIVACY AND DATA", "AI CONTENT",
                    "BUSINESS MODEL", "REGIONS", "China"):
        assert section in notes
    assert "TODO(owner)" not in notes


def test_mac_notes_say_how_to_reopen_the_window():
    notes = read("macos", "review_notes")
    assert "Window > Teyla (Cmd-0)" in notes


def test_keywords_have_no_wasted_space():
    for platform in PLATFORMS:
        assert ", " not in read(platform, "keywords")


def test_app_level_fields_match_between_platforms():
    for field in store.APP_LEVEL_FIELDS:
        assert read("macos", field) == read("ios", field)


def test_the_shipped_listing_passes_the_script_check():
    assert store.check_listing() == []


def test_script_is_executable_and_help_runs():
    assert SCRIPT.stat().st_mode & 0o111
    for args in ([], ["push"], ["screenshots"], ["submit"], ["status"]):
        done = subprocess.run([sys.executable, str(SCRIPT), *args, "--help"], capture_output=True, text=True, timeout=30)
        assert done.returncode == 0, done.stderr
        assert "usage:" in done.stdout
    top = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=30).stdout
    for command in ("status", "push", "screenshots", "submit", "--platform"):
        assert command in top


def test_platform_option_works_before_and_after_the_command():
    assert store.build_parser().parse_args(["--platform", "macos", "status"]).platform == "macos"
    assert store.build_parser().parse_args(["status", "--platform", "macos"]).platform == "macos"
    assert store.build_parser().parse_args(["status"]).platform == "ios"


def test_script_settings():
    assert store.BUNDLE_ID == "com.zaitsew.teyla"
    assert store.VERSIONS == {"IOS": "0.32.0", "MAC_OS": "0.32.0"}
    assert "CHN" in store.EXCLUDED_TERRITORIES
    assert (store.PRIMARY_CATEGORY, store.SECONDARY_CATEGORY) == ("DEVELOPER_TOOLS", "PRODUCTIVITY")
    assert set(store.AGE_RATING.values()) <= {"NONE", False}


def _copy_listing(tmp_path):
    import shutil
    shutil.copytree(LISTING, tmp_path / "listing")
    return tmp_path / "listing"


def test_check_refuses_a_provider_name_a_long_field_and_a_missing_section(tmp_path):
    root = _copy_listing(tmp_path)
    ios = root / "ios" / "en-US"
    (ios / "description.txt").write_text("Works with Claude and more.\n")
    (ios / "keywords.txt").write_text("a" * 101 + "\n")
    (ios / "review_notes.txt").write_text("HOW TO SEE EVERYTHING\n")
    problems = "\n".join(store.check_listing(root=root))
    assert "names a model provider" in problems
    assert "keywords.txt is 101 characters" in problems
    assert "no BUSINESS MODEL section" in problems
    assert "does not say why China is excluded" in problems


def test_check_refuses_a_todo_and_a_missing_file(tmp_path):
    root = _copy_listing(tmp_path)
    (root / "macos" / "en-US" / "whats_new.txt").write_text("TODO(owner) write this\n")
    (root / "ios" / "en-US" / "support_url.txt").unlink()
    problems = "\n".join(store.check_listing(root=root))
    assert "whats_new.txt still has a TODO(owner)" in problems
    assert "ios/en-US/support_url.txt is missing or empty" in problems


def test_check_refuses_a_mac_name_that_differs_from_ios(tmp_path):
    root = _copy_listing(tmp_path)
    (root / "macos" / "en-US" / "name.txt").write_text("Another name\n")
    assert "differs from the iOS file" in "\n".join(store.check_listing(root=root))


def test_review_contact_never_invents_a_phone_number():
    assert "contactPhone" not in store.review_contact({})
    assert "contactEmail" not in store.review_contact({})
    got = store.review_contact({"TEYLA_REVIEW_PHONE": "+10000000", "TEYLA_REVIEW_EMAIL": "a@example.com"})
    assert got["contactPhone"] == "+10000000" and got["contactEmail"] == "a@example.com"
    assert "contactFirstName" not in got  # names come from the environment too


def test_dry_run_output_hides_the_phone_number():
    body = {"data": {"attributes": {"contactPhone": "+10000000", "notes": "x"}}}
    assert store._redact(body)["data"]["attributes"]["contactPhone"] == "<redacted>"


def _png(path, width, height):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00")


def test_screenshot_sizes_are_checked(tmp_path):
    _png(tmp_path / "iphone69" / "en-US" / "1.png", 1320, 2868)
    _png(tmp_path / "iphone69" / "en-US" / "2.png", 1290, 2796)
    problems = store.check_screenshots(tmp_path, store.SHOT_SLOTS_IOS)
    assert len(problems) == 1 and "2.png is 1290x2796, expected 1320x2868" in problems[0]
    _png(tmp_path / "mac" / "en-US" / "1.png", 2880, 1800)
    assert store.check_screenshots(tmp_path, store.SHOT_SLOTS_MAC) == []
