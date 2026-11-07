from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from production_machine import IDENTIFIED, git

from app_support import provenance


def _a_real_repository_since_reading_one_is_the_whole_job(tmp_path: Path, name: str = "someapp") -> Path:
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

    def test_records_the_commit_git_reports_at_run_time_since_the_apps_run_from_their_checkouts(self, tmp_path: Path):
        repo = _a_real_repository_since_reading_one_is_the_whole_job(tmp_path)

        recorded = provenance.stamp("someapp", anchor=repo / "someapp" / "app.py")

        assert recorded["app_commit"] == git(*IDENTIFIED, "rev-parse", "HEAD", cwd=repo)

    def test_reads_the_checkout_once_so_a_running_app_keeps_its_commit_and_a_sweep_asks_git_once(
            self, tmp_path: Path):
        repo = _a_real_repository_since_reading_one_is_the_whole_job(tmp_path)
        anchor = repo / "someapp" / "app.py"
        first = provenance.stamp("someapp", anchor=anchor)["app_commit"]

        (repo / "someapp" / "later.py").write_text("", encoding="utf-8")
        git(*IDENTIFIED, "add", "-A", cwd=repo)
        git(*IDENTIFIED, "commit", "-qm", "second", cwd=repo)

        assert git(*IDENTIFIED, "rev-parse", "HEAD", cwd=repo) != first
        assert provenance.stamp("someapp", anchor=anchor)["app_commit"] == first

    def test_says_when_the_checkout_carried_edits_the_commit_does_not_as_a_previews_often_does(self, tmp_path: Path):
        repo = _a_real_repository_since_reading_one_is_the_whole_job(tmp_path)
        (repo / "someapp" / "app.py").write_text("edited", encoding="utf-8")

        assert provenance.stamp("someapp", anchor=repo / "someapp" / "app.py")["app_dirty"] is True

    def test_a_clean_checkout_is_not_dirty(self, tmp_path: Path):
        repo = _a_real_repository_since_reading_one_is_the_whole_job(tmp_path)

        assert provenance.stamp("someapp", anchor=repo / "someapp" / "app.py")["app_dirty"] is False

    def test_outside_a_checkout_the_commit_is_none_a_guess_would_make_a_sweep_skip_the_file(self, tmp_path: Path):
        recorded = provenance.stamp("someapp", anchor=tmp_path / "loose" / "app.py")

        assert recorded["app_commit"] is None
        assert recorded["app_dirty"] is None

    def test_records_the_method_version_a_person_bumps_by_hand_beside_the_commit_that_moves_for_other_reasons(
            self, tmp_path: Path):
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

    def test_the_same_keys_however_little_is_known_so_an_old_file_needs_no_shape_worked_out(self, tmp_path: Path):
        known = provenance.stamp("origenerator", anchor=tmp_path / "app.py",
                                 method="wan22_i2v", method_version="v007")
        unknown = provenance.stamp("someapp", anchor=tmp_path / "app.py")

        assert known.keys() == unknown.keys()
        assert unknown["schema"] == provenance.SCHEMA

    def test_schema_1_is_these_seven_keys_so_a_changed_key_is_a_new_schema(self, tmp_path: Path):
        stamped = provenance.stamp("someapp", anchor=tmp_path / "app.py")

        assert (provenance.SCHEMA, set(stamped)) == (1, {
            "schema", "app", "app_commit", "app_dirty",
            provenance.METHOD, provenance.METHOD_VERSION, "stamped_at"})

    def test_a_git_that_stops_answering_is_given_up_on_rather_than_freezing_the_app(self, tmp_path: Path):
        with patch("app_support.provenance.run_process_tree",
                   side_effect=subprocess.TimeoutExpired("git", provenance._GIVE_UP_ON_A_HUNG_GIT_AFTER_S)):
            recorded = provenance.stamp("someapp", anchor=tmp_path / "stalled" / "app.py")

        assert (recorded["app_commit"], recorded["app_dirty"]) == (None, None)

    def test_a_worktree_records_its_own_commit_so_a_previews_output_names_the_preview(self, tmp_path: Path):
        primary = _a_real_repository_since_reading_one_is_the_whole_job(tmp_path)
        worktree = tmp_path / "preview"
        git(*IDENTIFIED, "worktree", "add", "-q", "-b", "preview", str(worktree), cwd=primary)
        (worktree / "someapp" / "later.py").write_text("", encoding="utf-8")
        git(*IDENTIFIED, "add", "-A", cwd=worktree)
        git(*IDENTIFIED, "commit", "-qm", "the preview", cwd=worktree)

        recorded = provenance.stamp("someapp", anchor=worktree / "someapp" / "app.py")

        assert recorded["app_commit"] == git(*IDENTIFIED, "rev-parse", "HEAD", cwd=worktree)
        assert recorded["app_commit"] != git(*IDENTIFIED, "rev-parse", "HEAD", cwd=primary)

    def test_a_checkout_with_no_commit_yet_records_none(self, tmp_path: Path):
        # git reports "(initial)" as the oid of an unborn HEAD, which is a word,
        # not a commit anything can be found by.
        package = tmp_path / "someapp" / "someapp"
        package.mkdir(parents=True)
        git(*IDENTIFIED, "init", "-q", "-b", "main", str(tmp_path / "someapp"), cwd=tmp_path)

        assert provenance.stamp("someapp", anchor=package / "app.py")["app_commit"] is None
