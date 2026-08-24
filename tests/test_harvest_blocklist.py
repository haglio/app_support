"""Tests for the blocklist harvester.

Every name here is invented, and so is every word in the vocabulary the tests
hand it. The harvester's whole job is to read the real names off a machine, so a
test that reached for one to look realistic would be writing the exact thing this
tool exists to keep out of the tree.
"""
from __future__ import annotations

from pathlib import Path

import subprocess

import pytest

from app_support.sanitize import harvest as harvest_module
from app_support.sanitize.guard import load_blocklist
from app_support.sanitize.harvest import (
    _stale_hours,
    already_in_code,
    candidates_from,
    harvest,
    hours_since_harvest,
    main as harvest_main,
    merge,
    normalize,
    primary_of,
    read_excluded,
    read_roots,
    read_suffixes,
    siblings_of,
    stamp_path,
)

# The vocabulary a machine keeps in its own sanitize/ files, invented here.
# `EXCLUDED` is the ordinary words a name-shaped run is not worth blocking for;
# `SUFFIXES` names the files whose stems are worth reading at all.
EXCLUDED = frozenset({
    "archive", "inner", "other", "assorted", "done", "part",
    "jane doe", "ada roe", "example studio",
})
SUFFIXES = frozenset({".dat", ".blob"})


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


class TestNormalize:
    def test_lowercases_and_single_spaces_any_separator(self):
        for raw in ("Petra Vance", "Petra-Vance", "Petra_Vance", "Petra.Vance",
                    "  Petra   Vance  ", "PETRA-vance"):
            assert normalize(raw) == "petra vance", raw


class TestCandidatesFrom:
    """What a filename or folder name is worth remembering."""

    def test_takes_the_credit_from_a_name_dash_title_filename(self):
        """The shape these names actually take. Only the credit is wanted -- the
        title trailing it is not a name, and blocking a whole sentence would fail
        innocent commits everywhere.
        """
        got = candidates_from(
            "Petra Vance - Some Long Title 3 (2011) Revised",
            whole_name_counts=False,
            excluded=EXCLUDED,
        )
        assert got == {"petra vance"}

    def test_the_credit_is_read_off_the_dash_not_off_the_first_two_words(self):
        """A name longer than two words is why the leading region is split at
        the dash at all. Without the split the run stops being a name somewhere
        inside the title, and the third word of the credit is lost -- which the
        two-word case cannot show, because its leading pair is the whole credit
        either way.
        """
        got = candidates_from(
            "Ann Lee Kim - Some Long Title",
            whole_name_counts=False,
            excluded=EXCLUDED,
        )
        assert got == {"ann lee", "ann lee kim"}

    def test_finds_a_name_however_the_filename_joins_it(self):
        for stem in ("Petra-Vance-part-a-fine", "Petra_Vance_540-abcd1234",
                     "Petra.Vance.part.b"):
            assert "petra vance" in candidates_from(
                stem, whole_name_counts=False, excluded=EXCLUDED), stem

    def test_a_folder_name_counts_whole(self):
        """A folder at the bottom is named after one person and nothing else.
        This is the case that leaked: a single lowercase word, no capitals to
        spot.
        """
        assert candidates_from(
            "hargrove", whole_name_counts=True, excluded=EXCLUDED) == {"hargrove"}

    def test_a_folder_name_is_not_taken_from_a_filename(self):
        assert candidates_from(
            "hargrove", whole_name_counts=False, excluded=EXCLUDED) == set()

    def test_skips_a_name_the_vocabulary_excludes(self):
        """The structure a tree is filed under, named in the machine's own
        exclusion list. Blocking one of these would fail thousands of innocent
        lines the moment it landed.
        """
        for name in ("other", "2 done", "0 assorted", "3_archive",
                     "1 inner", "archive"):
            assert candidates_from(
                name, whole_name_counts=True, excluded=EXCLUDED) == set(), name

    def test_an_excluded_word_disqualifies_only_the_term_carrying_it(self):
        """Each candidate is judged on its own words, and the leading pair is a
        candidate in its own right -- so a credit trailed by an excluded word
        still yields the credit, while a pair containing one yields nothing.
        """
        assert candidates_from(
            "Inner Vance", whole_name_counts=False, excluded=EXCLUDED) == set()
        assert candidates_from(
            "Petra Vance Archive", whole_name_counts=False, excluded=EXCLUDED,
        ) == {"petra vance"}

    def test_skips_a_lowercase_run_in_a_filename(self):
        """A run has to be capitalised to be read as a name at all; a lowercase
        filename says nothing about who is in it.
        """
        for stem in ("part_two_of_three", "something_fine_and_plain"):
            assert candidates_from(
                stem, whole_name_counts=False, excluded=EXCLUDED) == set(), stem

    def test_skips_the_placeholders_the_fixtures_use(self):
        """Blocking one of these would turn every repo's fixtures red at once,
        so they are named in the exclusion list like any other ordinary word.
        """
        for stem in ("Jane Doe - Part One", "Ada-Roe-1", "Example Studio"):
            assert candidates_from(
                stem, whole_name_counts=False, excluded=EXCLUDED) == set(), stem

    def test_a_lone_short_word_is_not_worth_blocking(self):
        """One short token matches far too much prose to pay for itself."""
        assert candidates_from(
            "tess", whole_name_counts=True, excluded=EXCLUDED) == set()


class TestHarvest:
    def _tree(self, root: Path) -> Path:
        base = root / "archive" / "inner" / "other"
        (base / "hargrove" / "0 assorted").mkdir(parents=True)
        (base / "hargrove" / "0 assorted" / "Petra Vance - A Long Title.dat").touch()
        (base / "hargrove" / "0 assorted" / "Marisol Quint - Notes.txt").touch()
        (base / "Tallis-Brand-part-a.blob").touch()
        return root

    def test_finds_names_in_folder_names_and_file_stems(self, tmp_path: Path):
        found = harvest([self._tree(tmp_path)], excluded=EXCLUDED, suffixes=SUFFIXES)
        assert {"hargrove", "petra vance", "tallis brand"} <= found

    def test_reads_a_name_only_off_the_suffixes_it_was_given(self, tmp_path: Path):
        """The whole reason the suffix list exists. Reading every file's name
        would harvest whatever else is filed there and put ordinary words on a
        list that syncs to every checkout -- so the same name is invisible under
        one suffix list and found under another, and nothing else changes.
        """
        tree = self._tree(tmp_path)

        assert "marisol quint" not in harvest(
            [tree], excluded=EXCLUDED, suffixes=SUFFIXES)
        assert "marisol quint" in harvest(
            [tree], excluded=EXCLUDED, suffixes={*SUFFIXES, ".txt"})

    def test_a_root_that_is_not_there_is_skipped_not_fatal(self, tmp_path: Path):
        assert harvest([tmp_path / "gone", self._tree(tmp_path)],
                       excluded=EXCLUDED, suffixes=SUFFIXES)

    def test_stops_descending_past_the_depth_limit(self, tmp_path: Path):
        deep = tmp_path
        for part in ("a", "b", "c", "d", "e", "f", "g"):
            deep = deep / part
        deep.mkdir(parents=True)
        (deep / "Petra Vance - Deep.dat").touch()
        assert "petra vance" not in harvest(
            [tmp_path], excluded=EXCLUDED, suffixes=SUFFIXES, max_depth=3)

    def test_nothing_harvested_is_ever_an_excluded_term(self, tmp_path: Path):
        found = harvest([self._tree(tmp_path)], excluded=EXCLUDED, suffixes=SUFFIXES)
        assert not (found & EXCLUDED)


class TestAlreadyInCode:
    """The filter that decides whether a harvested term is safe to enforce.

    Without it the harvest is unusable: a folder named after an ordinary word
    fails thousands of innocent lines the moment it lands. Measured against the
    real tree, sixteen candidates collided and they alone accounted for every
    one of 3609 false failures.
    """

    def _repo(self, root: Path, files: dict[str, str]) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        for args in (["init", "-b", "main"], ["config", "user.email", "h@e.test"],
                     ["config", "user.name", "H"], ["add", "."],
                     ["commit", "-m", "seed", "--no-verify"]):
            subprocess.run(["git", "-C", str(root), *args],
                           check=True, capture_output=True)
        return root

    def test_reports_a_candidate_that_ordinary_code_already_uses(self, tmp_path: Path):
        repo = self._repo(tmp_path / "r", {"a.py": "parser.add_argument('--output')\n"})
        assert already_in_code({"output", "petra vance"}, [repo]) == {"output"}

    def test_a_candidate_no_code_uses_survives(self, tmp_path: Path):
        repo = self._repo(tmp_path / "r", {"a.py": "x = 1\n"})
        assert already_in_code({"petra vance"}, [repo]) == set()

    def test_a_collision_in_any_checkout_counts(self, tmp_path: Path):
        clean = self._repo(tmp_path / "clean", {"a.py": "x = 1\n"})
        other = self._repo(tmp_path / "other", {"b.py": "# frames per second\n"})
        assert already_in_code({"frames"}, [clean, other]) == {"frames"}

    def test_untracked_files_do_not_count(self, tmp_path: Path):
        """Only what is published can make a term unsafe to enforce."""
        repo = self._repo(tmp_path / "r", {"a.py": "x = 1\n"})
        (repo / "scratch.py").write_text("output = 2\n", encoding="utf-8")
        assert already_in_code({"output"}, [repo]) == set()

    def test_no_candidates_means_no_work(self, tmp_path: Path):
        assert already_in_code(set(), [tmp_path / "nonexistent"]) == set()


class TestMerge:
    def test_adds_only_what_is_new_and_keeps_the_rest(self):
        merged, added = merge(["zeta", "alpha"], {"alpha", "petra vance"})
        assert added == 1
        assert merged == ["alpha", "petra vance", "zeta"]

    def test_an_existing_term_in_another_spelling_is_not_re_added(self):
        """The file may hold `Petra-Vance` from an earlier hand edit; harvesting
        `petra vance` must not produce a second entry for the same person.
        """
        merged, added = merge(["Petra-Vance"], {"petra vance"})
        assert added == 0
        assert merged == ["Petra-Vance"]


class TestRoots:
    def test_reads_paths_skipping_comments_and_blanks(self, tmp_path: Path):
        (tmp_path / "sanitize").mkdir()
        (tmp_path / "sanitize" / "blocklist.local.txt").write_text("x\n", encoding="utf-8")
        (tmp_path / "sanitize" / "library_roots.local.txt").write_text(
            "# where the tree is\nC:/somewhere/one\n\nC:/somewhere/two\n",
            encoding="utf-8")
        assert read_roots(tmp_path) == [Path("C:/somewhere/one"), Path("C:/somewhere/two")]

    def test_no_roots_file_means_nothing_to_harvest(self, tmp_path: Path):
        (tmp_path / "sanitize").mkdir()
        (tmp_path / "sanitize" / "blocklist.local.txt").write_text("x\n", encoding="utf-8")
        assert read_roots(tmp_path) == []


class TestVocabulary:
    """The words that decide what is worth blocking live on the machine.

    They describe what is filed under the roots, so they belong beside the roots
    and the blocklist -- git-ignored, one set per machine, never committed. A
    published copy would be a description of the very thing being kept out, and
    a copy in this package would make it know a domain it has no business
    knowing.
    """

    def _sanitize(self, tmp_path: Path) -> Path:
        (tmp_path / "sanitize").mkdir()
        (tmp_path / "sanitize" / "blocklist.local.txt").write_text("x\n", encoding="utf-8")
        return tmp_path / "sanitize"

    def test_reads_excluded_terms_skipping_comments_and_blanks(self, tmp_path: Path):
        (self._sanitize(tmp_path) / "harvest_excluded.local.txt").write_text(
            "# ordinary words\narchive\n\n  inner room  \n", encoding="utf-8")
        assert read_excluded(tmp_path) == {"archive", "inner room"}

    def test_an_excluded_term_is_normalised_the_way_a_candidate_is(self, tmp_path: Path):
        """A candidate is compared against this set after normalising, so an
        entry written with capitals or a dash would otherwise never match.
        """
        (self._sanitize(tmp_path) / "harvest_excluded.local.txt").write_text(
            "Inner-Room\n", encoding="utf-8")
        assert read_excluded(tmp_path) == {"inner room"}

    def test_no_excluded_file_is_not_an_empty_list(self, tmp_path: Path):
        """Absent and empty are different answers: an empty exclusion list is a
        deliberate choice, and a missing file is a machine that was never set up.
        Reading the second as the first would put the words the tree is filed
        under onto a blocklist that syncs to every checkout at once.
        """
        self._sanitize(tmp_path)
        assert read_excluded(tmp_path) is None

    def test_reads_the_suffixes_worth_reading_a_name_off(self, tmp_path: Path):
        (self._sanitize(tmp_path) / "harvest_suffixes.local.txt").write_text(
            "# what to read\n.dat\n.BLOB\n", encoding="utf-8")
        assert read_suffixes(tmp_path) == {".dat", ".blob"}

    def test_a_suffix_written_without_its_dot_still_matches(self, tmp_path: Path):
        """`Path.suffix` always carries the dot, so an entry without one would
        silently match nothing -- and the failure would be a harvest that quietly
        reads fewer files, which is exactly the failure nobody notices.
        """
        (self._sanitize(tmp_path) / "harvest_suffixes.local.txt").write_text(
            "dat\n", encoding="utf-8")
        assert read_suffixes(tmp_path) == {".dat"}

    def test_no_suffix_file_is_not_an_empty_list(self, tmp_path: Path):
        self._sanitize(tmp_path)
        assert read_suffixes(tmp_path) is None

    def test_a_run_with_roots_but_no_vocabulary_declines_and_says_which(
        self, tmp_path: Path, monkeypatch, capsys,
    ):
        """Configured roots and no vocabulary is the dangerous shape: there is
        somewhere to walk and nothing to tell the walk which words are ordinary.
        It has to decline, name the files it wants, and leave the list alone --
        the same quiet answer as having no roots at all, because a startup caller
        fires this and never reads it.
        """
        repo = tmp_path / "repo"
        (repo / "sanitize").mkdir(parents=True)
        blocklist = repo / "sanitize" / "blocklist.local.txt"
        blocklist.write_text("kept\n", encoding="utf-8")
        (repo / "sanitize" / "library_roots.local.txt").write_text(
            str(tmp_path / "tree") + "\n", encoding="utf-8")
        _git(repo, "init", "-b", "main")
        monkeypatch.chdir(repo)

        assert harvest_main(["--sync"]) == 0

        printed = capsys.readouterr().out
        assert "harvest_excluded.local.txt" in printed
        assert "harvest_suffixes.local.txt" in printed
        assert blocklist.read_text(encoding="utf-8") == "kept\n"


class TestTheCommandLine:
    """The flags, driven end to end against a real family of checkouts.

    This is the surface something else already depends on: a session start fires
    `--if-stale 12 --detach --sync` and never waits for it, so every one of these
    decisions is silent in production. A run that ignored `--dry-run`, dropped
    `--sync`, walked instead of detaching, wrote into the wrong checkout or
    stamped a run that died partway would look exactly like a run that worked.
    """

    def _family(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        """A primary checkout, one sibling that keeps a blocklist, and a tree."""
        tree = tmp_path / "tree" / "archive"
        (tree / "hargrove").mkdir(parents=True)
        (tree / "hargrove" / "Petra Vance - A Title.dat").touch()

        home, kin = tmp_path / "home", tmp_path / "kin"
        for repo in (home, kin):
            (repo / "sanitize").mkdir(parents=True)
            # Ignored exactly as in the real repos, and the fixture depends on
            # it: a committed blocklist is copied into a worktree, and the
            # worktree then answers with its own instead of the primary's.
            (repo / ".gitignore").write_text(
                "sanitize/*.local.txt\n", encoding="utf-8")
            (repo / "sanitize" / "blocklist.local.txt").write_text(
                "keptterm\n", encoding="utf-8")
            _git(repo, "init", "-b", "main")
            _git(repo, "config", "user.email", "h@e.test")
            _git(repo, "config", "user.name", "H")
            (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "seed", "--no-verify")
        overlay = home / "sanitize"
        (overlay / "library_roots.local.txt").write_text(
            f"{tmp_path / 'tree'}\n", encoding="utf-8")
        (overlay / "harvest_excluded.local.txt").write_text(
            "archive\n", encoding="utf-8")
        (overlay / "harvest_suffixes.local.txt").write_text(".dat\n", encoding="utf-8")
        return home, kin, tmp_path / "tree"

    def _terms(self, repo: Path) -> list[str]:
        return load_blocklist(repo / "sanitize" / "blocklist.local.txt")

    def test_a_plain_run_writes_the_primary_and_stamps_it(
        self, tmp_path: Path, monkeypatch, capsys,
    ):
        home, kin, _ = self._family(tmp_path)
        monkeypatch.chdir(home)

        assert harvest_main([]) == 0

        assert "petra vance" in self._terms(home)
        assert "keptterm" in self._terms(home)  # what was there is kept
        assert self._terms(kin) == ["keptterm"]  # untouched without --sync
        assert stamp_path(home).exists()
        # The file explains itself: it is git-ignored and machine-local, so the
        # header is the only thing that ever tells a reader what it is.
        written = (home / "sanitize" / "blocklist.local.txt").read_text(encoding="utf-8")
        assert written.startswith("#")

    def test_no_roots_configured_is_a_quiet_nothing_to_do(
        self, tmp_path: Path, monkeypatch, capsys,
    ):
        """A checkout that never set the tool up has nothing to walk, and says so
        without failing: a session start fires this and must not be taken down by
        a machine that simply does not harvest.
        """
        home, _kin, _ = self._family(tmp_path)
        (home / "sanitize" / "library_roots.local.txt").unlink()
        monkeypatch.chdir(home)

        assert harvest_main(["--sync"]) == 0

        assert "nothing to harvest" in capsys.readouterr().out
        assert self._terms(home) == ["keptterm"]
        assert not stamp_path(home).exists()

    def test_a_run_from_a_worktree_writes_the_primary_it_belongs_to(
        self, tmp_path: Path, monkeypatch, capsys,
    ):
        """Where all the work happens, and the only case that tells the two
        apart. A worktree has no blocklist of its own -- it is git-ignored, so it
        exists only where it was written -- and writing the merged list into the
        worktree would leave the real one untouched and the harvest invisible.
        """
        home, _kin, _ = self._family(tmp_path)
        tree = home / ".claude" / "worktrees" / "wt"
        tree.parent.mkdir(parents=True)
        _git(home, "worktree", "add", str(tree), "-b", "side")
        monkeypatch.chdir(tree)

        assert harvest_main([]) == 0

        assert "petra vance" in self._terms(home)
        assert not (tree / "sanitize").exists()
        # And it says so by the primary's name. The write lands there either
        # way, since resolving the blocklist already crosses from a worktree to
        # the checkout that holds it -- the report is the only place the two can
        # be told apart, and it is what tells a person which lists were touched.
        assert "written to: home" in capsys.readouterr().out

    def test_sync_writes_every_sibling_that_keeps_a_list(
        self, tmp_path: Path, monkeypatch, capsys,
    ):
        home, kin, _ = self._family(tmp_path)
        monkeypatch.chdir(home)

        assert harvest_main(["--sync"]) == 0

        assert "petra vance" in self._terms(kin)
        assert "keptterm" in self._terms(kin)

    def test_dry_run_reports_the_counts_and_writes_nothing(
        self, tmp_path: Path, monkeypatch, capsys,
    ):
        home, _kin, _ = self._family(tmp_path)
        before = (home / "sanitize" / "blocklist.local.txt").read_bytes()
        monkeypatch.chdir(home)

        assert harvest_main(["--dry-run", "--sync"]) == 0

        assert "2 new" in capsys.readouterr().out
        assert (home / "sanitize" / "blocklist.local.txt").read_bytes() == before
        assert not stamp_path(home).exists()

    def test_a_fresh_stamp_stops_the_run_before_it_walks(
        self, tmp_path: Path, monkeypatch, capsys,
    ):
        home, _kin, _ = self._family(tmp_path)
        stamp_path(home).write_text("", encoding="utf-8")
        monkeypatch.chdir(home)

        assert harvest_main(["--if-stale", "12", "--sync"]) == 0

        assert "nothing to do" in capsys.readouterr().out
        assert self._terms(home) == ["keptterm"]

    def test_an_old_stamp_lets_the_run_through(
        self, tmp_path: Path, monkeypatch, capsys,
    ):
        import os
        import time

        home, _kin, _ = self._family(tmp_path)
        stamp = stamp_path(home)
        stamp.write_text("", encoding="utf-8")
        long_ago = time.time() - 30 * 3600
        os.utime(stamp, (long_ago, long_ago))
        monkeypatch.chdir(home)

        assert harvest_main(["--if-stale", "12"]) == 0

        assert "petra vance" in self._terms(home)

    def test_detach_hands_the_work_over_and_returns_before_walking(
        self, tmp_path: Path, monkeypatch, capsys,
    ):
        """The shape a session start fires: it must return before the walk, or
        the person starting the session waits the best part of a minute for it.
        """
        home, _kin, _ = self._family(tmp_path)
        handed: list[list[str]] = []
        monkeypatch.setattr(harvest_module, "detach", handed.append)
        monkeypatch.chdir(home)

        assert harvest_main(["--if-stale", "12", "--detach", "--sync"]) == 0

        assert handed == [["--if-stale", "12", "--detach", "--sync"]]
        assert self._terms(home) == ["keptterm"]  # the parent walked nothing

    def test_the_detached_child_runs_the_module_and_is_not_told_to_detach_again(
        self, monkeypatch,
    ):
        """A child that kept the flag would hand the work on again, forever."""
        started: list[list[str]] = []
        monkeypatch.setattr(
            harvest_module.subprocess, "Popen",
            lambda command, **kwargs: started.append(list(command)))

        harvest_module.detach(["--if-stale", "12", "--detach", "--sync"])

        assert len(started) == 1, started
        assert started[0][1:] == [
            "-m", "app_support.sanitize.harvest", "--if-stale", "12", "--sync"]

    def test_a_walk_that_died_partway_is_not_stamped_as_this_windows_run(
        self, tmp_path: Path, monkeypatch, capsys,
    ):
        """Otherwise `--if-stale` reads a half-finished harvest as a finished one
        and skips the retry for the whole window.
        """
        home, _kin, _ = self._family(tmp_path)
        monkeypatch.setattr(
            harvest_module, "harvest",
            lambda *a, **k: (_ for _ in ()).throw(OSError("the tree went away")))
        monkeypatch.chdir(home)

        with pytest.raises(OSError):
            harvest_main([])

        assert not stamp_path(home).exists()


class TestStaleness:
    """The throttle that makes this safe to fire from anything that starts.

    A harvest walks the whole tree and takes the best part of a minute, so a
    startup caller has to be able to ask "is there anything to do?" and get an
    answer instantly on the runs where there is not.
    """

    def _repo(self, tmp_path: Path) -> Path:
        (tmp_path / "sanitize").mkdir()
        (tmp_path / "sanitize" / "blocklist.local.txt").write_text("x\n", encoding="utf-8")
        return tmp_path

    def test_no_stamp_reads_as_never_harvested(self, tmp_path: Path):
        assert hours_since_harvest(self._repo(tmp_path)) is None

    def test_a_fresh_stamp_reads_as_hours_ago(self, tmp_path: Path):
        repo = self._repo(tmp_path)
        stamp_path(repo).write_text("", encoding="utf-8")
        age = hours_since_harvest(repo)
        assert age is not None and age < 0.1

    def test_an_old_stamp_reads_its_age(self, tmp_path: Path):
        import os
        import time

        repo = self._repo(tmp_path)
        stamp = stamp_path(repo)
        stamp.write_text("", encoding="utf-8")
        long_ago = time.time() - 30 * 3600
        os.utime(stamp, (long_ago, long_ago))
        assert 29 < hours_since_harvest(repo) < 31

    def test_the_stamp_sits_beside_the_blocklist(self, tmp_path: Path):
        """So it is found from a worktree the same way, and ignored the same way."""
        repo = self._repo(tmp_path)
        assert stamp_path(repo).parent == (repo / "sanitize")
        assert stamp_path(repo).name.endswith(".local.txt")

    def test_the_threshold_is_read_from_the_flag(self):
        assert _stale_hours(["--if-stale", "6", "--sync"]) == 6.0

    def test_absent_flag_means_no_throttle(self):
        assert _stale_hours(["--sync"]) is None

    def test_a_malformed_threshold_falls_back_rather_than_crashing(self):
        """Fired from a startup path, so a typo must not take the caller down."""
        assert _stale_hours(["--if-stale"]) == 24.0
        assert _stale_hours(["--if-stale", "soon"]) == 24.0


class TestSiblings:
    def _family(self, tmp_path: Path) -> Path:
        """Three neighbouring checkouts, two of which keep a blocklist.

        ``here`` is a real repo: without that, resolving its primary walks up
        into whatever repo the test itself is running inside, and the assertion
        is about the wrong family entirely.
        """
        for name in ("here", "kin", "stranger"):
            (tmp_path / name).mkdir()
        for name in ("here", "kin"):
            (tmp_path / name / "sanitize").mkdir()
        here = tmp_path / "here"
        _git(here, "init", "-b", "main")
        _git(here, "config", "user.email", "h@e.test")
        _git(here, "config", "user.name", "H")
        return here

    def test_finds_checkouts_that_keep_a_blocklist(self, tmp_path: Path):
        assert [p.name for p in siblings_of(self._family(tmp_path))] == ["kin"]

    def test_from_a_worktree_it_still_finds_the_real_siblings(self, tmp_path: Path):
        """The whole point. A worktree's own neighbours are other worktrees, so
        anchoring on it hid most of the family — and the collision check that
        keeps ordinary words off the list is only as good as the checkouts it
        can see. Three project words got through exactly this way.
        """
        here = self._family(tmp_path)
        (here / "README.md").write_text("hi\n", encoding="utf-8")
        _git(here, "add", "README.md")
        _git(here, "commit", "-m", "seed", "--no-verify")
        tree = here / ".claude" / "worktrees" / "wt"
        tree.parent.mkdir(parents=True)
        _git(here, "worktree", "add", str(tree), "-b", "side")

        assert [p.name for p in siblings_of(tree)] == ["kin"]
        assert primary_of(tree) == here.resolve()

    def test_a_primary_is_its_own_primary(self, tmp_path: Path):
        assert primary_of(self._family(tmp_path)) == (tmp_path / "here").resolve()

    def test_outside_git_it_falls_back_to_the_path_given(self, tmp_path: Path):
        assert primary_of(tmp_path / "nowhere") == tmp_path / "nowhere"
