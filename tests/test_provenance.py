from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from production_machine import IDENTIFIED, git

from app_support import provenance


def _checkout(tmp_path: Path, name: str = "someapp") -> Path:
    repo = tmp_path / name
    (repo / name).mkdir(parents=True)
    (repo / name / "app.py").write_text("", encoding="utf-8")
    git(*IDENTIFIED, "init", "-q", "-b", "main", str(repo), cwd=repo.parent)
    git(*IDENTIFIED, "add", "-A", cwd=repo)
    git(*IDENTIFIED, "commit", "-qm", "first", cwd=repo)
    return repo


class TestStamp:
    def test_names_the_app_that_made_the_file(self, tmp_path: Path):
        anchor = tmp_path / "app.py"

        assert provenance.stamp("origenerator", anchor=anchor)["app"] == "origenerator"

    def test_records_the_commit_the_code_is_checked_out_at(self, tmp_path: Path):
        repo = _checkout(tmp_path)

        recorded = provenance.stamp("someapp", anchor=repo / "someapp" / "app.py")

        assert recorded["app_commit"] == git(*IDENTIFIED, "rev-parse", "HEAD", cwd=repo)

    def test_reads_the_checkout_once_so_a_running_app_keeps_its_commit(self, tmp_path: Path):
        repo = _checkout(tmp_path)
        anchor = repo / "someapp" / "app.py"
        first = provenance.stamp("someapp", anchor=anchor)["app_commit"]

        (repo / "someapp" / "later.py").write_text("", encoding="utf-8")
        git(*IDENTIFIED, "add", "-A", cwd=repo)
        git(*IDENTIFIED, "commit", "-qm", "second", cwd=repo)

        assert git(*IDENTIFIED, "rev-parse", "HEAD", cwd=repo) != first
        assert provenance.stamp("someapp", anchor=anchor)["app_commit"] == first

    def test_says_when_the_checkout_carried_edits_the_commit_does_not(self, tmp_path: Path):
        repo = _checkout(tmp_path)
        (repo / "someapp" / "app.py").write_text("edited", encoding="utf-8")

        assert provenance.stamp("someapp", anchor=repo / "someapp" / "app.py")["app_dirty"] is True

    def test_a_clean_checkout_is_not_dirty(self, tmp_path: Path):
        repo = _checkout(tmp_path)

        assert provenance.stamp("someapp", anchor=repo / "someapp" / "app.py")["app_dirty"] is False

    def test_code_outside_a_checkout_records_no_commit_rather_than_a_guess(self, tmp_path: Path):
        recorded = provenance.stamp("someapp", anchor=tmp_path / "loose" / "app.py")

        assert recorded["app_commit"] is None
        assert recorded["app_dirty"] is None

    def test_records_the_method_and_the_version_of_it_that_ran(self, tmp_path: Path):
        recorded = provenance.stamp("origenerator", anchor=tmp_path / "app.py",
                                    method="wan22_i2v", method_version="v007")

        assert (recorded[provenance.METHOD], recorded[provenance.METHOD_VERSION]) == (
            "wan22_i2v", "v007")

    def test_keeps_what_ran_under_the_keys_every_file_on_disk_already_holds(self):
        assert (provenance.METHOD, provenance.METHOD_VERSION) == ("recipe", "recipe_version")

    def test_records_when_it_was_stamped_because_the_file_gets_moved(self, tmp_path: Path):
        stamped = datetime.fromisoformat(
            provenance.stamp("someapp", anchor=tmp_path / "app.py")["stamped_at"])

        assert stamped.tzinfo is not None
        assert abs((stamped - datetime.now(UTC)).total_seconds()) < 60

    def test_is_the_same_keys_however_little_is_known(self, tmp_path: Path):
        known = provenance.stamp("origenerator", anchor=tmp_path / "app.py",
                                 method="wan22_i2v", method_version="v007")
        unknown = provenance.stamp("someapp", anchor=tmp_path / "app.py")

        assert known.keys() == unknown.keys() == {
            "schema", "app", "app_commit", "app_dirty",
            provenance.METHOD, provenance.METHOD_VERSION, "stamped_at"}
        assert unknown["schema"] == provenance.SCHEMA

    def test_a_checkout_with_no_commit_yet_records_none(self, tmp_path: Path):
        # git reports "(initial)" as the oid of an unborn HEAD, which is a word,
        # not a commit anything can be found by.
        package = tmp_path / "someapp" / "someapp"
        package.mkdir(parents=True)
        git(*IDENTIFIED, "init", "-q", "-b", "main", str(tmp_path / "someapp"), cwd=tmp_path)

        assert provenance.stamp("someapp", anchor=package / "app.py")["app_commit"] is None
