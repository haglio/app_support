"""Unit tests for the shared dead-code scan.

The scan itself is the subject here. Each repo's own gate — the one whose
subject is that repo's tree — is `tests/test_dead_code.py`, which is a handful
of lines calling into this.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app_support.dead_code import (
    ScanDidNotRun,
    assert_no_dead_code,
    assert_whitelist_is_live,
    scan,
)


def _tree(root: Path, **modules: str) -> Path:
    package = root / "example_package"
    package.mkdir()
    for name, source in modules.items():
        (package / f"{name}.py").write_text(source, encoding="utf-8")
    return package


def test_the_report_names_a_function_nothing_calls(tmp_path):
    package = _tree(tmp_path, widgets="def polish_the_brass():\n    pass\n")

    report = scan(package)

    assert "polish_the_brass" in report


def test_the_gate_passes_a_tree_that_uses_everything_it_defines(tmp_path):
    package = _tree(
        tmp_path,
        widgets="def polish_the_brass():\n    pass\n",
        parlour="from example_package.widgets import polish_the_brass\n\npolish_the_brass()\n",
    )

    assert_no_dead_code(package)


def test_the_gate_fails_on_a_function_nothing_calls(tmp_path):
    package = _tree(tmp_path, widgets="def polish_the_brass():\n    pass\n")

    with pytest.raises(AssertionError) as failure:
        assert_no_dead_code(package)

    assert "polish_the_brass" in str(failure.value)


def test_a_whitelist_entry_takes_a_name_out_of_the_report(tmp_path):
    """How a repo records a name vulture cannot see the caller of -- a Qt event
    handler, a pytest fixture, an attribute the framework reads. The file is
    handed to vulture as one more thing to scan, so mentioning the name there
    counts as using it.
    """
    package = _tree(tmp_path, widgets="def polish_the_brass():\n    pass\n")
    whitelist = tmp_path / "vulture_whitelist.py"
    whitelist.write_text("polish_the_brass\n", encoding="utf-8")

    assert_no_dead_code(package, whitelist=whitelist)


def test_a_whitelist_that_suppresses_what_the_scan_reports_is_live(tmp_path):
    """Spelled the way ``vulture --make-whitelist`` writes it: ``_.name`` for an
    attribute or method, with ``_`` standing in for "some object" rather than
    naming an entry of its own.
    """
    package = _tree(
        tmp_path,
        widgets="class Sideboard:\n    def polish(self):\n        self.drawer = 1\n",
    )
    whitelist = tmp_path / "vulture_whitelist.py"
    whitelist.write_text("_.polish\n_.drawer\n", encoding="utf-8")

    assert_whitelist_is_live(package, whitelist=whitelist)


def test_a_whitelist_entry_that_suppresses_nothing_fails(tmp_path):
    """The exception file is the record of what a repo decided to allow, and an
    entry whose subject was deleted long ago is only there to hide the next name
    that happens to match it. One repo here reached 31 dead entries out of 45,
    23 of them naming symbols the family no longer contains.
    """
    package = _tree(tmp_path, widgets="def polish_the_brass():\n    pass\n")
    whitelist = tmp_path / "vulture_whitelist.py"
    whitelist.write_text(
        "polish_the_brass\nwind_the_clock  # deleted in 2019\n", encoding="utf-8"
    )

    with pytest.raises(AssertionError) as failure:
        assert_whitelist_is_live(package, whitelist=whitelist)

    assert "wind_the_clock" in str(failure.value)
    assert "polish_the_brass" not in str(failure.value)


def test_a_stale_entry_is_caught_in_the_attribute_spelling_too(tmp_path):
    package = _tree(
        tmp_path,
        widgets="class Sideboard:\n    def polish(self):\n        self.drawer = 1\n",
    )
    whitelist = tmp_path / "vulture_whitelist.py"
    whitelist.write_text("_.polish\n_.drawer\n_.varnish\n", encoding="utf-8")

    with pytest.raises(AssertionError) as failure:
        assert_whitelist_is_live(package, whitelist=whitelist)

    assert "varnish" in str(failure.value)
    assert "polish" not in str(failure.value)
    assert "drawer" not in str(failure.value)


def test_a_whitelist_kept_inside_a_scanned_tree_is_refused(tmp_path):
    """Where a whitelist may not live. vulture reads the file by unioning the
    names it uses with the names the tree uses, so one kept *inside* a scanned
    directory is read twice -- and every name in it counts as used whether or
    not it was handed over. The gate then reports nothing whatever the tree
    holds, and `assert_whitelist_is_live` calls every entry stale.
    """
    package = _tree(tmp_path, widgets="def polish_the_brass():\n    pass\n")
    whitelist = package / "vulture_whitelist.py"
    whitelist.write_text("polish_the_brass\n", encoding="utf-8")

    with pytest.raises(ScanDidNotRun):
        scan(package, whitelist=whitelist)

    with pytest.raises(ScanDidNotRun):
        assert_whitelist_is_live(package, whitelist=whitelist)


def test_a_target_that_is_not_there_is_refused_rather_than_called_clean(tmp_path):
    """The gate a repo renamed a directory out from under reports nothing, and
    nothing is what a clean tree reports too. vulture leaves them
    distinguishable -- it exits 1 for input it could not read and 3 for a report
    -- so the two must never arrive at the same answer here.
    """
    with pytest.raises(ScanDidNotRun):
        scan(tmp_path / "a_package_that_was_renamed")


def test_a_target_holding_no_python_is_refused_rather_than_called_clean(tmp_path):
    """The failure the exit code cannot catch. vulture is content to be handed a
    directory with nothing in it to read and exits 0, which is the same answer a
    scanned-and-clean tree gets -- so a gate aimed at a directory that no longer
    holds the source (an `--exclude` that swallowed the tree, a package that
    moved) keeps passing and says nothing.
    """
    empty = tmp_path / "no_python_here"
    empty.mkdir()
    (empty / "README.md").write_text("prose only\n", encoding="utf-8")

    with pytest.raises(ScanDidNotRun):
        scan(empty)


def test_a_file_vulture_cannot_parse_is_refused_rather_than_called_clean(tmp_path):
    """vulture stops at the first file it cannot read and exits 1 having
    reported nothing about the rest of the tree.
    """
    package = _tree(tmp_path, widgets="def polish_the_brass(:\n")

    with pytest.raises(ScanDidNotRun):
        scan(package)
