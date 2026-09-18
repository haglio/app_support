"""The family's Windows launchers, rendered from one template: `app_support.launcher`.

A launcher's text says little about whether it runs: VBScript reports an
undeclared variable only when the line holding it executes.  So what the template
renders is run here under the real console script host -- its decisions through
the dry run, and its launch through a rehearsal that swaps ``WScript.Shell`` for
a stand-in, so every line runs and nothing is started.
"""
from __future__ import annotations

import contextlib
import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app_support import launcher
from app_support.launcher import (
    LauncherSpecError,
    ScriptHostRun,
    dry_run,
    launchers,
    run_under_script_host,
)


def _checkout(tmp_path: Path, specs: str, name: str = "example") -> Path:
    checkout = tmp_path / name
    checkout.mkdir(parents=True, exist_ok=True)
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "example"\n\n' + specs, encoding="utf-8")
    return checkout


MINIMAL = """
[tool.haglio.launchers."launch_example.vbs"]
app = "Example"
run = "-m example"
"""


class TestTheSpec:
    def test_a_checkout_declares_its_launchers_in_its_pyproject(self, tmp_path: Path):
        (found,) = launchers(_checkout(tmp_path, MINIMAL))

        assert found.file == "launch_example.vbs"
        assert found.app == "Example"
        assert found.run == "-m example"
        assert found.interpreter == "python.exe"
        assert found.venv == "own"
        assert found.log is None

    def test_a_checkout_with_no_launchers_declares_none(self, tmp_path: Path):
        assert launchers(_checkout(tmp_path, "")) == []

    def test_a_misspelled_key_is_refused_rather_than_ignored(self, tmp_path: Path):
        checkout = _checkout(tmp_path, MINIMAL + 'named-interpretor = "Example-Example.exe"\n')

        with pytest.raises(LauncherSpecError, match="named-interpretor"):
            launchers(checkout)

    @pytest.mark.parametrize("missing", ["app", "run"])
    def test_a_launcher_is_refused_without_its_app_or_what_it_runs(
        self, tmp_path: Path, missing: str,
    ):
        spec = "\n".join(line for line in MINIMAL.splitlines() if not line.startswith(missing))

        with pytest.raises(LauncherSpecError, match=missing):
            launchers(_checkout(tmp_path, spec))

    def test_text_the_script_host_would_misread_is_refused(self, tmp_path: Path):
        # wscript reads a launcher in the ANSI code page, so a dash typed as an
        # em dash reaches the dialog as three other characters.
        checkout = _checkout(tmp_path, MINIMAL.replace('"Example"', '"Example — Two"'))

        with pytest.raises(LauncherSpecError, match="ASCII"):
            launchers(checkout)

    def test_a_control_character_in_a_spec_is_refused(self, tmp_path: Path):
        checkout = _checkout(tmp_path, MINIMAL + 'log = "state\\u000Bexample.log"\n')

        with pytest.raises(LauncherSpecError, match="log holds a control character"):
            launchers(checkout)

    def test_watching_a_launch_needs_the_log_it_watches_beside(self, tmp_path: Path):
        with pytest.raises(LauncherSpecError, match="watch"):
            launchers(_checkout(tmp_path, MINIMAL + "watch = true\n"))

    def test_a_note_needs_the_watch_whose_failure_would_show_it(self, tmp_path: Path):
        with pytest.raises(LauncherSpecError, match="note"):
            launchers(_checkout(tmp_path, NOTED_WITHOUT_WATCH))

    def test_copying_from_the_primary_needs_the_primary_venv(self, tmp_path: Path):
        spec = MINIMAL + 'copy-from-primary = ["content.local.json"]\n'

        with pytest.raises(LauncherSpecError, match="copy-from-primary"):
            launchers(_checkout(tmp_path, spec))

    def test_a_venv_is_either_this_checkouts_or_the_primarys(self, tmp_path: Path):
        with pytest.raises(LauncherSpecError, match="venv"):
            launchers(_checkout(tmp_path, MINIMAL + 'venv = "shared"\n'))

    def test_a_placeholder_nothing_fills_is_refused(self, tmp_path: Path):
        # {checkout} is only known to a launcher a shortcut hands a checkout to.
        spec = MINIMAL.replace('"-m example"', '"-m example {checkout}"')

        with pytest.raises(LauncherSpecError, match="checkout"):
            launchers(_checkout(tmp_path, spec))

    def test_the_whole_spec_is_read(self, tmp_path: Path):
        spec = """
[tool.haglio.launchers."launch_branch.vbs"]
app = "Example"
run = '-m example.branch "{checkout}"'
interpreter = "pythonw.exe"
named-interpreter = "Example-Example.exe"
venv = "primary"
log = 'state\\launcher.log'
watch = true
environment = { EXAMPLE_BRANCH = "1" }
copy-from-primary = ["content.local.json"]

[tool.haglio.launchers."launch_branch.vbs".checkout-argument]
missing = "Nothing to run."
gone = "Gone: {checkout}"

[tool.haglio.launchers."launch_branch.vbs".checkout-argument.flags."--two"]
app = "Example Two"
log = 'state\\two_launcher.log'
"""
        (found,) = launchers(_checkout(tmp_path, spec))

        assert found.interpreter == "pythonw.exe"
        assert found.named_interpreter == "Example-Example.exe"
        assert found.venv == "primary"
        assert found.log == "state\\launcher.log"
        assert found.watch is True
        assert found.environment == (("EXAMPLE_BRANCH", "1"),)
        assert found.copy_from_primary == ("content.local.json",)
        assert found.checkout_argument.missing == "Nothing to run."
        assert found.checkout_argument.gone == "Gone: {checkout}"
        (flag,) = found.checkout_argument.flags
        assert (flag.name, flag.app, flag.log) == ("--two", "Example Two", "state\\two_launcher.log")

    def test_a_flag_needs_a_checkout_argument_to_follow(self, tmp_path: Path):
        spec = MINIMAL + '\n[tool.haglio.launchers."launch_example.vbs".flags."--two"]\napp = "Two"\n'

        with pytest.raises(LauncherSpecError, match="flags"):
            launchers(_checkout(tmp_path, spec))


class TestTheFilesOnDisk:
    def test_a_launcher_rendered_from_its_spec_passes(self, tmp_path: Path):
        checkout = _checkout(tmp_path, MINIMAL)
        launcher.write(checkout)

        assert launcher.differences(checkout) == []
        launcher.assert_launchers_match_their_specs(checkout)

    def test_a_hand_edited_launcher_is_named(self, tmp_path: Path):
        checkout = _checkout(tmp_path, MINIMAL)
        launcher.write(checkout)
        edited = checkout / "launch_example.vbs"
        edited.write_text(edited.read_text(encoding="utf-8") + "' a note\n", encoding="utf-8")

        (problem,) = launcher.differences(checkout)
        assert "launch_example.vbs" in problem
        with pytest.raises(AssertionError, match=r"app_support\.launcher --write"):
            launcher.assert_launchers_match_their_specs(checkout)

    def test_line_endings_git_may_have_changed_are_not_a_difference(self, tmp_path: Path):
        checkout = _checkout(tmp_path, MINIMAL)
        launcher.write(checkout)
        written = checkout / "launch_example.vbs"
        written.write_bytes(written.read_bytes().replace(b"\n", b"\r\n"))

        assert launcher.differences(checkout) == []

    def test_a_spec_whose_launcher_is_missing_is_named(self, tmp_path: Path):
        (problem,) = launcher.differences(_checkout(tmp_path, MINIMAL))

        assert "launch_example.vbs" in problem

    def test_a_launcher_with_no_spec_is_named(self, tmp_path: Path):
        # A hand-written launcher beside the rendered ones is the fork this
        # module exists to end.
        checkout = _checkout(tmp_path, MINIMAL)
        launcher.write(checkout)
        (checkout / "launch_other.vbs").write_text("MsgBox 1\n", encoding="utf-8")

        (problem,) = launcher.differences(checkout)
        assert "launch_other.vbs" in problem

    def test_write_leaves_a_launcher_that_already_matches_untouched(self, tmp_path: Path):
        checkout = _checkout(tmp_path, MINIMAL)

        assert launcher.write(checkout) == ["launch_example.vbs"]
        assert launcher.write(checkout) == []

    def test_the_command_line_reports_and_writes(self, tmp_path: Path, capsys):
        checkout = _checkout(tmp_path, MINIMAL)

        assert launcher.main([str(checkout)]) == 1
        assert "launch_example.vbs" in capsys.readouterr().out
        assert launcher.main([str(checkout), "--write"]) == 0
        assert launcher.main([str(checkout)]) == 0


EVERY_SHAPE = [
    launcher.Launcher("console.vbs", "Example", "-m example", log="state\\example.log"),
    launcher.Launcher("windowed.vbs", "Example", "-m example", interpreter="pythonw.exe",
                      named_interpreter="Example-Example.exe"),
    launcher.Launcher("watched.vbs", "Example", "-m example", log="state\\example.log", watch=True),
    launcher.Launcher("worktree.vbs", "Example", "-m example", venv="primary", log="example.log",
                      environment=(("EXAMPLE_BRANCH", "1"),),
                      copy_from_primary=("content.local.json",)),
    launcher.Launcher(
        "branch.vbs", "Example", '-m example "{checkout}"', log="state\\example.log", watch=True,
        checkout_argument=launcher.CheckoutArgument(
            "Nothing to run.", "Gone: {checkout}",
            (launcher.Flag("--two", "Example Two", "state\\two.log"),))),
]


@pytest.mark.parametrize("shape", EVERY_SHAPE, ids=lambda shape: shape.file)
class TestTheRendering:
    def test_every_variable_is_declared_before_the_first_statement(self, shape):
        code = [line for line in launcher.render(shape).splitlines()
                if line and not line.startswith("'")]

        assert code[0] == "Option Explicit"

    def test_nothing_goes_on_the_python_path_and_no_interpreter_is_searched_for(self, shape):
        # A checkouts' parent on PYTHONPATH makes every sibling repo directory
        # importable as a namespace package, the shadow the compat editable
        # installs exist to prevent; and a python found on PATH has none of the
        # venv's siblings, so it dies importing before it can log a word.
        text = launcher.render(shape)

        assert "PYTHONPATH" not in text
        assert "where " not in text
        assert "py -3" not in text

    def test_the_launcher_names_its_spec_and_how_to_render_it_again(self, shape):
        header = launcher.render(shape).splitlines()[:3]

        assert f'"{shape.file}"' in header[0]
        assert "python -m app_support.launcher --write" in header[1]

    def test_the_launcher_is_plain_ascii(self, shape):
        assert launcher.render(shape).isascii()


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="the Windows script host")

LOGGED = MINIMAL + "log = 'state\\example.log'\n"
WATCHED = LOGGED + "watch = true\n"
NOTED = WATCHED + "note = 'out_of_date.txt'\n"
NOTED_WITHOUT_WATCH = LOGGED + "note = 'out_of_date.txt'\n"
WINDOWED = MINIMAL + 'interpreter = "pythonw.exe"\n'
WORKTREE = MINIMAL + """venv = "primary"
log = 'state\\example.log'
environment = { EXAMPLE_BRANCH = "1" }
copy-from-primary = ["content.local.json"]
"""
BRANCH = '''
[tool.haglio.launchers."launch_example.vbs"]
app = "Example"
run = '-m example.branch "{checkout}"'
log = 'state\\launcher.log'
watch = true

[tool.haglio.launchers."launch_example.vbs".checkout-argument]
missing = "There is nothing to run here on its own."
gone = """That checkout is gone:
{checkout}"""

[tool.haglio.launchers."launch_example.vbs".checkout-argument.flags."--two"]
app = "Example Two"
log = 'state\\two_launcher.log'
'''


def _rendered(checkout: Path) -> Path:
    launcher.write(checkout)
    return checkout / "launch_example.vbs"


def _venv(folder: Path, *interpreters: str) -> Path:
    scripts = folder / ".venv" / "Scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in interpreters:
        (scripts / name).write_bytes(b"")
    return scripts


def _worktree(tmp_path: Path, specs: str) -> tuple[Path, Path]:
    """Where a branch launcher runs from: ``<primary>/.claude/worktrees/<name>``."""
    primary = tmp_path / "primary"
    return primary, _checkout(primary / ".claude" / "worktrees", specs, name="branch")


@windows_only
class TestADryRun:
    def test_it_reports_what_it_would_run_and_where(self, tmp_path: Path):
        checkout = _checkout(tmp_path, MINIMAL)

        report = dry_run(_rendered(checkout))

        interpreter = checkout / ".venv" / "Scripts" / "python.exe"
        assert report.value("app") == "Example"
        assert report.value("interpreter") == str(interpreter)
        assert report.value("directory") == str(checkout)
        assert report.value("arguments") == "-m example"
        assert report.value("command") == f'"{interpreter}" -m example'

    def test_a_watched_launch_can_name_a_note_to_show_in_place_of_the_log(self, tmp_path: Path):
        """A launch that fails for a reason the app itself knows -- a copy older than
        the code the launcher runs, say -- leaves that reason in a file beside the log,
        and the dialog is that sentence rather than fifteen lines of traceback."""
        checkout = _checkout(tmp_path, NOTED)

        report = dry_run(_rendered(checkout))

        assert report.value("note") == str(checkout / "state" / "out_of_date.txt")

    def test_it_takes_the_copy_named_for_the_app_when_one_is_there(self, tmp_path: Path):
        checkout = _checkout(tmp_path, MINIMAL + 'named-interpreter = "Example-Example.exe"\n')
        scripts = _venv(checkout, "python.exe", "Example-Example.exe")

        report = dry_run(_rendered(checkout))

        assert report.value("interpreter") == str(scripts / "Example-Example.exe")

    def test_until_a_run_has_made_that_copy_it_takes_the_plain_interpreter(self, tmp_path: Path):
        checkout = _checkout(tmp_path, MINIMAL + 'named-interpreter = "Example-Example.exe"\n')
        scripts = _venv(checkout, "python.exe")

        report = dry_run(_rendered(checkout))

        assert report.value("interpreter") == str(scripts / "python.exe")

    def test_a_console_launch_appends_everything_the_app_prints_to_its_log(self, tmp_path: Path):
        checkout = _checkout(tmp_path, LOGGED)

        report = dry_run(_rendered(checkout))

        log = checkout / "state" / "example.log"
        interpreter = checkout / ".venv" / "Scripts" / "python.exe"
        assert report.value("log") == str(log)
        assert report.value("command") == (
            f'cmd /c cd /d "{checkout}" && "{interpreter}" -m example >> "{log}" 2>&1')

    def test_a_windowed_launch_runs_the_interpreter_it_names(self, tmp_path: Path):
        checkout = _checkout(tmp_path, WINDOWED)

        report = dry_run(_rendered(checkout))

        assert report.value("interpreter") == str(checkout / ".venv" / "Scripts" / "pythonw.exe")
        assert report.values("log") == []

    def test_a_worktree_launcher_takes_the_primary_checkouts_venv(self, tmp_path: Path):
        primary, worktree = _worktree(tmp_path, WORKTREE)

        report = dry_run(_rendered(worktree))

        assert report.value("primary") == str(primary)
        assert report.value("interpreter") == str(primary / ".venv" / "Scripts" / "python.exe")
        assert report.value("directory") == str(worktree)
        assert report.value("log") == str(worktree / "state" / "example.log")

    def test_it_reports_what_it_would_set_and_what_it_would_bring_across(self, tmp_path: Path):
        primary, worktree = _worktree(tmp_path, WORKTREE)

        report = dry_run(_rendered(worktree))

        assert report.value("environment") == "EXAMPLE_BRANCH=1"
        assert report.value("copy") == (
            f"{primary / 'content.local.json'} > {worktree / 'content.local.json'}")

    def test_it_changes_nothing_on_disk(self, tmp_path: Path):
        primary, worktree = _worktree(tmp_path, WORKTREE + "watch = true\n")
        (primary / "content.local.json").write_text("{}", encoding="utf-8")
        script = _rendered(worktree)
        before = sorted(worktree.rglob("*"))

        dry_run(script)

        assert sorted(worktree.rglob("*")) == before

    def test_a_folder_named_in_what_it_runs_is_filled_in(self, tmp_path: Path):
        spec = MINIMAL.replace('"-m example"', "'-m example --config \"{root}\\example.json\"'")
        checkout = _checkout(tmp_path, spec)

        report = dry_run(_rendered(checkout))

        assert report.value("arguments") == f'-m example --config "{checkout}\\example.json"'

    def test_quotes_in_a_spec_reach_the_launcher_intact(self, tmp_path: Path):
        checkout = _checkout(tmp_path, MINIMAL.replace('"Example"', "'Say \"Example\"'"))

        report = dry_run(_rendered(checkout))

        assert report.value("app") == 'Say "Example"'


@windows_only
class TestACheckoutArgument:
    def test_with_no_checkout_it_says_there_is_nothing_to_run_here(self, tmp_path: Path):
        run = run_under_script_host(_rendered(_checkout(tmp_path, BRANCH, name="primary")))

        assert run.returncode == 1
        assert "dialog: There is nothing to run here on its own." in run.output
        assert run.values("command") == []

    def test_a_checkout_that_is_gone_is_named_in_the_refusal(self, tmp_path: Path):
        gone = tmp_path / "gone"

        run = run_under_script_host(_rendered(_checkout(tmp_path, BRANCH, name="primary")), str(gone))

        assert run.returncode == 1
        assert f"dialog: That checkout is gone:\n{gone}" in run.output

    def test_a_checkout_on_its_own_is_its_own_label(self, tmp_path: Path):
        # VBScript's And evaluates both sides, so a launcher that guards reading a
        # second argument with a count check still reads it, and dies when it is
        # not there.
        checkout = _checkout(tmp_path, "", name="worktree")

        report = dry_run(_rendered(_checkout(tmp_path, BRANCH, name="primary")), str(checkout))

        assert report.value("label") == str(checkout)

    def test_the_second_argument_labels_the_launch(self, tmp_path: Path):
        checkout = _checkout(tmp_path, "", name="worktree")

        report = dry_run(_rendered(_checkout(tmp_path, BRANCH, name="primary")),
                         str(checkout), "my-branch")

        assert report.value("label") == "my-branch"

    def test_the_checkout_holds_the_log_and_the_files_the_launch_is_watched_through(
        self, tmp_path: Path,
    ):
        primary = _checkout(tmp_path, BRANCH, name="primary")
        checkout = _checkout(tmp_path, "", name="worktree")

        report = dry_run(_rendered(primary), str(checkout))

        assert report.value("log") == str(checkout / "state" / "launcher.log")
        assert report.value("ready") == str(checkout / "state" / "launcher.ready")
        assert report.value("exited") == str(checkout / "state" / "launcher.exited")
        assert report.value("interpreter") == str(primary / ".venv" / "Scripts" / "python.exe")
        assert report.value("arguments") == f'-m example.branch "{checkout}"'

    def test_a_flag_switches_the_app_its_log_and_its_watched_files_and_is_passed_on(
        self, tmp_path: Path,
    ):
        checkout = _checkout(tmp_path, "", name="worktree")

        report = dry_run(_rendered(_checkout(tmp_path, BRANCH, name="primary")),
                         str(checkout), "my-branch", "--two")

        assert report.value("app") == "Example Two"
        assert report.value("label") == "my-branch"
        assert report.value("log") == str(checkout / "state" / "two_launcher.log")
        assert report.value("ready") == str(checkout / "state" / "two_launcher.ready")
        assert report.value("exited") == str(checkout / "state" / "two_launcher.exited")
        assert report.value("arguments") == f'-m example.branch "{checkout}" --two'

    def test_a_flag_where_the_label_would_be_leaves_the_checkout_as_the_label(
        self, tmp_path: Path,
    ):
        checkout = _checkout(tmp_path, "", name="worktree")

        report = dry_run(_rendered(_checkout(tmp_path, BRANCH, name="primary")),
                         str(checkout), "--two")

        assert report.value("label") == str(checkout)
        assert report.value("app") == "Example Two"


_REHEARSAL = """\
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = New RehearsalShell
root = fso.GetParentFolderName(WScript.ScriptFullName)
Decide
Launch
WScript.Echo "rehearsal: finished"
WScript.Quit 0

Class RehearsalShell
  Private variables

  Private Sub Class_Initialize()
    Set variables = CreateObject("Scripting.Dictionary")
  End Sub

  Public Function Environment(kind)
    Set Environment = Me
  End Function

  Public Default Property Get Item(name)
    Item = ""
    If variables.Exists(name) Then Item = variables(name)
  End Property

  Public Property Let Item(name, value)
    variables(name) = value
    WScript.Echo "rehearsal: environment " & name & "=" & value
  End Property

  Public Property Let CurrentDirectory(value)
    WScript.Echo "rehearsal: directory " & value
  End Property

  Public Function Run(command, style, wait)
    Dim stream
    WScript.Echo "rehearsal: run " & command & " (style " & style & ", wait " & wait & ")"
    fso.CreateTextFile(fso.BuildPath(root, "rehearsal.ran"), True).Close
{child}
    Run = 0
  End Function
End Class
"""

CHILD_COMES_UP = "    fso.CreateTextFile(readyFile, True).Close"
CHILD_DIES = """\
    Set stream = fso.OpenTextFile(logPath, 8, True)
    stream.WriteLine "Traceback: the example app could not start"
    stream.Close
    fso.CreateTextFile(exitedFlag, True).Close"""
CHILD_DIES_LEAVING_BLANK_LINES = """\
    Set stream = fso.OpenTextFile(logPath, 2, True)
    stream.Write vbCrLf & vbCrLf
    stream.Close
    fso.CreateTextFile(exitedFlag, True).Close"""
CHILD_DIES_LEAVING_A_NOTE = """\
    Set stream = fso.OpenTextFile(logPath, 8, True)
    stream.WriteLine "Traceback: the example app could not start"
    stream.Close
    Set stream = fso.CreateTextFile(notePath, True)
    stream.WriteLine "This copy is 12 commits older than the Example you run."
    stream.Close
    fso.CreateTextFile(exitedFlag, True).Close"""


def _rehearsal_of(script: Path, child: str = "") -> Path:
    """*script* with the shell it launches through swapped for one that only
    says what it was asked, and *child* standing in for the app it started."""
    text = script.read_text(encoding="utf-8")
    first_statement = 'Set fso = CreateObject("Scripting.FileSystemObject")\n'
    assert text.count(first_statement) == 1
    script.write_text(text.replace(first_statement, _REHEARSAL.replace("{child}", child)),
                      encoding="utf-8")
    return script


def _rehearse(script: Path, *arguments: str, child: str = "") -> ScriptHostRun:
    return run_under_script_host(_rehearsal_of(script, child), *arguments, dry_run=False)


def _rehearsed_to_the_end(run: ScriptHostRun) -> ScriptHostRun:
    __tracebackhide__ = True
    assert run.returncode == 0, run.output
    assert "Microsoft VBScript" not in run.output, run.output
    assert "rehearsal: finished" in run.output, run.output
    return run


def _line_index(run: ScriptHostRun, start: str) -> int:
    return next(index for index, line in enumerate(run.output.splitlines())
                if line.startswith(start))


@contextlib.contextmanager
def _held(path: Path):
    """Hold *path* the way a stray child holds a redirect it inherited: open for
    writing, shared with nobody."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong,
                                     ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                                     ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    path.parent.mkdir(parents=True, exist_ok=True)
    generic_write, open_always, normal = 0x40000000, 4, 0x80
    handle = kernel32.CreateFileW(str(path), generic_write, 0, None, open_always, normal, None)
    assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
    try:
        yield
    finally:
        kernel32.CloseHandle(handle)


@windows_only
class TestALaunch:
    def test_a_missing_venv_is_refused_before_anything_is_touched(self, tmp_path: Path):
        checkout = _checkout(tmp_path, LOGGED)

        run = run_under_script_host(_rendered(checkout), dry_run=False)

        assert run.returncode == 1
        interpreter = checkout / ".venv" / "Scripts" / "python.exe"
        assert f"dialog: Example's virtual environment is missing:\n{interpreter}" in run.output
        assert not (checkout / "state").exists()

    def test_a_worktree_launcher_says_it_is_the_primarys_venv_that_is_missing(self, tmp_path: Path):
        _, worktree = _worktree(tmp_path, WORKTREE)

        run = run_under_script_host(_rendered(worktree), dry_run=False)

        assert run.returncode == 1
        assert "dialog: The primary checkout's virtual environment is missing:" in run.output

    def test_a_console_launch_runs_the_app_through_cmd_into_its_log_under_a_banner(
        self, tmp_path: Path,
    ):
        checkout = _checkout(tmp_path, LOGGED)
        interpreter = _venv(checkout, "python.exe") / "python.exe"

        run = _rehearsed_to_the_end(_rehearse(_rendered(checkout)))

        log = checkout / "state" / "example.log"
        command = f'cmd /c cd /d "{checkout}" && "{interpreter}" -m example >> "{log}" 2>&1'
        assert f"rehearsal: run {command} (style 0, wait False)" in run.output
        assert f" launch: {command}" in log.read_text(encoding="utf-8")

    def test_a_held_log_costs_its_name_and_not_the_launch(self, tmp_path: Path):
        # A child of an earlier session that outlived it holds the log it
        # inherited, and cmd cannot redirect into it -- a launch that fails
        # before python runs, leaving nothing anywhere to say why.
        checkout = _checkout(tmp_path, LOGGED)
        _venv(checkout, "python.exe")

        with _held(checkout / "state" / "example.log"):
            run = _rehearsed_to_the_end(_rehearse(_rendered(checkout)))

        second = checkout / "state" / "example-2.log"
        assert f'>> "{second}" 2>&1' in run.output
        assert " launch: " in second.read_text(encoding="utf-8")

    def test_a_log_grown_past_a_megabyte_is_rolled_aside_first(self, tmp_path: Path):
        checkout = _checkout(tmp_path, LOGGED)
        _venv(checkout, "python.exe")
        log = checkout / "state" / "example.log"
        log.parent.mkdir()
        log.write_bytes(b"x" * 1_100_000)

        _rehearsed_to_the_end(_rehearse(_rendered(checkout)))

        assert (checkout / "state" / "example.log.1").stat().st_size == 1_100_000
        assert log.read_text(encoding="utf-8").startswith("===== ")

    def test_a_windowed_launch_moves_into_the_checkout_and_runs_the_interpreter(
        self, tmp_path: Path,
    ):
        checkout = _checkout(tmp_path, WINDOWED)
        interpreter = _venv(checkout, "pythonw.exe") / "pythonw.exe"

        run = _rehearsed_to_the_end(_rehearse(_rendered(checkout)))

        assert f"rehearsal: directory {checkout}" in run.output
        assert f'rehearsal: run "{interpreter}" -m example (style 0, wait False)' in run.output
        assert _line_index(run, "rehearsal: directory") < _line_index(run, "rehearsal: run")

    def test_the_environment_is_in_place_before_the_app_runs(self, tmp_path: Path):
        primary, worktree = _worktree(tmp_path, WORKTREE)
        _venv(primary, "python.exe")

        run = _rehearsed_to_the_end(_rehearse(_rendered(worktree)))

        assert _line_index(run, "rehearsal: environment EXAMPLE_BRANCH=1") < _line_index(
            run, "rehearsal: run")

    def test_a_worktree_launch_brings_the_primarys_overlay_across_first(self, tmp_path: Path):
        primary, worktree = _worktree(tmp_path, WORKTREE)
        _venv(primary, "python.exe")
        (primary / "content.local.json").write_text('{"example": 1}', encoding="utf-8")

        _rehearsed_to_the_end(_rehearse(_rendered(worktree)))

        assert (worktree / "content.local.json").read_text(encoding="utf-8") == '{"example": 1}'

    def test_an_overlay_the_primary_does_not_have_is_not_needed(self, tmp_path: Path):
        primary, worktree = _worktree(tmp_path, WORKTREE)
        _venv(primary, "python.exe")

        _rehearsed_to_the_end(_rehearse(_rendered(worktree)))

        assert not (worktree / "content.local.json").exists()

    def test_a_watched_launch_that_comes_up_says_nothing(self, tmp_path: Path):
        checkout = _checkout(tmp_path, WATCHED)
        _venv(checkout, "python.exe")

        run = _rehearsed_to_the_end(_rehearse(_rendered(checkout), child=CHILD_COMES_UP))

        exited = checkout / "state" / "example.exited"
        assert f'2>&1 & type nul > "{exited}"' in run.output
        assert "dialog:" not in run.output

    def test_a_launch_that_takes_a_moment_to_come_up_is_waited_for(self, tmp_path: Path):
        # The exit stamp an earlier launch left is cleared first, or the wait
        # would read it as this launch dying before it had a chance.
        checkout = _checkout(tmp_path, WATCHED)
        _venv(checkout, "python.exe")
        (checkout / "state").mkdir()
        (checkout / "state" / "example.exited").write_bytes(b"")
        script = _rehearsal_of(_rendered(checkout))
        host = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "cscript.exe"

        with subprocess.Popen([str(host), "//Nologo", str(script)], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True) as rehearsal:
            deadline = time.monotonic() + 30
            while not (checkout / "rehearsal.ran").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            time.sleep(0.6)
            (checkout / "state" / "example.ready").write_text("ready\n", encoding="utf-8")
            output, _ = rehearsal.communicate(timeout=30)

        _rehearsed_to_the_end(ScriptHostRun(rehearsal.returncode, output))
        assert "dialog:" not in output

    def test_what_an_earlier_launch_left_cannot_vouch_for_this_one(self, tmp_path: Path):
        checkout = _checkout(tmp_path, WATCHED)
        _venv(checkout, "python.exe")
        (checkout / "state").mkdir()
        (checkout / "state" / "example.ready").write_text("ready\n", encoding="utf-8")

        run = _rehearse(_rendered(checkout), child=CHILD_DIES)

        assert run.returncode == 1
        assert "dialog: Example failed to start." in run.output

    def test_a_watched_launch_that_dies_shows_the_end_of_its_log(self, tmp_path: Path):
        checkout = _checkout(tmp_path, WATCHED)
        _venv(checkout, "python.exe")

        run = _rehearse(_rendered(checkout), child=CHILD_DIES)

        log = checkout / "state" / "example.log"
        assert run.returncode == 1
        assert "Microsoft VBScript" not in run.output
        assert f"dialog: Example failed to start.\n\nSee the full log at:\n{log}" in run.output
        assert "Last lines of the log:" in run.output
        assert "Traceback: the example app could not start" in run.output

    def test_a_log_holding_only_blank_lines_still_reaches_the_dialog(self, tmp_path: Path):
        checkout = _checkout(tmp_path, WATCHED)
        _venv(checkout, "python.exe")

        run = _rehearse(_rendered(checkout), child=CHILD_DIES_LEAVING_BLANK_LINES)

        assert run.returncode == 1
        assert "Microsoft VBScript" not in run.output
        assert "dialog: Example failed to start." in run.output
        assert "Last lines of the log:" not in run.output

    def test_a_launch_that_leaves_a_note_shows_it_in_place_of_the_log_tail(self, tmp_path: Path):
        """The app knows why it could not start where the log's last lines only show
        where it gave up, so the note is the whole dialog and the log is a path to read."""
        checkout = _checkout(tmp_path, NOTED)
        _venv(checkout, "python.exe")

        run = _rehearse(_rendered(checkout), child=CHILD_DIES_LEAVING_A_NOTE)

        assert run.returncode == 1
        assert "Microsoft VBScript" not in run.output
        assert "This copy is 12 commits older than the Example you run." in run.output
        assert "Last lines of the log:" not in run.output
        assert str(checkout / "state" / "example.log") in run.output

    def test_a_note_from_an_earlier_launch_never_explains_this_one(self, tmp_path: Path):
        checkout = _checkout(tmp_path, NOTED)
        _venv(checkout, "python.exe")
        (checkout / "state").mkdir(exist_ok=True)
        (checkout / "state" / "out_of_date.txt").write_text(
            "the launch before this one was the stale copy", encoding="utf-8")

        run = _rehearse(_rendered(checkout), child=CHILD_DIES)

        assert run.returncode == 1
        assert "the launch before this one was the stale copy" not in run.output
        assert "Last lines of the log:" in run.output

    def test_a_launch_from_a_shortcut_that_dies_says_which_branch_it_was(self, tmp_path: Path):
        primary = _checkout(tmp_path, BRANCH, name="primary")
        _venv(primary, "python.exe")
        checkout = _checkout(tmp_path, "", name="worktree")

        run = _rehearse(_rendered(primary), str(checkout), "my-branch", child=CHILD_DIES)

        assert run.returncode == 1
        assert "dialog: Example failed to start on my-branch." in run.output


@windows_only
class TestTheChecksBite:
    def test_a_misspelled_variable_in_the_launch_does_not_rehearse_cleanly(self, tmp_path: Path):
        checkout = _checkout(tmp_path, LOGGED)
        _venv(checkout, "python.exe")
        script = _rendered(checkout)
        script.write_text(script.read_text(encoding="utf-8").replace(
            "logPath = FreeLog(logPath)", "logPath = FreeLog(logPth)"), encoding="utf-8")

        run = _rehearse(script)

        assert "Variable is undefined: 'logPth'" in run.output
        with pytest.raises(AssertionError):
            _rehearsed_to_the_end(run)

    def test_a_misspelled_variable_in_the_decisions_fails_the_dry_run(self, tmp_path: Path):
        script = _rendered(_checkout(tmp_path, MINIMAL))
        script.write_text(script.read_text(encoding="utf-8").replace(
            "  directory = root", "  directory = rot"), encoding="utf-8")

        with pytest.raises(AssertionError, match="Variable is undefined: 'rot'"):
            dry_run(script)
