from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from production_machine import git

from app_support import haglio_settings
from app_support.sanitize import (
    ListUnreadable,
    blocklist_path,
    find_violations,
    load_blocklist,
    scan_files,
    the_computers_terms,
)
from app_support.sanitize.guard import Violation, _fold, _matcher, build_parser, main


class TestFold:
    def test_it_never_parts_two_characters_ignorecase_matches_as_one(self):
        cased = [ch for ch in map(chr, range(sys.maxunicode + 1))
                 if ch.lower() != ch or ch.upper() != ch or ch.casefold() != ch]
        images = "".join(ch.lower() + ch.upper() + ch.casefold() for ch in cased)
        alphabet = "".join(sorted({*cased, *images}))

        parted = [(x, match.group()) for x in alphabet
                  for match in re.finditer(re.escape(x), alphabet, re.IGNORECASE)
                  if _fold(match.group()) != _fold(x)]

        assert parted == []


class TestViolation:
    def test_its_repr_which_pytest_prints_on_a_failure_names_the_place_not_the_term(self):
        shown = repr(Violation("notes.md", 3, "forbiddenterm", "has *** in it"))

        assert "forbiddenterm" not in shown
        assert "notes.md" in shown
        assert "3" in shown


class TestFindViolations:
    def test_flags_a_banned_single_word(self):
        found = find_violations("this has forbiddenterm in it", ["forbiddenterm"])
        assert [(v.term, v.line) for v in found] == [("forbiddenterm", 1)]

    def test_is_case_insensitive(self):
        assert find_violations("FORBIDDENTERM", ["forbiddenterm"])

    def test_a_letter_ignorecase_reads_as_the_plain_one_still_matches_it(self):
        for spelled in ("m\u0131\u017fplacedterm", "MİSPLACEDTERM"):
            assert find_violations(f"the {spelled} here", ["misplacedterm"]), spelled

    def test_the_right_boundary_refuses_a_term_starting_a_longer_word(self):
        assert find_violations("a catalog here", ["cat"]) == []

    def test_the_left_boundary_refuses_a_term_ending_a_longer_word(self):
        assert find_violations("a bobcat here", ["cat"]) == []

    def test_matches_a_multi_word_term_across_flexible_whitespace(self):
        assert find_violations("a two   word phrase", ["two word"])

    def test_matches_a_term_a_line_wrap_has_split(self):
        found = find_violations("a title like *two\n    word* would match", ["two word"])
        assert [v.line for v in found] == [1]

    def test_a_line_number_still_points_at_the_right_line(self):
        found = find_violations("clean\nclean\nhas badterm\nclean", ["badterm"])
        assert [v.line for v in found] == [3]

    def test_violations_come_back_sorted_by_line_since_only_the_first_twenty_are_shown(self):
        found = find_violations("has beta\nclean\nhas alpha\n", ["alpha", "beta"])

        assert [(v.line, v.term) for v in found] == [(1, "beta"), (3, "alpha")]

    def test_matches_a_multi_word_term_joined_the_way_a_filename_joins_it(self):
        for slug in ("two-word", "two_word", "two.word", "twoword"):
            assert find_violations(f"item-{slug}-part-a.dat", ["two word"]), slug

    def test_matches_an_inflected_form(self):
        for form in ("badterms", "badterm's", "badtermed", "badterming"):
            assert find_violations(f"the {form} here", ["badterm"]), form

    def test_a_sibilants_plural_takes_es_which_a_bare_s_cannot_reach(self):
        assert find_violations("all the foxes here", ["fox"])

    def test_an_entry_written_in_the_plural_matches_its_own_stem(self):
        assert find_violations("one badterm here", ["badterms"])
        assert find_violations("the badterms here", ["badterms"])
        assert find_violations("one fox here", ["foxes"])
        assert find_violations("a bad phrase here", ["bad phrases"])

    def test_a_word_that_merely_ends_in_s_is_not_stemmed(self):
        assert find_violations("a glas of water", ["glass"]) == []
        assert find_violations("the bu stop", ["bus"]) == []
        assert find_violations("thi one", ["this"]) == []
        assert find_violations("a ga leak", ["gas"]) == []

    def test_widening_still_refuses_an_unrelated_longer_word(self):
        assert find_violations("a concatenated list", ["cat"]) == []
        assert find_violations("scatter the words", ["cat"]) == []
        assert find_violations("a category error", ["cat"]) == []

    def test_punctuated_term_matches_literally(self):
        assert find_violations("go to site.example now", ["site.example"])
        assert find_violations("go to siteXexample now", ["site.example"]) == []
        assert find_violations("the (parenthesised) name", ["(parenthesised)"])

    def test_reports_the_line_number(self):
        found = find_violations("clean\nclean\nbadterm here", ["badterm"])
        assert [v.line for v in found] == [3]

    def test_each_term_on_a_line_is_reported(self):
        found = find_violations("alpha and beta together", ["alpha", "beta"])
        assert {v.term for v in found} == {"alpha", "beta"}

    def test_excerpt_redacts_every_matched_term(self):
        found = find_violations("keep alpha drop beta", ["alpha", "beta"])
        assert all("alpha" not in v.excerpt and "beta" not in v.excerpt for v in found)
        assert all("***" in v.excerpt for v in found)

    def test_clean_text_has_no_violations(self):
        assert find_violations("perfectly clean text", ["badterm", "two word"]) == []


class TestLoadBlocklist:
    def test_reads_terms_skipping_blanks_and_comments(self, tmp_path: Path):
        f = tmp_path / "bl.txt"
        f.write_text("# a comment\nalpha\n\n  beta gamma  \n", encoding="utf-8")
        assert load_blocklist(f) == ["alpha", "beta gamma"]


class TestScanFiles:
    def test_collects_violations_with_paths_relative_to_root(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("has badterm", encoding="utf-8")
        (tmp_path / "b.txt").write_text("clean", encoding="utf-8")
        found = scan_files([tmp_path / "a.txt", tmp_path / "b.txt"], ["badterm"], root=tmp_path)
        assert [(v.path, v.term) for v in found] == [("a.txt", "badterm")]

    def test_skips_binary_contents_leaving_media_to_gitignore(self, tmp_path: Path):
        (tmp_path / "img.bin").write_bytes(b"\x00\xff\xfe badterm \x00")
        assert scan_files([tmp_path / "img.bin"], ["badterm"], root=tmp_path) == []

    def test_a_file_that_refuses_to_open_is_reported_rather_than_skipped(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        locked = tmp_path / "locked.md"
        locked.write_text("clean", encoding="utf-8")
        opened = Path.open

        def refuse_the_locked_file(path, *args, **kwargs):
            if path == locked:
                raise PermissionError(13, "Permission denied", str(path))
            return opened(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", refuse_the_locked_file)

        found = scan_files([locked], ["badterm"], root=tmp_path)

        assert [(v.path, v.line) for v in found] == [("locked.md", 0)]
        assert "could not be read" in found[0].excerpt

    def test_a_file_gone_from_disk_is_judged_by_its_name_alone(self, tmp_path: Path):
        found = scan_files([tmp_path / "badterm-gone.md"], ["badterm"], root=tmp_path)

        assert [(v.line, v.excerpt) for v in found] == [(0, "(in the file's name)")]

    def test_a_terms_matcher_is_built_once_so_a_large_tree_stays_under_its_time_limit(
            self, tmp_path: Path):
        for name in ("a.txt", "b.txt", "c.txt"):
            (tmp_path / name).write_text("clean", encoding="utf-8")
        built = _matcher.cache_info().misses

        scan_files(sorted(tmp_path.iterdir()), ["badterm", "other term"], root=tmp_path)

        assert _matcher.cache_info().misses - built <= 2

    def test_a_term_no_file_carries_is_never_matched_against_them(self, tmp_path: Path):
        for name in ("a.txt", "b.txt"):
            (tmp_path / name).write_text("perfectly clean\n", encoding="utf-8")
        ran: list[str] = []

        def note_each_pattern_run(_frame, event, arg):
            if event == "c_call" and isinstance(getattr(arg, "__self__", None), re.Pattern):
                ran.append(arg.__self__.pattern)

        before = sys.getprofile()
        sys.setprofile(note_each_pattern_run)
        try:
            scan_files(sorted(tmp_path.iterdir()), ["absentterm"], root=tmp_path)
        finally:
            sys.setprofile(before)

        assert [pattern for pattern in ran if "absentterm" in pattern] == []

    def test_flags_a_file_named_after_a_term(self, tmp_path: Path):
        (tmp_path / "badterm-notes.md").write_text("clean", encoding="utf-8")
        (tmp_path / "play_badterm.bin").write_bytes(b"\x00\xff\xfe")
        found = scan_files(
            [tmp_path / "badterm-notes.md", tmp_path / "play_badterm.bin"],
            ["badterm"], root=tmp_path)
        assert [(v.path, v.line, v.term) for v in found] == [
            ("*** notes md", 0, "badterm"), ("play *** bin", 0, "badterm")]
        assert all("badterm" not in repr(v) for v in found)


class TestWhereTheOneListIs:
    def test_it_is_in_the_library_the_computers_haglio_settings_name_so_every_computer_reads_one_copy(
            self, computer):
        library = computer.name_its_library()

        assert blocklist_path() == library / "app_data" / "sanitize" / "blocklist.txt"

    def test_a_computer_with_no_haglio_settings_like_a_public_clone_or_ci_has_none(self, computer):
        assert blocklist_path() is None

    def test_a_suite_pointing_the_apps_at_made_up_settings_still_reads_the_computers_own_list(
            self, computer, tmp_path, monkeypatch):
        library = computer.name_its_library()
        made_up = tmp_path / "made_up.json"
        made_up.write_text('{"library_root": "D:/made-up"}', encoding="utf-8")
        monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(made_up))

        assert blocklist_path() == library / "app_data" / "sanitize" / "blocklist.txt"

    def test_settings_that_name_no_library_are_refused_rather_than_read_as_no_list(self, computer):
        computer.name_its_library({"microphone": "Example microphone"})

        with pytest.raises(haglio_settings.MissingSetting):
            blocklist_path()


class TestTheComputersTerms:
    def test_a_computer_with_no_haglio_settings_keeps_no_list(self, computer):
        assert the_computers_terms() is None

    def test_the_terms_come_from_the_one_list_in_the_library(self, computer):
        computer.arm("# a comment\nalpha\n\nbeta gamma\n")

        assert the_computers_terms() == ["alpha", "beta gamma"]

    def test_a_list_the_settings_point_at_but_that_is_not_there_is_refused(self, computer):
        computer.name_its_library()

        with pytest.raises(ListUnreadable, match="cannot be read"):
            the_computers_terms()

    def test_a_list_holding_no_words_is_refused(self, computer):
        computer.arm("# only a comment\n")

        with pytest.raises(ListUnreadable, match="holds no words"):
            the_computers_terms()

    def test_settings_that_name_no_library_are_refused(self, computer):
        computer.name_its_library({"microphone": "Example microphone"})

        with pytest.raises(ListUnreadable, match="library_root"):
            the_computers_terms()

    def test_settings_that_are_not_json_are_refused(self, computer):
        (computer.home / ".haglio").mkdir()
        (computer.home / ".haglio" / "settings.json").write_text("{not json", encoding="utf-8")

        with pytest.raises(ListUnreadable, match="do not say where the library is"):
            the_computers_terms()


class TestTheHooksMakeGitRefuseTheCommit:
    TERM = "nonceterm"

    @pytest.fixture(autouse=True)
    def _on_a_computer_of_its_own(self, computer):
        self.computer = computer

    def _repo(self, tmp_path: Path, terms: str | None) -> Path:
        repo = tmp_path / "family" / "repo"
        repo.mkdir(parents=True)
        if terms is not None:
            self.computer.arm(terms)
        here = Path(__file__).resolve().parent.parent
        for rel in ("tools/githooks/pre-commit", "tools/githooks/commit-msg"):
            dest = repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((here / rel).read_bytes())
            # Copying a file does not copy its mode, and git skips a hook it
            # cannot execute — with a warning, and a commit that succeeds. Off
            # Windows that silently turned every case below into a test of
            # nothing.
            dest.chmod(0o755)
        git("init", "-b", "main", cwd=repo)
        git("config", "user.email", "guard@example.test", cwd=repo)
        git("config", "user.name", "Guard Test", cwd=repo)
        git("config", "core.hooksPath", "tools/githooks", cwd=repo)
        return repo

    def _commit(self, repo: Path, message: str = "seed", *, guard_on_path: Path | None = None):
        return subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", message],
            capture_output=True, text=True, env=self._the_guard_for_a_repo_with_no_venv(guard_on_path),
            check=False,
        )

    @staticmethod
    def _the_guard_for_a_repo_with_no_venv(guard_on_path: Path | None) -> dict[str, str]:
        here = Path(__file__).resolve().parents[1]
        return {**os.environ, "PYTHONPATH": str(guard_on_path or here)}

    def test_the_hook_refuses_a_banned_term_while_still_staged_before_the_suite_could_meet_it_as_a_commit(
            self, tmp_path: Path):
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        (repo / "notes.md").write_text(f"this has {self.TERM} in it\n", encoding="utf-8")
        git("add", ".", cwd=repo)
        done = self._commit(repo)
        assert done.returncode != 0
        assert "blocked term" in done.stderr
        assert self.TERM not in done.stderr

    def test_the_hook_refuses_a_file_named_after_a_term(self, tmp_path: Path):
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        (repo / f"play_{self.TERM}.bat").write_text("clean\n", encoding="utf-8")
        git("add", ".", cwd=repo)
        done = self._commit(repo)
        assert done.returncode != 0
        assert self.TERM not in done.stderr

    def test_the_hook_refuses_a_banned_term_in_the_message(self, tmp_path: Path):
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        (repo / "notes.md").write_text("clean\n", encoding="utf-8")
        git("add", ".", cwd=repo)
        assert self._commit(repo, f"drop the {self.TERM} fixture").returncode != 0

    def test_it_judges_the_staged_half_not_the_working_copy(self, tmp_path: Path):
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        f = repo / "notes.md"
        f.write_text("clean\n", encoding="utf-8")
        git("add", ".", cwd=repo)
        f.write_text(f"now with {self.TERM}\n", encoding="utf-8")
        assert self._commit(repo).returncode == 0

    def test_a_clean_commit_passes(self, tmp_path: Path):
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        (repo / "notes.md").write_text("perfectly clean\n", encoding="utf-8")
        git("add", ".", cwd=repo)
        assert self._commit(repo).returncode == 0

    @pytest.mark.parametrize("terms", [f"{TERM}\n", None], ids=["armed", "with-no-blocklist"])
    def test_the_hook_refuses_a_commit_that_stages_a_merge_conflicts_markers(self, tmp_path: Path, terms):
        repo = self._repo(tmp_path, terms)
        (repo / "pane.py").write_text("<" * 7 + " HEAD\nx = 1\n" + "=" * 7 + "\nx = 2\n" + ">" * 7 + " abc\n",
                                      encoding="utf-8")
        git("add", "pane.py", cwd=repo)
        done = self._commit(repo)
        assert done.returncode != 0
        assert "pane.py: " + "<" * 7 + " HEAD" in done.stderr

    def test_no_blocklist_means_no_enforcement_said_aloud_as_the_only_sign_it_is_missing(self, tmp_path: Path):
        repo = self._repo(tmp_path, None)
        (repo / "notes.md").write_text(f"this has {self.TERM} in it\n", encoding="utf-8")
        git("add", ".", cwd=repo)
        done = self._commit(repo)
        assert done.returncode == 0
        assert "no blocklist" in done.stderr

    def test_a_computer_whose_one_list_cannot_be_read_refuses_the_commit_rather_than_let_any_word_through(
            self, tmp_path: Path):
        repo = self._repo(tmp_path, None)
        list_it_should_read = self.computer.name_its_library() / "app_data" / "sanitize" / "blocklist.txt"
        (repo / "notes.md").write_text("perfectly clean\n", encoding="utf-8")
        git("add", ".", cwd=repo)

        done = self._commit(repo)

        assert done.returncode != 0
        assert str(list_it_should_read) in done.stderr
        assert "pCloud" in done.stderr

    def test_an_empty_list_is_refused_since_a_half_synced_file_reads_as_one(self, tmp_path: Path):
        repo = self._repo(tmp_path, "# nothing but a comment\n")
        (repo / "notes.md").write_text("perfectly clean\n", encoding="utf-8")
        git("add", ".", cwd=repo)

        done = self._commit(repo)

        assert done.returncode != 0
        assert "holds no words" in done.stderr

    def test_settings_that_name_no_library_refuse_the_commit(self, tmp_path: Path):
        repo = self._repo(tmp_path, None)
        self.computer.name_its_library({"microphone": "Example microphone"})
        (repo / "notes.md").write_text("perfectly clean\n", encoding="utf-8")
        git("add", ".", cwd=repo)

        done = self._commit(repo)

        assert done.returncode != 0
        assert "library_root" in done.stderr

    def _shadow_app_support_so_the_import_fails_everywhere(self, tmp_path: Path) -> Path:
        shadow = tmp_path / "shadow"
        shadow.mkdir()
        (shadow / "app_support.py").write_text("", encoding="utf-8")
        return shadow

    def _only_this_hook_so_the_other_cannot_answer_for_it(self, repo: Path, hook_name: str) -> None:
        alone = repo / "tools" / f"githooks-{hook_name}-only"
        alone.mkdir()
        hook = alone / hook_name
        hook.write_bytes((repo / "tools" / "githooks" / hook_name).read_bytes())
        hook.chmod(0o755)
        git("config", "core.hooksPath", str(alone.relative_to(repo)), cwd=repo)

    def test_a_guard_it_cannot_import_refuses_the_commit(self, tmp_path: Path):
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        (repo / "notes.md").write_text("perfectly clean\n", encoding="utf-8")
        git("add", ".", cwd=repo)
        self._only_this_hook_so_the_other_cannot_answer_for_it(repo, "pre-commit")

        done = self._commit(repo, guard_on_path=self._shadow_app_support_so_the_import_fails_everywhere(tmp_path))

        assert done.returncode != 0
        assert "app_support" in done.stderr

    def test_a_guard_it_cannot_import_refuses_the_message_too(self, tmp_path: Path):
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        (repo / "notes.md").write_text("perfectly clean\n", encoding="utf-8")
        git("add", ".", cwd=repo)
        self._only_this_hook_so_the_other_cannot_answer_for_it(repo, "commit-msg")

        done = self._commit(repo, guard_on_path=self._shadow_app_support_so_the_import_fails_everywhere(tmp_path))

        assert done.returncode != 0
        assert "app_support" in done.stderr


class TestTheFlagsTheHookPasses:
    def test_a_message_with_no_file_is_a_usage_error_not_a_traceback(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--message"])

    def test_each_mode_parses_on_its_own(self):
        assert build_parser().parse_args(["--staged"]).staged is True
        assert build_parser().parse_args(["--message", "MSG"]).message == "MSG"

    def test_the_two_modes_are_exclusive(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--staged", "--message", "MSG"])

    def test_a_misspelled_flag_is_refused_rather_than_read_as_the_other_mode(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--staged-changes"])

    def test_main_refuses_the_malformed_call_before_it_looks_for_a_blocklist(self):
        with pytest.raises(SystemExit):
            main(["--message"])
