from __future__ import annotations

import pytest

from app_support import conflict_markers
from app_support.conflict_markers import Leftover
from app_support.git_files import git

OURS, BETWEEN, THEIRS = "<" * 7 + " HEAD\n", "=" * 7 + "\n", ">" * 7 + " 1234abc (a change)\n"
A_CONFLICT = OURS + "x = 1\n" + BETWEEN + "x = 2\n" + THEIRS


def _sha(branch) -> str:
    return git(branch.path, "rev-parse", "HEAD").strip()


class TestTheGate:
    def test_it_names_each_commit_and_file_that_holds_a_leftover(self, branch_from):
        branch = branch_from({"pane.py": "x = 0\n"})
        branch.commit({"pane.py": A_CONFLICT}, "a pick finished by hand")
        left_in = _sha(branch)
        branch.commit({"pane.py": "x = 2\n"})

        with pytest.raises(AssertionError) as refused:
            conflict_markers.assert_no_commit_holds_a_leftover(branch.path, since="main")

        assert f"{left_in[:12]} a pick finished by hand: pane.py: {OURS.strip()}" in str(refused.value)
        assert f"given {conflict_markers.FIXTURE_ATTRIBUTE} in .gitattributes" in str(refused.value)

    def test_a_branch_whose_commits_hold_none_passes(self, branch_from):
        branch = branch_from({"pane.py": "x = 0\n"})
        branch.commit({"pane.py": "x = 2\n"})

        conflict_markers.assert_no_commit_holds_a_leftover(branch.path, since="main")

    def test_a_folder_that_is_no_repository_has_no_commits_to_judge(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))

        conflict_markers.assert_no_commit_holds_a_leftover(tmp_path, since="main")

    def test_a_repository_without_the_main_it_is_judged_against_is_refused(self, branch_from):
        branch = branch_from({"pane.py": "x = 0\n"})

        with pytest.raises(AssertionError, match="origin/main"):
            conflict_markers.assert_no_commit_holds_a_leftover(branch.path)


class TestTheCommitBeingMade:
    def test_a_staged_leftover_is_named_as_the_commit_being_made(self, branch_from):
        branch = branch_from({"pane.py": "x = 0\n"})
        branch.track({"pane.py": A_CONFLICT, "notes.md": "A heading\n" + BETWEEN})

        found = conflict_markers.in_staged(branch.path)

        assert found == [Leftover(conflict_markers.STAGED, "pane.py", OURS.strip()),
                         Leftover(conflict_markers.STAGED, "pane.py", THEIRS.strip())]
        assert f"the commit being made: pane.py: {OURS.strip()}" in conflict_markers.told_of(branch.path, found)

    def test_the_pre_commit_hook_is_refused_naming_the_leftover(self, branch_from, capsys, monkeypatch):
        branch = branch_from({"pane.py": "x = 0\n"})
        branch.track({"pane.py": A_CONFLICT})
        monkeypatch.chdir(branch.path)

        assert conflict_markers.refuse_a_staged_leftover(["--staged"]) == 1
        assert f"the commit being made: pane.py: {THEIRS.strip()}" in capsys.readouterr().err

    def test_the_commit_message_hook_leaves_the_staged_files_to_the_pre_commit_one(self, branch_from, monkeypatch):
        branch = branch_from({"pane.py": "x = 0\n"})
        branch.track({"pane.py": A_CONFLICT})
        monkeypatch.chdir(branch.path)

        assert conflict_markers.refuse_a_staged_leftover(["--message", "COMMIT_EDITMSG"]) == 0

    def test_a_commit_holding_none_goes_ahead(self, branch_from, monkeypatch):
        branch = branch_from({"pane.py": "x = 0\n"})
        branch.track({"pane.py": "x = 2\n"})
        monkeypatch.chdir(branch.path)

        assert conflict_markers.refuse_a_staged_leftover(["--staged"]) == 0


class TestTheCommandLine:
    def test_it_judges_the_commits_since_the_main_it_is_given(self, branch_from, capsys, monkeypatch):
        branch = branch_from({"pane.py": "x = 0\n"})
        branch.commit({"pane.py": A_CONFLICT}, "a pick finished by hand")
        branch.commit({"pane.py": "x = 2\n"})
        monkeypatch.chdir(branch.path)

        assert conflict_markers.main(["--since", "main"]) == 1
        assert "a pick finished by hand: pane.py" in capsys.readouterr().err


class TestTheCommitsABranchAdds:
    def test_a_marker_one_commit_adds_and_the_next_takes_out_is_still_found(self, branch_from):
        branch = branch_from({"pane.py": "x = 0\n"})
        branch.commit({"pane.py": A_CONFLICT})
        left_in = _sha(branch)
        branch.commit({"pane.py": "x = 2\n"})

        assert conflict_markers.in_commits(branch.path, since="main") == [
            Leftover(left_in, "pane.py", OURS.strip()), Leftover(left_in, "pane.py", THEIRS.strip())]

    def test_a_file_its_attributes_call_a_conflict_fixture_may_carry_markers(self, branch_from):
        branch = branch_from({".gitattributes": "tests/fixtures/* conflict-marker-fixture\n"})
        branch.commit({"tests/fixtures/merge.txt": A_CONFLICT})

        assert conflict_markers.in_commits(branch.path, since="main") == []

    def test_a_line_that_only_looks_like_a_marker_is_none(self, branch_from):
        branch = branch_from({"notes.md": "notes\n"})
        branch.commit({"notes.md": "A heading\n" + BETWEEN + f'quoted = "{OURS.strip()}"\n' + "<" * 8 + " eight\n"})

        assert conflict_markers.in_commits(branch.path, since="main") == []

    def test_an_added_line_that_begins_with_two_pluses_is_not_read_as_a_files_name(self, branch_from):
        branch = branch_from({"notes.txt": "notes\n"})
        branch.commit({"notes.txt": "++ two pluses\n" + A_CONFLICT})

        assert {leftover.path for leftover in conflict_markers.in_commits(branch.path, since="main")} == {"notes.txt"}

    def test_a_merge_is_judged_by_what_it_adds_to_its_first_parent(self, branch_from):
        branch = branch_from({"pane.py": "x = 0\n"})
        branch.git("checkout", "-q", "-b", "side")
        branch.commit({"other.py": "y = 0\n"})
        branch.git("checkout", "-q", "branch")
        branch.commit({"third.py": "z = 0\n"})
        branch.git("merge", "-q", "--no-commit", "side")
        branch.commit({"pane.py": A_CONFLICT}, "a merge left unfinished")

        assert [leftover.commit for leftover in conflict_markers.in_commits(branch.path, since="main")] == [
            _sha(branch), _sha(branch)]
