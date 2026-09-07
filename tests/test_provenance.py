"""What made a file, in the form that outlives the app that wrote it.

Every checkout here is a real git repository under tmp_path: the module's whole
job is reading one, so a fake would test the fake.
"""
from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from app_support import provenance

_IDENTITY = ("-c", "user.email=test@example.com", "-c", "user.name=Test")


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *_IDENTITY, *args],
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _checkout(tmp_path: Path, name: str = "someapp") -> Path:
    """A checkout of *name* with one commit, its package one level down."""
    repo = tmp_path / name
    (repo / name).mkdir(parents=True)
    (repo / name / "app.py").write_text("", encoding="utf-8")
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "first")
    return repo


class TestStamp:
    def test_names_the_app_that_made_the_file(self, tmp_path: Path):
        anchor = tmp_path / "app.py"

        assert provenance.stamp("origenerator", anchor=anchor)["app"] == "origenerator"

    def test_records_the_commit_the_code_is_checked_out_at(self, tmp_path: Path):
        repo = _checkout(tmp_path)

        recorded = provenance.stamp("someapp", anchor=repo / "someapp" / "app.py")

        assert recorded["app_commit"] == _git(repo, "rev-parse", "HEAD")

    def test_reads_the_checkout_once_so_a_running_app_keeps_its_commit(self, tmp_path: Path):
        # A tray that has been up for days holds the code it imported at launch;
        # asking git again would report a checkout the running code is not.
        repo = _checkout(tmp_path)
        anchor = repo / "someapp" / "app.py"
        first = provenance.stamp("someapp", anchor=anchor)["app_commit"]

        (repo / "someapp" / "later.py").write_text("", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "second")

        assert _git(repo, "rev-parse", "HEAD") != first
        assert provenance.stamp("someapp", anchor=anchor)["app_commit"] == first

    def test_says_when_the_checkout_carried_edits_the_commit_does_not(self, tmp_path: Path):
        # A preview branch is generated from with edits in the tree; the sha
        # alone would name code that never ran.
        repo = _checkout(tmp_path)
        (repo / "someapp" / "app.py").write_text("edited", encoding="utf-8")

        assert provenance.stamp("someapp", anchor=repo / "someapp" / "app.py")["app_dirty"] is True

    def test_a_clean_checkout_is_not_dirty(self, tmp_path: Path):
        repo = _checkout(tmp_path)

        assert provenance.stamp("someapp", anchor=repo / "someapp" / "app.py")["app_dirty"] is False

    def test_code_outside_a_checkout_records_no_commit_rather_than_a_guess(self, tmp_path: Path):
        # A wrong version is worse than a missing one: an upgrade sweep would
        # skip the file believing it current.
        recorded = provenance.stamp("someapp", anchor=tmp_path / "loose" / "app.py")

        assert recorded["app_commit"] is None
        assert recorded["app_dirty"] is None

    def test_records_the_recipe_and_the_version_of_it_that_ran(self, tmp_path: Path):
        recorded = provenance.stamp("origenerator", anchor=tmp_path / "app.py",
                                    recipe="wan22_i2v", recipe_version="v007")

        assert (recorded["recipe"], recorded["recipe_version"]) == ("wan22_i2v", "v007")

    def test_records_when_it_was_stamped_because_the_file_gets_moved(self, tmp_path: Path):
        # Evolver moves a clip through the library, so its mtime stops answering
        # when the thing was made.
        stamped = datetime.fromisoformat(
            provenance.stamp("someapp", anchor=tmp_path / "app.py")["stamped_at"])

        assert stamped.tzinfo is not None
        assert abs((stamped - datetime.now(UTC)).total_seconds()) < 60

    def test_is_the_same_keys_however_little_is_known(self, tmp_path: Path):
        # A fact nobody knows is an explicit None, never an absent key: a reader
        # of a ten-year-old file should not have to guess which shape it got.
        known = provenance.stamp("origenerator", anchor=tmp_path / "app.py",
                                 recipe="wan22_i2v", recipe_version="v007")
        unknown = provenance.stamp("someapp", anchor=tmp_path / "app.py")

        assert known.keys() == unknown.keys() == {
            "schema", "app", "app_commit", "app_dirty",
            "recipe", "recipe_version", "stamped_at"}
        assert unknown["schema"] == provenance.SCHEMA

    def test_a_checkout_with_no_commit_yet_records_none(self, tmp_path: Path):
        # git reports "(initial)" as the oid of an unborn HEAD, which is a word,
        # not a commit anything can be found by.
        package = tmp_path / "someapp" / "someapp"
        package.mkdir(parents=True)
        _git(tmp_path, "init", "-q", "-b", "main", str(tmp_path / "someapp"))

        assert provenance.stamp("someapp", anchor=package / "app.py")["app_commit"] is None
