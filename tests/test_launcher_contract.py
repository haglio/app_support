from __future__ import annotations

from pathlib import Path

import pytest

from app_support import launcher
from app_support.launcher_contract import (
    assert_a_branch_can_be_tried,
    assert_every_launcher_keeps_a_log,
    assert_every_launcher_reports_its_spec,
    assert_what_a_shortcut_or_a_task_starts_runs_on_its_own_venv,
    assert_what_every_launcher_runs_is_there,
)

EVERYDAY = """
[tool.haglio.launchers."launch_example.vbs"]
app = "Example"
run = '-m example --open "{root}\\settings.json"'
interpreter = "pythonw.exe"
named-interpreter = "Example-Example.exe"
log = 'state\\example.log'
"""
A_SHORTCUT = """
[tool.haglio.shortcuts."Example"]
launcher = "launch_example.vbs"
icon = "example.ico"
app-id = "Example"
places = ["checkout"]
"""
PREVIEW = """
[tool.haglio.launchers."launch_preview_branch.vbs"]
app = "Example (branch preview)"
run = "-m example"
venv = "primary"
log = 'state\\example.log'
preview = true
loading-screen = ["Updating Example..."]
copy-from-primary = ["content.local.json"]

[tool.haglio.launchers."launch_preview_branch.vbs".environment]
EXAMPLE_BRANCH_SESSION = "1"
"""
TAKES_A_CHECKOUT = """
[tool.haglio.launchers."launch_branch.vbs"]
app = "Example"
run = '-m example "{checkout}"'
log = 'state\\example.log'
preview = true
loading-screen = ["Updating Example..."]

[tool.haglio.launchers."launch_branch.vbs".checkout-argument]
missing = "Say which."
gone = "It is gone."
"""
NO_LOG = """
[tool.haglio.launchers."launch_tray.vbs"]
app = "Example"
run = "-m example"
"""


def _checkout(tmp_path: Path, specs: str = EVERYDAY + PREVIEW) -> Path:
    checkout = tmp_path / "example" / ".claude" / "worktrees" / "a-branch"
    (checkout / "example").mkdir(parents=True)
    (checkout / "example" / "__main__.py").write_text("", encoding="utf-8")
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "example"\n[tool.haglio.production]\n' + specs, encoding="utf-8")
    launcher.write(checkout)
    return checkout


def _edit(checkout: Path, file: str, old: str, new: str) -> None:
    path = checkout / file
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


class TestWhatALauncherReports:
    def test_launchers_that_say_what_their_specs_say_pass(self, tmp_path: Path):
        assert_every_launcher_reports_its_spec(_checkout(tmp_path))

    @pytest.mark.parametrize(("file", "old", "new", "named"), [
        ("launch_example.vbs", "directory = root", 'directory = "C:\\elsewhere"', "directory"),
        ("launch_example.vbs", '"-m example --open "', '"-m other --open "', "arguments"),
        ("launch_example.vbs", ".venv\\Scripts\\pythonw.exe", "Scripts\\pythonw.exe", "interpreter"),
        ("launch_example.vbs", "state\\example.log", "state\\other.log", "log"),
        ("launch_example.vbs", 'WScript.Echo "gate: " & gate', 'WScript.Echo "not: " & gate', "gate"),
        ("launch_preview_branch.vbs", "\\preview", "\\pictures", "pictures"),
        ("launch_preview_branch.vbs", '"EXAMPLE_BRANCH_SESSION"', '"OTHER"', "environment"),
    ])
    def test_a_launcher_that_says_otherwise_is_named_with_what_it_says(
            self, tmp_path: Path, file: str, old: str, new: str, named: str):
        checkout = _checkout(tmp_path)
        _edit(checkout, file, old, new)

        with pytest.raises(AssertionError, match=f"{file}: {named}"):
            assert_every_launcher_reports_its_spec(checkout)

    def test_a_checkout_the_updater_keeps_out_of_has_no_update_to_wait_for(self, tmp_path: Path):
        checkout = _checkout(tmp_path, NO_LOG)
        without = (checkout / "pyproject.toml").read_text(encoding="utf-8").replace("[tool.haglio.production]" + chr(10), "")
        (checkout / "pyproject.toml").write_text(without, encoding="utf-8")
        launcher.write(checkout)

        assert_every_launcher_reports_its_spec(checkout)

    def test_a_launcher_that_takes_a_checkout_is_asked_with_this_one(self, tmp_path: Path):
        assert_every_launcher_reports_its_spec(_checkout(tmp_path, TAKES_A_CHECKOUT))


class TestWhatALauncherRuns:
    def test_a_package_and_a_file_that_are_there_pass(self, tmp_path: Path):
        checkout = _checkout(tmp_path, EVERYDAY + """
[tool.haglio.launchers."launch_file.vbs"]
app = "Example"
run = '"{root}\\tray_app.py" --show-window'
""")
        (checkout / "tray_app.py").write_text("", encoding="utf-8")

        assert_what_every_launcher_runs_is_there(checkout)

    def test_a_module_inside_a_package_passes(self, tmp_path: Path):
        checkout = _checkout(tmp_path, """
[tool.haglio.launchers."launch_tool.vbs"]
app = "Example"
run = "-m example.tool"
""")
        (checkout / "example" / "tool.py").write_text("", encoding="utf-8")

        assert_what_every_launcher_runs_is_there(checkout)

    @pytest.mark.parametrize("run", ["-m example.gone", "-m gone", '"{root}\\gone.py"', "nothing it can name"])
    def test_what_is_not_there_is_named(self, tmp_path: Path, run: str):
        checkout = _checkout(tmp_path, f"""
[tool.haglio.launchers."launch_tool.vbs"]
app = "Example"
run = '{run}'
""")

        with pytest.raises(AssertionError, match=r"launch_tool[.]vbs"):
            assert_what_every_launcher_runs_is_there(checkout)


class TestALaunchersLog:
    def test_a_launcher_with_no_log_is_named(self, tmp_path: Path):
        with pytest.raises(AssertionError, match=r"launch_tray[.]vbs"):
            assert_every_launcher_keeps_a_log(_checkout(tmp_path, NO_LOG), without=())

    def test_one_the_repo_lists_passes(self, tmp_path: Path):
        assert_every_launcher_keeps_a_log(_checkout(tmp_path, NO_LOG), without=("launch_tray.vbs",))

    def test_a_listed_launcher_that_has_a_log_is_named(self, tmp_path: Path):
        with pytest.raises(AssertionError, match=r"launch_example[.]vbs"):
            assert_every_launcher_keeps_a_log(_checkout(tmp_path), without=("launch_example.vbs",))

    def test_a_listed_launcher_that_is_gone_is_named(self, tmp_path: Path):
        with pytest.raises(AssertionError, match=r"launch_gone[.]vbs"):
            assert_every_launcher_keeps_a_log(_checkout(tmp_path), without=("launch_gone.vbs",))


class TestWhatHisMachineStarts:
    def test_a_shortcut_to_a_launcher_on_its_own_venv_passes(self, tmp_path: Path):
        assert_what_a_shortcut_or_a_task_starts_runs_on_its_own_venv(_checkout(tmp_path, EVERYDAY + A_SHORTCUT))

    def test_a_preview_no_shortcut_starts_may_run_on_the_primarys(self, tmp_path: Path):
        assert_what_a_shortcut_or_a_task_starts_runs_on_its_own_venv(_checkout(tmp_path))

    def test_a_shortcut_to_a_launcher_on_another_checkouts_venv_is_named(self, tmp_path: Path):
        on_the_primary = EVERYDAY + 'venv = "primary"\n' + A_SHORTCUT

        with pytest.raises(AssertionError, match=r"launch_example[.]vbs"):
            assert_what_a_shortcut_or_a_task_starts_runs_on_its_own_venv(_checkout(tmp_path, on_the_primary))


class TestTryingABranch:
    def test_a_repo_with_a_preview_passes(self, tmp_path: Path):
        assert_a_branch_can_be_tried(_checkout(tmp_path))

    def test_a_repo_with_launchers_and_no_preview_is_refused(self, tmp_path: Path):
        with pytest.raises(AssertionError, match="preview"):
            assert_a_branch_can_be_tried(_checkout(tmp_path, EVERYDAY))

    def test_a_library_has_no_app_to_try(self, tmp_path: Path):
        assert_a_branch_can_be_tried(_checkout(tmp_path, EVERYDAY), is_a_library=True)

    def test_a_repo_with_no_launchers_has_nothing_to_try(self, tmp_path: Path):
        assert_a_branch_can_be_tried(_checkout(tmp_path, ""))
