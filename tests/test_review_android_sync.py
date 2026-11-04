"""The Android package's vendoring script deletes its target, so it must refuse anything else."""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "packages/review-android/scripts/teyla-review-sync-android"
HEADING = "# Teyla Android review, vendored\n"


def sync(cwd: Path, *args: str) -> int:
    done = subprocess.run(
        ["bash", str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True, env={"TEYLA_REPO": str(REPO), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    )
    return done.returncode


def product(tmp_path: Path) -> Path:
    root = tmp_path / "product"
    root.mkdir()
    return root


def test_a_new_folder_is_filled_and_can_be_refreshed(tmp_path):
    root = product(tmp_path)
    assert sync(root, "vendor/review") == 0
    assert (root / "vendor/review/teyla-review/build.gradle.kts").is_file()
    assert (root / "vendor/review/teyla-review-noop/build.gradle.kts").is_file()
    assert (root / "vendor/review/VENDORED.md").read_text().startswith(HEADING)
    (root / "vendor/review/stale.kt").write_text("old")
    assert sync(root, "vendor/review") == 0
    assert not (root / "vendor/review/stale.kt").exists()


def test_the_copy_holds_no_tests_and_no_build_output(tmp_path):
    root = product(tmp_path)
    assert sync(root) == 0
    copy = root / "vendor/teyla-review-android"
    assert (copy / "teyla-review/src/main/kotlin/teyla/review/ReviewOverlay.kt").is_file()
    assert not (copy / "teyla-review/src/test").exists()
    assert not (copy / "teyla-review/build").exists()
    assert not (copy / "teyla-review-noop/src/main/kotlin/teyla/review/ReviewOverlay.kt").exists()


def test_a_path_out_of_the_repo_is_refused(tmp_path):
    root = product(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep").write_text("x")
    for dest in ("../other", str(other), ".", "a/../.."):
        assert sync(root, dest) == 2, dest
    assert (other / "keep").is_file()


def test_a_symlink_on_the_way_out_of_the_repo_is_refused(tmp_path):
    root = product(tmp_path)
    outside = tmp_path / "outside"
    (outside / "copy").mkdir(parents=True)
    (outside / "copy/VENDORED.md").write_text(HEADING)
    (root / "linked").symlink_to(outside)
    assert sync(root, "linked/copy") == 2
    assert sync(root, "linked/new") == 2
    (root / "direct").symlink_to(outside / "copy")
    assert sync(root, "direct") == 2
    assert (outside / "copy/VENDORED.md").is_file()


def test_a_folder_that_is_not_our_copy_is_refused(tmp_path):
    root = product(tmp_path)
    for name, marker in (("plain", None), ("theirs", "# Some other library, vendored\n"), ("the-web-copy", "# Teyla web review, vendored\n")):
        folder = root / name
        folder.mkdir()
        (folder / "keep").write_text("x")
        if marker:
            (folder / "VENDORED.md").write_text(marker)
        assert sync(root, name) == 2
        assert (folder / "keep").is_file()
