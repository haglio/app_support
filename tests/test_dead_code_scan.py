from __future__ import annotations

from pathlib import Path

import pytest

from app_support.dead_code import (
    SCAN_DEADLINE_S,
    ScanDidNotRun,
    assert_every_package_is_scanned,
    assert_no_dead_code,
    assert_no_function_takes_an_argument_it_never_reads,
    assert_nothing_is_imported_or_assigned_and_left_unread,
    assert_whitelist_is_live,
    scan,
    tracked_python,
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


def test_a_name_only_a_caller_uses_is_not_reported(tmp_path):
    package = _tree(tmp_path, widgets="def polish_the_brass():\n    pass\n")
    caller = tmp_path / "parlour.py"
    caller.write_text(
        "from example_package.widgets import polish_the_brass\n\npolish_the_brass()\n",
        encoding="utf-8",
    )

    assert_no_dead_code(package, callers=[caller])


def test_what_is_dead_inside_a_caller_is_left_to_its_own_gate(tmp_path):
    package = _tree(tmp_path, widgets="def polish_the_brass():\n    pass\n")
    caller = tmp_path / "parlour.py"
    caller.write_text(
        "from example_package.widgets import polish_the_brass\n\npolish_the_brass()\n\n\n"
        "def wind_the_clock():\n    pass\n",
        encoding="utf-8",
    )

    assert scan(package, callers=[caller]) == ""


def test_more_callers_than_a_command_line_holds_are_all_read(tmp_path):
    package = _tree(tmp_path, widgets="def polish_the_brass():\n    pass\n")
    callers = [tmp_path / f"a_caller_named_at_the_length_an_app_names_its_modules_{n:04}.py"
               for n in range(400)]
    for caller in callers:
        caller.write_text("", encoding="utf-8")
    callers[-1].write_text(
        "from example_package.widgets import polish_the_brass\n\npolish_the_brass()\n",
        encoding="utf-8",
    )

    assert_no_dead_code(package, callers=callers)


def test_a_target_inside_a_caller_is_refused_rather_than_left_out_of_the_report(tmp_path):
    package = _tree(tmp_path, widgets="def polish_the_brass():\n    pass\n")

    with pytest.raises(ScanDidNotRun):
        scan(package, callers=[tmp_path])


def test_a_whitelist_entry_for_a_name_a_caller_uses_suppresses_nothing(tmp_path):
    package = _tree(tmp_path, widgets="def polish_the_brass():\n    pass\n")
    caller = tmp_path / "parlour.py"
    caller.write_text(
        "from example_package.widgets import polish_the_brass\n\npolish_the_brass()\n",
        encoding="utf-8",
    )
    whitelist = tmp_path / "vulture_whitelist.py"
    whitelist.write_text("polish_the_brass  # the parlour calls it\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="polish_the_brass"):
        assert_whitelist_is_live(package, whitelist=whitelist, callers=[caller])


def test_a_checkouts_python_is_what_it_tracks(checkout_tracking):
    app = checkout_tracking("an_app", {"parlour.py": "", "drawing_room.py": ""})
    installed = app / ".venv" / "Lib" / "site-packages" / "example_package"
    installed.mkdir(parents=True)
    (installed / "widgets.py").write_text("", encoding="utf-8")

    assert sorted(path.name for path in tracked_python(app)) == ["drawing_room.py", "parlour.py"]


def test_a_folder_that_tracks_no_python_is_refused_rather_than_read_as_no_callers(
        tmp_path, checkout_tracking):
    (tmp_path / "not_a_checkout").mkdir()
    (tmp_path / "not_a_checkout" / "parlour.py").write_text("", encoding="utf-8")
    prose_only = checkout_tracking("prose_only", {"README.md": "prose only\n"})

    for folder in (tmp_path / "not_a_checkout", prose_only):
        with pytest.raises(ScanDidNotRun):
            tracked_python(folder)


def test_a_whitelist_entry_takes_a_name_out_of_the_report(tmp_path):
    package = _tree(tmp_path, widgets="def polish_the_brass():\n    pass\n")
    whitelist = tmp_path / "vulture_whitelist.py"
    whitelist.write_text("polish_the_brass\n", encoding="utf-8")

    assert_no_dead_code(package, whitelist=whitelist)


def test_a_whitelist_that_suppresses_what_the_scan_reports_is_live(tmp_path):
    package = _tree(
        tmp_path,
        widgets="class Sideboard:\n    def polish(self):\n        self.drawer = 1\n",
    )
    whitelist = tmp_path / "vulture_whitelist.py"
    whitelist.write_text("_.polish\n_.drawer\n", encoding="utf-8")

    assert_whitelist_is_live(package, whitelist=whitelist)


def test_a_whitelist_entry_that_suppresses_nothing_fails(tmp_path):
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
    package = _tree(tmp_path, widgets="def polish_the_brass():\n    pass\n")
    whitelist = package / "vulture_whitelist.py"
    whitelist.write_text("polish_the_brass\n", encoding="utf-8")

    with pytest.raises(ScanDidNotRun):
        scan(package, whitelist=whitelist)

    with pytest.raises(ScanDidNotRun):
        assert_whitelist_is_live(package, whitelist=whitelist)


def test_a_target_that_is_not_there_is_refused_rather_than_called_clean(tmp_path):
    with pytest.raises(ScanDidNotRun):
        scan(tmp_path / "a_package_that_was_renamed")


def test_a_target_holding_no_python_is_refused_rather_than_called_clean(tmp_path):
    empty = tmp_path / "no_python_here"
    empty.mkdir()
    (empty / "README.md").write_text("prose only\n", encoding="utf-8")

    with pytest.raises(ScanDidNotRun):
        scan(empty)


def test_a_file_vulture_cannot_parse_is_refused_rather_than_called_clean(tmp_path):
    package = _tree(tmp_path, widgets="def polish_the_brass(:\n")

    with pytest.raises(ScanDidNotRun):
        scan(package)


def test_a_scan_still_reading_at_its_deadline_is_refused_with_how_long_it_had(tmp_path):
    package = _tree(tmp_path, widgets="def polish_the_brass():\n    pass\n")

    with pytest.raises(ScanDidNotRun, match=r"still reading after 0\.001 s"):
        scan(package, deadline_s=0.001)


def test_the_gate_checks_that_scan_run_on_a_clock_longer_than_the_scans_deadline_so_a_slow_scan_fails_rather_than_kills_its_worker():
    from app_support.gates import test_dead_code as gate  # noqa: PLC0415

    for check in (gate.test_no_dead_code, gate.test_the_whitelist_still_suppresses_what_it_claims_to):
        (clock,) = [mark.args[0] for mark in check.pytestmark if mark.name == "timeout"]
        assert clock > SCAN_DEADLINE_S, check.__name__


def test_a_package_the_gate_does_not_name_is_reported(tmp_path):
    for name in ("app", "tools", "tests"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    assert_every_package_is_scanned(tmp_path, ("app", "tools"))
    with pytest.raises(AssertionError, match="tools"):
        assert_every_package_is_scanned(tmp_path, ("app",))


def test_an_import_unused_in_its_own_file_is_reported_even_if_a_sibling_uses_the_name(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text("import os\n\n\ndef a():\n    return os.sep\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("import os\n\n\ndef b():\n    return 1\n", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"b\.py:1:8: F401"):
        assert_nothing_is_imported_or_assigned_and_left_unread(tmp_path, tmp_path / "pkg")


def test_an_argument_a_function_never_reads_is_reported(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text(
        "def a(used, unused):\n    return used\n\n\ndef _cb(_frames):\n    return 1\n", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"a\.py:1:13: ARG001"):
        assert_no_function_takes_an_argument_it_never_reads(tmp_path, tmp_path / "pkg")


def test_an_unread_argument_the_repo_allows_is_named_by_its_file_and_left_out(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text("def a(used, unused):\n    return used\n", encoding="utf-8")

    assert_no_function_takes_an_argument_it_never_reads(
        tmp_path, tmp_path / "pkg", allowing=("pkg/a.py: unused",))
    with pytest.raises(AssertionError, match="unused"):
        assert_no_function_takes_an_argument_it_never_reads(
            tmp_path, tmp_path / "pkg", allowing=("pkg/b.py: unused",))


def _two_packages_sharing_a_name(tmp_path):
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "a" / "mod.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b" / "mod.py").write_text(
        "def helper():\n    return 2\n\n\ndef main():\n    return helper()\n\n\nmain()\n", encoding="utf-8")
    return tmp_path / "a", tmp_path / "b"


def test_packages_scanned_each_alone_cannot_hide_each_others_dead_code(tmp_path):
    a, b = _two_packages_sharing_a_name(tmp_path)
    assert_no_dead_code(a, b)
    with pytest.raises(AssertionError, match="helper"):
        assert_no_dead_code(a, b, each_alone=True)


def test_a_whitelist_entry_one_package_alone_reports_is_live(tmp_path):
    a, b = _two_packages_sharing_a_name(tmp_path)
    whitelist = tmp_path / "vulture_whitelist.py"
    whitelist.write_text("helper\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="helper"):
        assert_whitelist_is_live(a, b, whitelist=whitelist)
    assert_whitelist_is_live(a, b, whitelist=whitelist, each_alone=True)


def test_a_private_package_is_not_one_the_gate_must_name(tmp_path):
    (tmp_path / "_scratch").mkdir()
    (tmp_path / "_scratch" / "__init__.py").write_text("", encoding="utf-8")
    assert_every_package_is_scanned(tmp_path, ())


def test_a_directory_without_an_init_is_not_a_package_the_gate_must_name(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "a.py").write_text("", encoding="utf-8")
    assert_every_package_is_scanned(tmp_path, ())


def test_an_argument_a_method_never_reads_is_left_alone_by_default(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text(
        "class A:\n    def paint(self, event):\n        return 1\n", encoding="utf-8")
    assert_no_function_takes_an_argument_it_never_reads(tmp_path, tmp_path / "pkg")
