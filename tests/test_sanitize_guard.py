"""Tests for the pre-publication content guard.

Every "banned" term here is an invented placeholder — the guard's real
blocklist lives outside every repository, and these tests must themselves stay
publishable.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app_support.sanitize import (
    blocklist_path,
    find_violations,
    load_blocklist,
    scan_files,
)
from app_support.sanitize.guard import Violation


class TestViolation:
    def test_its_repr_names_the_place_and_not_the_term(self):
        """A failing tracked-tree check reprints every violation through
        pytest's assertion introspection -- once in the terminal, twice in a
        retained junit artifact -- and the dataclass repr carried the term,
        the one thing the guard exists to keep out of both (bug 82)."""
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

    def test_word_boundary_prevents_substring_false_positive(self):
        assert find_violations("a concatenated list", ["cat"]) == []
        # A term at the *end* of a longer word, which only the left-hand
        # boundary refuses -- every other case here is caught by the right one,
        # so without this the left guard could be deleted and nothing would say.
        assert find_violations("a bobcat here", ["cat"]) == []

    def test_matches_a_multi_word_term_across_flexible_whitespace(self):
        assert find_violations("a two   word phrase", ["two word"])

    def test_matches_a_term_a_line_wrap_has_split(self):
        """A per-line scan cannot see this. A real title hid behind a docstring's
        line break through every scan, and only surfaced when a history rewrite
        matched on the whole blob and put it back together.
        """
        found = find_violations("a title like *two\n    word* would match", ["two word"])
        assert [v.line for v in found] == [1]  # reported where the match starts

    def test_a_line_number_still_points_at_the_right_line(self):
        found = find_violations("clean\nclean\nhas badterm\nclean", ["badterm"])
        assert [v.line for v in found] == [3]

    def test_violations_come_back_in_the_order_a_reader_would_want_them(self):
        """Matching runs term by term, so the raw order is grouped by term and
        scattered by line. Only the first twenty are ever reported, so an
        unsorted list would show a reader whichever twenty happened to match
        first rather than the ones at the top of the file.
        """
        found = find_violations("has beta\nclean\nhas alpha\n", ["alpha", "beta"])

        assert [(v.line, v.term) for v in found] == [(1, "beta"), (3, "alpha")]

    def test_matches_a_multi_word_term_joined_the_way_a_filename_joins_it(self):
        """The list is written in prose; the leak arrives as a filename. Real
        names sat on a public `main` in exactly these shapes, unflagged, because
        the matcher allowed only whitespace between a term's words.
        """
        for slug in ("two-word", "two_word", "two.word", "twoword"):
            assert find_violations(f"item-{slug}-part-a.dat", ["two word"]), slug

    def test_matches_an_inflected_form(self):
        """`badterm` on the list did not catch `badterms` in prose: the trailing
        word boundary refused the plural.
        """
        for form in ("badterms", "badterm's", "badtermed", "badterming"):
            assert find_violations(f"the {form} here", ["badterm"]), form
        # `es` is its own branch: the bare `s` alternative cannot reach a
        # sibilant's plural, so without it `foxes` walks past `fox`.
        assert find_violations("all the foxes here", ["fox"])

    def test_an_entry_written_in_the_plural_matches_its_own_stem(self):
        """`badterms` on the list matched `badterms` and let `badterm` through:
        the inflection slack ran only one way, and a list is full of plurals
        (bug 80).  The plural's stem is what the entry names.
        """
        assert find_violations("one badterm here", ["badterms"])
        assert find_violations("the badterms here", ["badterms"])
        assert find_violations("one fox here", ["foxes"])
        assert find_violations("a bad phrase here", ["bad phrases"])

    def test_a_word_that_merely_ends_in_s_is_not_stemmed(self):
        """`glass` names glass, not `glas`; `bus`, `this` and a three-letter
        word are left as written, so the stem never decays into a substring
        that fires on something else."""
        assert find_violations("a glas of water", ["glass"]) == []
        assert find_violations("the bu stop", ["bus"]) == []
        assert find_violations("thi one", ["this"]) == []
        assert find_violations("a ga leak", ["gas"]) == []

    def test_widening_still_refuses_an_unrelated_longer_word(self):
        """Separator and inflection slack must not decay into a substring match:
        `cat` may reach `cat-s`, never `concatenated`.
        """
        assert find_violations("a concatenated list", ["cat"]) == []
        assert find_violations("scatter the words", ["cat"]) == []
        assert find_violations("a category error", ["cat"]) == []

    def test_punctuated_term_matches_literally(self):
        """Literally, not as a pattern. Without escaping, the `.` in a term is a
        wildcard that fires on text the term does not name, and a term carrying a
        bracket or a paren stops being a term at all -- it raises, and takes
        every commit in the repo down with it.
        """
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

    def test_flags_a_file_named_after_a_term(self, tmp_path: Path):
        """The path was passed through as a label and never scanned, so a file
        NAMED after a term cleared the hook, the tracked-tree check and CI --
        which is how a launcher named after one reached a public main
        (bug 79).  A name hit is reported at line 0 with the name redacted --
        the report would otherwise print the term -- and a binary file's name
        is read even though its contents are not."""
        (tmp_path / "badterm-notes.md").write_text("clean", encoding="utf-8")
        (tmp_path / "play_badterm.bin").write_bytes(b"\x00\xff\xfe")
        found = scan_files(
            [tmp_path / "badterm-notes.md", tmp_path / "play_badterm.bin"],
            ["badterm"], root=tmp_path)
        assert [(v.path, v.line, v.term) for v in found] == [
            ("*** notes md", 0, "badterm"), ("play *** bin", 0, "badterm")]
        assert all("badterm" not in repr(v) for v in found)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _arm(repo: Path, terms: str) -> Path:
    """Put a list where the guard will look for it, by asking the guard.

    Every case below is about what happens once terms resolve, not about where
    they were found, so the layout is stated once — in ``TestBlocklistPath``,
    which pins it against literal paths — and read from here.
    """
    path = blocklist_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(terms, encoding="utf-8")
    return path


def _checkout(family: Path, name: str) -> Path:
    repo = family / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "guard@example.test")
    _git(repo, "config", "user.name", "Guard Test")
    return repo


class TestBlocklistPath:
    """One list for every checkout, so only its resolution keeps the guard alive."""

    def test_reads_the_one_list_beside_the_checkouts(self, tmp_path: Path):
        family = tmp_path / "family"
        repo = _checkout(family, "repo")
        shared = family / ".sanitize" / "blocklist.txt"
        shared.parent.mkdir()
        shared.write_text("alpha\n", encoding="utf-8")
        assert blocklist_path(repo) == shared.resolve()

    def test_ignores_a_copy_left_inside_a_checkout(self, tmp_path: Path):
        """A per-repo copy is not a second place to look — it is the thing the one
        list replaced. Eleven of them drifted apart unseen, and a checkout that
        could still prefer its own would let the twelfth drift back in.
        """
        family = tmp_path / "family"
        repo = _checkout(family, "repo")
        (repo / ".sanitize").mkdir()
        (repo / ".sanitize" / "blocklist.txt").write_text("stale\n", encoding="utf-8")
        assert blocklist_path(repo).parent.parent == family.resolve()

    def test_finds_it_from_a_worktree_too(self, tmp_path: Path):
        """The regression this helper exists for: a worktree sits two levels below
        the family, so resolving from it naively looks in the wrong place entirely
        and leaves the guard toothless wherever the work actually happens.
        """
        family = tmp_path / "family"
        primary = _checkout(family, "repo")
        shared = family / ".sanitize" / "blocklist.txt"
        shared.parent.mkdir()
        shared.write_text("alpha\n", encoding="utf-8")
        (primary / "README.md").write_text("hi\n", encoding="utf-8")
        _git(primary, "add", "README.md")
        _git(primary, "commit", "-m", "seed")

        tree = primary / ".claude" / "worktrees" / "side"
        _git(primary, "worktree", "add", str(tree), "-b", "side")
        assert blocklist_path(tree) == shared.resolve()

    def test_returns_a_missing_path_when_there_is_no_list(self, tmp_path: Path):
        """The public-clone case: a checkout with no family beside it. Absence must
        read as "nothing to enforce" — a returned path that simply does not exist —
        never a crash. Same outcome when git is missing entirely, which the helper
        swallows for the benefit of a source tree with no repo.
        """
        clone = tmp_path / "clone"
        clone.mkdir()
        _git(clone, "init", "-b", "main")
        assert not blocklist_path(clone).exists()


class TestHookEntryPoint:
    """The CLI the git hooks call. Each case builds a throwaway repo and drives
    the real hooks through ``git commit``, because what matters is not that
    ``main()`` returns 1 — it is that git refuses the commit.
    """

    TERM = "nonceterm"  # invented, like every fixture value here

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
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "guard@example.test")
        _git(repo, "config", "user.name", "Guard Test")
        _git(repo, "config", "core.hooksPath", "tools/githooks")
        return repo

    def _commit(self, repo: Path, message: str = "seed", *, pythonpath: Path | None = None):
        # The hook runs whatever interpreter it finds, and this throwaway repo
        # has no venv — so hand it the guard on PYTHONPATH, standing in for the
        # installed package a real checkout's venv carries.
        here = Path(__file__).resolve().parents[1]
        env = {**os.environ, "PYTHONPATH": str(pythonpath or here)}
        return subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", message],
            capture_output=True, text=True, env=env,
        )

    def test_the_hook_refuses_a_staged_banned_term(self, tmp_path: Path):
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        (repo / "notes.md").write_text(f"this has {self.TERM} in it\n", encoding="utf-8")
        _git(repo, "add", ".")
        done = self._commit(repo)
        assert done.returncode != 0
        assert "blocked term" in done.stderr
        assert self.TERM not in done.stderr  # redacted, never echoed back

    def test_the_hook_refuses_a_file_named_after_a_term(self, tmp_path: Path):
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        (repo / f"play_{self.TERM}.bat").write_text("clean\n", encoding="utf-8")
        _git(repo, "add", ".")
        done = self._commit(repo)
        assert done.returncode != 0
        assert self.TERM not in done.stderr

    def test_the_hook_refuses_a_banned_term_in_the_message(self, tmp_path: Path):
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        (repo / "notes.md").write_text("clean\n", encoding="utf-8")
        _git(repo, "add", ".")
        assert self._commit(repo, f"drop the {self.TERM} fixture").returncode != 0

    def test_it_judges_the_staged_half_not_the_working_copy(self, tmp_path: Path):
        """A file staged clean and then dirtied must still commit: the index is
        what becomes the commit, so reading from disk would block the wrong thing.
        """
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        f = repo / "notes.md"
        f.write_text("clean\n", encoding="utf-8")
        _git(repo, "add", ".")
        f.write_text(f"now with {self.TERM}\n", encoding="utf-8")
        assert self._commit(repo).returncode == 0

    def test_a_clean_commit_passes(self, tmp_path: Path):
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        (repo / "notes.md").write_text("perfectly clean\n", encoding="utf-8")
        _git(repo, "add", ".")
        assert self._commit(repo).returncode == 0

    def test_no_blocklist_means_no_enforcement(self, tmp_path: Path):
        """A public clone has no overlay. It must commit normally, not be told
        the guard cannot run -- but it is told, in one line, that nothing was
        enforced: on the machine that keeps the list, that line is the only
        sign the list has gone missing (bug 47).
        """
        repo = self._repo(tmp_path, None)
        (repo / "notes.md").write_text(f"this has {self.TERM} in it\n", encoding="utf-8")
        _git(repo, "add", ".")
        done = self._commit(repo)
        assert done.returncode == 0
        assert "no blocklist" in done.stderr

    def _shadow(self, tmp_path: Path) -> Path:
        """A path entry where ``app_support`` resolves to something that is not
        the guard, so the hook's import fails on any machine and any interpreter.

        Standing in for the case this hook exists to make loud: the package is
        not installed in whatever interpreter the hook found. Faking it beats
        hoping the ambient python happens not to have it.
        """
        shadow = tmp_path / "shadow"
        shadow.mkdir()
        (shadow / "app_support.py").write_text("", encoding="utf-8")
        return shadow

    def _only(self, repo: Path, hook_name: str) -> None:
        """Point the repo at a hooks directory holding just one of the two.

        Both hooks run on a commit and either can refuse it, so a case about one
        of them has to be the only one installed — otherwise the other's refusal
        answers for it, and the hook actually under test could be `exit 0`
        throughout and nothing would say so.
        """
        alone = repo / "tools" / f"githooks-{hook_name}-only"
        alone.mkdir()
        hook = alone / hook_name
        hook.write_bytes((repo / "tools" / "githooks" / hook_name).read_bytes())
        hook.chmod(0o755)
        _git(repo, "config", "core.hooksPath", str(alone.relative_to(repo)))

    def test_a_guard_it_cannot_import_refuses_the_commit(self, tmp_path: Path):
        """The contract the move to an installed package created. A hook that
        exited 0 when the import failed would leave a checkout that has silently
        stopped being guarded looking exactly like one that is — and that is the
        state every leak so far was committed from.
        """
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        (repo / "notes.md").write_text("perfectly clean\n", encoding="utf-8")
        _git(repo, "add", ".")
        self._only(repo, "pre-commit")

        done = self._commit(repo, pythonpath=self._shadow(tmp_path))

        assert done.returncode != 0
        assert "app_support" in done.stderr

    def test_a_guard_it_cannot_import_refuses_the_message_too(self, tmp_path: Path):
        """Both hooks or neither: a commit-msg hook that waved the message
        through would leave the half of the surface terms actually land in.
        """
        repo = self._repo(tmp_path, f"{self.TERM}\n")
        (repo / "notes.md").write_text("perfectly clean\n", encoding="utf-8")
        _git(repo, "add", ".")
        self._only(repo, "commit-msg")

        done = self._commit(repo, pythonpath=self._shadow(tmp_path))

        assert done.returncode != 0
        assert "app_support" in done.stderr


class TestTheFlagsTheHookPasses:
    """This runs inside a git hook, where a usage mistake used to be a
    traceback and a misspelling used to be silently the other mode."""

    def test_a_message_with_no_file_is_a_usage_error_not_a_traceback(self):
        """`args[args.index("--message") + 1]` raised IndexError here."""
        from app_support.sanitize.guard import build_parser

        with pytest.raises(SystemExit):
            build_parser().parse_args(["--message"])

    def test_each_mode_parses_on_its_own(self):
        from app_support.sanitize.guard import build_parser

        assert build_parser().parse_args(["--staged"]).staged is True
        assert build_parser().parse_args(["--message", "MSG"]).message == "MSG"

    def test_the_two_modes_are_exclusive(self):
        """One scan per run: a hook is either pre-commit or commit-msg."""
        from app_support.sanitize.guard import build_parser

        with pytest.raises(SystemExit):
            build_parser().parse_args(["--staged", "--message", "MSG"])

    def test_a_misspelled_flag_is_refused_rather_than_read_as_the_other_mode(self):
        from app_support.sanitize.guard import build_parser

        with pytest.raises(SystemExit):
            build_parser().parse_args(["--staged-changes"])

    def test_main_refuses_the_malformed_call_before_it_looks_for_a_blocklist(self):
        """The parser has to be the first thing `main` does, or the checkout
        that most needs the usage error -- a public clone with no blocklist --
        is the one that exits 0 on it.
        """
        from app_support.sanitize.guard import main

        with pytest.raises(SystemExit):
            main(["--message"])
