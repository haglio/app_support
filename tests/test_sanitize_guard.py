from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from production_machine import git

from app_support.sanitize import (
    blocklist_path,
    find_violations,
    load_blocklist,
    scan_files,
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
    def test_its_repr_names_the_place_and_not_the_term(self):
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
        for spelled in ("mıſplacedterm", "MİSPLACEDTERM"):
            assert find_violations(f"the {spelled} here", ["misplacedterm"]), spelled

    def test_word_boundary_prevents_substring_false_positive(self):
        assert find_violations("a concatenated list", ["cat"]) == []
        assert find_violations("a bobcat here", ["cat"]) == []

    def test_matches_a_multi_word_term_across_flexible_whitespace(self):
        assert find_violations("a two   word phrase", ["two word"])

    def test_matches_a_term_a_line_wrap_has_split(self):
        found = find_violations("a title like *two\n    word* would match", ["two word"])
        assert [v.line for v in found] == [1]

    def test_a_line_number_still_points_at_the_right_line(self):
        found = find_violations("clean\nclean\nhas badterm\nclean", ["badterm"])
        assert [v.line for v in found] == [3]

    def test_violations_come_back_sorted_by_line_not_grouped_by_term(self):
        found = find_violations("has beta\nclean\nhas alpha\n", ["alpha", "beta"])

        assert [(v.line, v.term) for v in found] == [(1, "beta"), (3, "alpha")]

    def test_matches_a_multi_word_term_joined_the_way_a_filename_joins_it(self):
        for slug in ("two-word", "two_word", "two.word", "twoword"):
            assert find_violations(f"item-{slug}-part-a.dat", ["two word"]), slug

    def test_matches_an_inflected_form(self):
        for form in ("badterms", "badterm's", "badtermed", "badterming"):
            assert find_violations(f"the {form} here", ["badterm"]), form
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

    def test_skips_undecodable_binary_files(self, tmp_path: Path):
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

    def test_a_terms_matcher_is_built_once_however_many_files_are_scanned(
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


def _arm(repo: Path, terms: str) -> Path:
    path = blocklist_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(terms, encoding="utf-8")
    return path


def _checkout(family: Path, name: str) -> Path:
    repo = family / name
    repo.mkdir(parents=True)
    git("init", "-b", "main", cwd=repo)
    git("config", "user.email", "guard@example.test", cwd=repo)
    git("config", "user.name", "Guard Test", cwd=repo)
    return repo


class TestBlocklistPath:
    def test_reads_the_one_list_beside_the_checkouts(self, tmp_path: Path):
        family = tmp_path / "family"
        repo = _checkout(family, "repo")
        shared = family / ".sanitize" / "blocklist.txt"
        shared.parent.mkdir()
        shared.write_text("alpha\n", encoding="utf-8")
        assert blocklist_path(repo) == shared.resolve()

    def test_ignores_a_copy_left_inside_a_checkout(self, tmp_path: Path):
        family = tmp_path / "family"
        repo = _checkout(family, "repo")
        (repo / ".sanitize").mkdir()
        (repo / ".sanitize" / "blocklist.txt").write_text("stale\n", encoding="utf-8")
        assert blocklist_path(repo).parent.parent == family.resolve()

    def test_finds_it_from_a_worktree_too(self, tmp_path: Path):
        family = tmp_path / "family"
        primary = _checkout(family, "repo")
        shared = family / ".sanitize" / "blocklist.txt"
        shared.parent.mkdir()
        shared.write_text("alpha\n", encoding="utf-8")
        (primary / "README.md").write_text("hi\n", encoding="utf-8")
        git("add", "README.md", cwd=primary)
        git("commit", "-m", "seed", cwd=primary)

        tree = primary / ".claude" / "worktrees" / "side"
        git("worktree", "add", str(tree), "-b", "side", cwd=primary)
        assert blocklist_path(tree) == shared.resolve()

    def test_a_machine_with_no_blocklist_still_names_where_one_would_go(self, tmp_path: Path):
        clone = tmp_path / "clone"
        clone.mkdir()
        git("init", "-b", "main", cwd=clone)
        assert not blocklist_path(clone).exists()


class TestHookEntryPoint:
    TERM = "nonceterm"

    def _repo(self, tmp_path: Path, terms: str | None) -> Path:
        repo = tmp_path / "family" / "repo"
        repo.mkdir(parents=True)
        if terms is not None:
            _arm(repo, terms)
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

    def _commit(self, repo: Path, message: str = "seed", *, pythonpath: Path | None = None):
        here = Path(__file__).resolve().parents[1]
        env = {**os.environ, "PYTHONPATH": str(pythonpath or here)}
        return subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", message],
            capture_output=True, text=True, env=env, check=False,
        )

    def test_the_hook_refuses_a_staged_banned_term(self, tmp_path: Path):
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

    def test_no_blocklist_means_no_enforcement(self, tmp_path: Path):
        repo = self._repo(tmp_path, None)
        (repo / "notes.md").write_text(f"this has {self.TERM} in it\n", encoding="utf-8")
        git("add", ".", cwd=repo)
        done = self._commit(repo)
        assert done.returncode == 0
        assert "no blocklist" in done.stderr

    def _shadow(self, tmp_path: Path) -> Path:
        shadow = tmp_path / "shadow"
        shadow.mkdir()
        (shadow / "app_support.py").write_text("", encoding="utf-8")
        return shadow

    def _only(self, repo: Path, hook_name: str) -> None:
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
        self._only(repo, "pre-commit")

        done = self._commit(repo, pythonpath=self._shadow(tmp_path))

        assert done.returncode != 0
        assert "app_support" in done.stderr

    def test_a_guard_it_cannot_import_refuses_the_message_too(self, tmp_path: Path):
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        (repo / "notes.md").write_text("perfectly clean\n", encoding="utf-8")
        git("add", ".", cwd=repo)
        self._only(repo, "commit-msg")

        done = self._commit(repo, pythonpath=self._shadow(tmp_path))

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
