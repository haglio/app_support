"""The numbers a repo keeps per file, which only ever move the right way. Every file here is invented."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from consumer_runs import run_pytest_in

from app_support.gates import Checkout, baseline, over

GATED = "-p no:cacheprovider -p app_support.gates.pytest_plugin --timeout=60 --timeout-method=thread"
PROJECT = '[project]\nname = "example"\n'
MEASURING = """\
[tool.pytest.ini_options]
addopts = "-p no:cacheprovider -p app_support.coverage_gate --cov --cov-report="
testpaths = ["tests"]
"""
TWO_LINES = "def told():\n    return 1\n\n\ndef never_called():\n    return 2\n"
A_TEST = "from pkg.mod import told\n\n\ndef test_told():\n    assert told() == 1\n"


def _files(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _checkout(root: Path, files: dict[str, str] | None = None, entries: dict | None = None) -> Checkout:
    every = {"pyproject.toml": PROJECT, "pkg/__init__.py": "", **(files or {})}
    if entries is not None:
        every[baseline.BASELINE_PATH] = json.dumps(entries)
    return Checkout(_files(root, every))


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=a", "-c", "user.email=a@example.invalid", *args],
                          capture_output=True, text=True, check=True).stdout


def _with_a_main(root: Path) -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "first")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")


class TestProseLines:
    @pytest.mark.parametrize(("source", "lines"), [
        ("x = 1\n", 0),
        ("# why\nx = 1\n", 1),
        ("x = 1  # why\n", 0),
        ('"""One line."""\nx = 1\n', 1),
        ('"""Three\n\nlines with a blank."""\n', 2),
        ('def f():\n    """Told."""\n    return 1\n', 1),
        ('X = """not\nprose"""\n', 0),
        ('f("""not\nprose""")\n', 0),
        ("def broken(:\n    '''\n", 0),
    ], ids=["code", "comment", "trailing comment", "docstring", "blank in a docstring", "function docstring",
            "assigned string", "argument string", "what will not tokenize"])
    def test_a_line_is_prose_when_a_comment_or_a_docstring_is_all_it_holds(self, source: str, lines: int):
        assert baseline.prose_lines(source) == lines


class TestMethods:
    @pytest.mark.parametrize(("source", "methods"), [
        ("class A:\n    def f(self):\n        pass\n    def g(self):\n        pass\n", 2),
        ("class A:\n    async def f(self):\n        pass\n", 1),
        ("class A:\n    if True:\n        def f(self):\n            pass\n", 1),
        ("class A:\n    try:\n        x = 1\n    except E:\n        def f(self):\n            pass\n", 1),
        ("class A:\n    def f(self):\n        def inner():\n            pass\n", 1),
        ("class A:\n    class B:\n        def f(self):\n            pass\n", 0),
        ("class C:\n    def f(self):\n        pass\n", 0),
    ], ids=["two", "async", "inside a block", "inside a handler", "a closure is not one", "a nested class's are not", "no such class"])
    def test_a_class_is_counted_by_what_it_defines_itself(self, source: str, methods: int):
        assert baseline.methods_of(source, "A") == methods


class TestWhatACountReads:
    def test_prose_is_read_over_the_code_and_the_tests(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {"pkg/a.py": "# why\n", "tools/t.py": "# why\n# what\n",
                                        "tests/test_a.py": "# why\n", "main.py": "x = 1\n"})

        assert baseline.count_named("prose_lines").measure(checkout, {}) == {
            "pkg/a.py": 1, "tools/t.py": 2, "tests/test_a.py": 1}

    def test_reaches_are_read_over_the_code_alone(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {"pkg/a.py": "def f(b):\n    return b._c\n",
                                        "tests/test_a.py": "def f(b):\n    return b._c\n"})

        assert baseline.count_named("private_reaches").measure(checkout, {}) == {"pkg/a.py": 1}

    def test_private_imports_are_read_over_the_code_alone(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {"pkg/a.py": "from pkg.b import _c\n", "pkg/b.py": "_c = 1\n",
                                        "tests/test_a.py": "from pkg.b import _c\n"})

        assert baseline.count_named("private_imports").measure(checkout, {}) == {"pkg/a.py": 1}

    def test_methods_are_read_only_of_the_classes_the_repo_lists(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {"pkg/a.py": "class A:\n    def f(self):\n        pass\n\n\nclass B:\n    def g(self):\n        pass\n"})

        assert baseline.count_named("methods").measure(checkout, {"pkg/a.py::A": 5, "pkg/gone.py::C": 1}) == {
            "pkg/a.py::A": 1}


class TestTheCompare:
    def test_a_rise_above_its_entry_is_over(self):
        assert over({"a.py": 2}, {"a.py": 3}) == {"a.py": (3, 2)}

    def test_a_unit_absent_from_the_entries_enters_at_zero(self):
        assert over({}, {"new.py": 1}) == {"new.py": (1, 0)}

    def test_nothing_is_over_at_its_entry(self):
        assert over({"a.py": 2}, {"a.py": 2}) == {}

    def test_a_fall_below_its_entry_is_owed(self):
        assert baseline.owed({"a.py": 2, "b.py": 1, "c.py": 4}, {"a.py": 1, "c.py": 4}) == {"a.py": (1, 2), "b.py": (0, 1)}

    def test_lowered_entries_take_every_fall_keep_every_rise_and_drop_what_reached_zero(self):
        assert baseline.lowered({"a.py": 2, "b.py": 1, "c.py": 4}, {"a.py": 1, "c.py": 9}) == {"a.py": 1, "c.py": 4}


class TestCarrying:
    def test_a_renamed_files_entry_goes_with_it(self):
        assert baseline.carried({"old.py": 3, "kept.py": 1}, {"old.py": "new.py"}) == {"new.py": 3, "kept.py": 1}

    def test_a_renamed_files_classes_go_with_it(self):
        assert baseline.carried({"old.py::A": 3}, {"old.py": "new.py"}) == {"new.py::A": 3}

    def test_an_entry_the_new_name_already_holds_is_not_added_to(self):
        assert baseline.carried({"old.py": 3, "new.py": 1}, {"old.py": "new.py"}) == {"new.py": 3}


class TestHoldingACount:
    def test_a_section_the_file_does_not_have_passes(self, tmp_path: Path):
        baseline.assert_count_holds(_checkout(tmp_path, {"pkg/a.py": "# why\n"}, {}), baseline.count_named("prose_lines"))

    def test_a_rise_and_a_fall_are_both_told(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {"pkg/a.py": "# why\n# what\n", "pkg/b.py": "x = 1\n"},
                             {"prose_lines": {"pkg/a.py": 1, "pkg/b.py": 1}})

        with pytest.raises(AssertionError) as told:
            baseline.assert_count_holds(checkout, baseline.count_named("prose_lines"))

        assert "pkg/a.py holds 2 prose_lines, over its entry of 1" in str(told.value)
        assert "pkg/b.py holds 0 prose_lines, under its entry of 1" in str(told.value)

    def test_a_reach_over_its_entry_shows_its_line(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {"pkg/a.py": "def f(b):\n    return b._c\n"}, {"private_reaches": {}})

        with pytest.raises(AssertionError, match=r"pkg/a.py:2: b._c"):
            baseline.assert_count_holds(checkout, baseline.count_named("private_reaches"))

    def test_nothing_above_main_holds_with_no_history_to_read(self, tmp_path: Path):
        baseline.assert_nothing_stands_above_main(_checkout(tmp_path, {}, {"prose_lines": {"pkg/a.py": 9}}))

    def test_a_section_main_holds_cannot_be_dropped(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {"pkg/a.py": "# why\n"}, {"prose_lines": {"pkg/a.py": 1}})
        _with_a_main(tmp_path)
        _files(tmp_path, {baseline.BASELINE_PATH: json.dumps({})})

        with pytest.raises(AssertionError, match=r"prose_lines is gone from the file, and main holds it"):
            baseline.assert_nothing_stands_above_main(checkout)

    def test_an_entry_above_mains_is_told(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {}, {"prose_lines": {"pkg/a.py": 1}})
        _with_a_main(tmp_path)
        _files(tmp_path, {baseline.BASELINE_PATH: json.dumps({"prose_lines": {"pkg/a.py": 2}})})

        with pytest.raises(AssertionError, match=r"prose_lines pkg/a.py stands at 2, above the 1 main holds"):
            baseline.assert_nothing_stands_above_main(checkout)


class TestTheGateInARun:
    def _repo(self, root: Path, files: dict[str, str], entries: dict | None) -> Path:
        every = {"pyproject.toml": PROJECT + f'[tool.pytest.ini_options]\naddopts = "{GATED}"\n',
                 "example/__init__.py": "", **files}
        if entries is not None:
            every[baseline.BASELINE_PATH] = json.dumps(entries)
        return _files(root, every)

    def _a_baseline_gate_failed(self, done) -> list[str]:
        return [line for line in done.stdout.splitlines() if line.startswith("FAILED") and "test_no_baseline_entry" in line]

    def test_a_repo_with_no_baseline_is_not_held_to_one(self, tmp_path: Path):
        done = run_pytest_in(self._repo(tmp_path, {"example/a.py": "# why\n"}, None))

        assert self._a_baseline_gate_failed(done) == [], done.stdout
        assert "test_quality_baseline" not in run_pytest_in(tmp_path, "--collect-only").stdout

    def test_a_file_at_its_entry_passes(self, tmp_path: Path):
        done = run_pytest_in(self._repo(tmp_path, {"example/a.py": "# why\n"}, {"prose_lines": {"example/a.py": 1}}))

        assert self._a_baseline_gate_failed(done) == [], done.stdout

    def test_a_file_that_grew_goes_red_even_when_another_shrank_by_as_much(self, tmp_path: Path):
        done = run_pytest_in(self._repo(tmp_path, {"example/a.py": "# why\n# what\n", "example/b.py": "x = 1\n"},
                                        {"prose_lines": {"example/a.py": 1, "example/b.py": 1}}))

        assert "example/a.py holds 2 prose_lines, over its entry of 1" in done.stdout

    def test_a_file_that_shrank_goes_red_until_its_entry_comes_down(self, tmp_path: Path):
        done = run_pytest_in(self._repo(tmp_path, {"example/a.py": "x = 1\n"}, {"prose_lines": {"example/a.py": 1}}))

        assert "example/a.py holds 0 prose_lines, under its entry of 1" in done.stdout
        assert "python -m app_support.gates.baseline" in done.stdout

    def test_a_new_file_with_prose_goes_red(self, tmp_path: Path):
        done = run_pytest_in(self._repo(tmp_path, {"example/a.py": "# why\n"}, {"prose_lines": {}}))

        assert "example/a.py holds 1 prose_lines, over its entry of 0" in done.stdout

    def test_a_reach_says_which_line_it_is(self, tmp_path: Path):
        done = run_pytest_in(self._repo(tmp_path, {"example/a.py": "def f(b):\n    return b._c\n"},
                                        {"private_reaches": {}}))

        assert "example/a.py:2: b._c" in done.stdout

    def test_a_section_the_file_does_not_have_is_not_held(self, tmp_path: Path):
        done = run_pytest_in(self._repo(tmp_path, {"example/a.py": "def f(b):\n    return b._c\n"},
                                        {"prose_lines": {}}))

        assert self._a_baseline_gate_failed(done) == [], done.stdout


class TestAnEntryRaisedByHand:
    def _committed(self, root: Path, entries: dict) -> None:
        _files(root, {"pyproject.toml": PROJECT + f'[tool.pytest.ini_options]\naddopts = "{GATED}"\n',
                      "example/__init__.py": "", "example/a.py": "# why\n",
                      baseline.BASELINE_PATH: json.dumps(entries)})
        _with_a_main(root)

    def test_it_goes_red_against_what_main_holds(self, tmp_path: Path):
        self._committed(tmp_path, {"prose_lines": {"example/a.py": 1}})
        _files(tmp_path, {"example/a.py": "# why\n# what\n",
                          baseline.BASELINE_PATH: json.dumps({"prose_lines": {"example/a.py": 2}})})

        done = run_pytest_in(tmp_path)

        assert "prose_lines example/a.py stands at 2, above the 1 main holds" in done.stdout

    def test_a_new_entry_counts_as_raised_from_zero(self, tmp_path: Path):
        self._committed(tmp_path, {"prose_lines": {"example/a.py": 1}})
        _files(tmp_path, {"example/b.py": "# why\n",
                          baseline.BASELINE_PATH: json.dumps({"prose_lines": {"example/a.py": 1, "example/b.py": 1}})})

        done = run_pytest_in(tmp_path)

        assert "prose_lines example/b.py stands at 1, above the 0 main holds" in done.stdout

    def test_a_renamed_files_entry_is_no_raise(self, tmp_path: Path):
        self._committed(tmp_path, {"prose_lines": {"example/a.py": 1}})
        _git(tmp_path, "mv", "example/a.py", "example/b.py")
        _files(tmp_path, {baseline.BASELINE_PATH: json.dumps({"prose_lines": {"example/b.py": 1}})})

        assert "above the" not in run_pytest_in(tmp_path).stdout

    def test_a_section_new_since_main_is_the_adoption_of_that_section(self, tmp_path: Path):
        self._committed(tmp_path, {"prose_lines": {"example/a.py": 1}})
        _files(tmp_path, {"example/b.py": "def f(c):\n    return c._d\n",
                          baseline.BASELINE_PATH: json.dumps({"prose_lines": {"example/a.py": 1},
                                                              "private_reaches": {"example/b.py": 1}})})

        assert "above the" not in run_pytest_in(tmp_path).stdout

    def test_a_branch_behind_main_is_held_to_where_it_left_main(self, tmp_path: Path):
        self._committed(tmp_path, {"prose_lines": {"example/a.py": 1}})
        _git(tmp_path, "checkout", "-q", "-b", "elsewhere")
        _files(tmp_path, {"example/a.py": "x = 1\n", baseline.BASELINE_PATH: json.dumps({"prose_lines": {}})})
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "main moved on")
        _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
        _git(tmp_path, "checkout", "-q", "main")

        assert "above the" not in run_pytest_in(tmp_path).stdout


class TestTheCommand:
    def _main(self, checkout: Checkout) -> tuple[int, str]:
        said: list[str] = []
        code = baseline.main_in(checkout, said=said.append)
        return code, "\n".join(said)

    def _written(self, checkout: Checkout) -> dict:
        return json.loads((checkout.root / baseline.BASELINE_PATH).read_text(encoding="utf-8"))

    def test_with_no_file_it_enters_what_it_measures(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {"pkg/a.py": "# why\ndef f(b):\n    return b._c\n"})

        code, _ = self._main(checkout)

        assert code == 0
        assert self._written(checkout) == {**{count.section: {} for count in baseline.COUNTS},
                                           "private_reaches": {"pkg/a.py": 1}, "prose_lines": {"pkg/a.py": 1}}

    def test_it_lowers_what_fell(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {"pkg/a.py": "# why\n"}, {"prose_lines": {"pkg/a.py": 3}})

        code, said = self._main(checkout)

        assert code == 0
        assert self._written(checkout)["prose_lines"] == {"pkg/a.py": 1}
        assert "lowered prose_lines pkg/a.py from 3 to 1" in said

    def test_it_refuses_to_raise_what_rose_and_says_so(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {"pkg/a.py": "# why\n# what\n"}, {"prose_lines": {"pkg/a.py": 1}})

        code, said = self._main(checkout)

        assert code == 1
        assert self._written(checkout)["prose_lines"] == {"pkg/a.py": 1}
        assert "refused prose_lines pkg/a.py: it holds 2, over its entry of 1" in said

    def test_it_carries_a_renamed_files_entry(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {"pkg/a.py": "# why\n" * 3}, {"prose_lines": {"pkg/a.py": 3}})
        _with_a_main(tmp_path)
        _git(tmp_path, "mv", "pkg/a.py", "pkg/b.py")

        code, said = self._main(checkout)

        assert code == 0
        assert self._written(checkout)["prose_lines"] == {"pkg/b.py": 3}
        assert "carried prose_lines pkg/a.py to pkg/b.py" in said

    def test_it_says_what_it_could_not_match(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {"pkg/new.py": "# why\n"}, {"prose_lines": {"pkg/gone.py": 2}})
        _with_a_main(tmp_path)

        code, said = self._main(checkout)

        assert code == 1
        assert "could not match prose_lines pkg/gone.py: nothing is there now and git names no rename of it" in said
        assert "refused prose_lines pkg/new.py: it holds 1, over its entry of 0" in said

    def test_it_keeps_the_file_in_one_order_with_a_line_per_entry(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {"pkg/b.py": "# why\n", "pkg/a.py": "# why\n"})

        self._main(checkout)

        written = (tmp_path / baseline.BASELINE_PATH).read_text(encoding="utf-8")
        assert '  "prose_lines": {\n    "pkg/a.py": 1,\n    "pkg/b.py": 1\n  },\n' in written


class TestUncoveredLines:
    def _measured(self, root: Path, entries: dict | None, *args: str):
        every = {"pyproject.toml": PROJECT + MEASURING, "pkg/__init__.py": "", "pkg/mod.py": TWO_LINES,
                 "tests/test_mod.py": A_TEST, ".coveragerc": "[run]\nsource = .\nomit = tests/*\nrelative_files = true\n"
                 "[report]\nfail_under = 74.5\n"}
        if entries is not None:
            every[baseline.BASELINE_PATH] = json.dumps(entries)
        return run_pytest_in(_files(root, every), *args)

    def test_a_file_with_more_uncovered_lines_than_its_entry_fails_the_run(self, tmp_path: Path):
        done = self._measured(tmp_path, {"uncovered_lines": {}})

        assert done.returncode == 1, done.stdout
        assert "pkg/mod.py leaves 1 uncovered_lines, over its entry of 0" in done.stdout

    def test_a_file_at_its_entry_passes(self, tmp_path: Path):
        done = self._measured(tmp_path, {"uncovered_lines": {"pkg/mod.py": 1}})

        assert done.returncode == 0, done.stdout

    def test_a_file_under_its_entry_passes_since_a_line_may_be_reached_by_chance(self, tmp_path: Path):
        done = self._measured(tmp_path, {"uncovered_lines": {"pkg/mod.py": 5}})

        assert done.returncode == 0, done.stdout

    def test_a_repo_whose_file_has_no_such_section_is_not_held_to_one(self, tmp_path: Path):
        done = self._measured(tmp_path, {"prose_lines": {}})

        assert "uncovered_lines" not in done.stdout

    def test_a_narrowed_run_is_not_held_to_it(self, tmp_path: Path):
        done = self._measured(tmp_path, {"uncovered_lines": {}}, "tests/test_mod.py")

        assert done.returncode == 0, done.stdout

    def test_the_command_reads_the_last_run(self, tmp_path: Path):
        self._measured(tmp_path, {"uncovered_lines": {"pkg/mod.py": 5}})
        said: list[str] = []

        code = baseline.main_in(Checkout(tmp_path), said=said.append)

        assert code == 0
        written = json.loads((tmp_path / baseline.BASELINE_PATH).read_text(encoding="utf-8"))
        assert written["uncovered_lines"] == {"pkg/mod.py": 1}

    def test_the_command_enters_the_section_from_the_last_run_when_the_file_has_none(self, tmp_path: Path):
        self._measured(tmp_path, {})

        assert baseline.main_in(Checkout(tmp_path), said=print) == 0
        written = json.loads((tmp_path / baseline.BASELINE_PATH).read_text(encoding="utf-8"))
        assert written["uncovered_lines"] == {"pkg/mod.py": 1}

    def test_holding_a_gathered_run_names_each_rise(self, tmp_path: Path):
        self._measured(tmp_path, {"uncovered_lines": {"pkg/mod.py": 1}})
        _files(tmp_path, {baseline.BASELINE_PATH: json.dumps({"uncovered_lines": {}})})
        said: list[str] = []

        assert baseline.hold_uncovered(Checkout(tmp_path), said=said.append) == 1
        assert said == ["pkg/mod.py leaves 1 uncovered_lines, over its entry of 0: test them, or take them out"]

    def test_holding_a_gathered_run_at_its_entries_passes(self, tmp_path: Path):
        self._measured(tmp_path, {"uncovered_lines": {"pkg/mod.py": 1}})

        assert baseline.hold_uncovered(Checkout(tmp_path), said=print) == 0

    def test_holding_with_no_run_to_read_is_no_pass(self, tmp_path: Path):
        said: list[str] = []

        assert baseline.hold_uncovered(_checkout(tmp_path, {}, {"uncovered_lines": {}}), said=said.append) == 1
        assert said == ["no whole run's .coverage to read"]

    def test_the_command_says_when_there_is_no_run_to_read(self, tmp_path: Path):
        checkout = _checkout(tmp_path, {}, {"uncovered_lines": {"pkg/a.py": 2}})
        said: list[str] = []

        code = baseline.main_in(checkout, said=said.append)

        assert code == 0
        assert "left uncovered_lines as it was: no whole run's .coverage to read" in said
        written = json.loads((tmp_path / baseline.BASELINE_PATH).read_text(encoding="utf-8"))
        assert written["uncovered_lines"] == {"pkg/a.py": 2}
