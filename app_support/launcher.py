"""The family's Windows launchers, each rendered from a spec in its checkout's pyproject.

A launcher is the ``.vbs`` a pinned shortcut, a scheduled task or another app runs
to start an app hidden.  The decisions every launcher makes are made here, once:
the interpreter is the venv's, never one found on ``PATH``; nothing goes on
``PYTHONPATH``, so the siblings resolve through the venv's editable installs;
``Option Explicit`` holds every variable; a dialog raised under the console host
is printed rather than shown; and ``HAGLIO_LAUNCHER_DRY_RUN=1`` makes a launcher
report what it would run and stop, which is how a suite runs one on Windows
without starting an app.

    [tool.haglio.launchers."launch_example.vbs"]
    app = "Example"
    run = "-m example"

``python -m app_support.launcher --write`` renders a checkout's launchers from
its specs; without ``--write`` it names every launcher that differs from one.

Standard library only.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

DRY_RUN = "HAGLIO_LAUNCHER_DRY_RUN"
INTERPRETERS = ("python.exe", "pythonw.exe")
VENVS = ("own", "primary")

_KEYS = frozenset({
    "app", "run", "interpreter", "named-interpreter", "venv", "log", "watch",
    "environment", "copy-from-primary", "checkout-argument",
})
_CHECKOUT_KEYS = frozenset({"missing", "gone", "flags"})
_FLAG_KEYS = frozenset({"app", "log"})
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_SCRIPT_ERROR = "Microsoft VBScript"


class LauncherSpecError(ValueError):
    """A launcher spec that cannot be rendered, named by its file and key."""


@dataclass(frozen=True)
class Flag:
    name: str
    app: str | None = None
    log: str | None = None


@dataclass(frozen=True)
class CheckoutArgument:
    missing: str
    gone: str
    flags: tuple[Flag, ...] = ()


@dataclass(frozen=True)
class Launcher:
    file: str
    app: str
    run: str
    interpreter: str = "python.exe"
    named_interpreter: str | None = None
    venv: str = "own"
    log: str | None = None
    watch: bool = False
    environment: tuple[tuple[str, str], ...] = ()
    copy_from_primary: tuple[str, ...] = ()
    checkout_argument: CheckoutArgument | None = None


# --- Reading the specs --------------------------------------------------------


def launchers(checkout: Path) -> list[Launcher]:
    """Every launcher *checkout*'s pyproject declares, checked and in file order."""
    document = tomllib.loads((Path(checkout) / "pyproject.toml").read_text(encoding="utf-8"))
    specs = document.get("tool", {}).get("haglio", {}).get("launchers", {})
    return [_launcher(file, spec) for file, spec in specs.items()]


def _launcher(file: str, spec: dict) -> Launcher:
    def refuse(message: str) -> LauncherSpecError:
        return LauncherSpecError(f"{file}: {message}")

    _refuse_unknown(refuse, spec, _KEYS, "")
    _refuse_unreadable_text(refuse, spec)
    for key in ("app", "run"):
        if not isinstance(spec.get(key), str) or not spec[key]:
            raise refuse(f"{key} is required")
    launcher = Launcher(
        file=file,
        app=spec["app"],
        run=spec["run"],
        interpreter=spec.get("interpreter", "python.exe"),
        named_interpreter=spec.get("named-interpreter"),
        venv=spec.get("venv", "own"),
        log=spec.get("log"),
        watch=spec.get("watch", False),
        environment=tuple(spec.get("environment", {}).items()),
        copy_from_primary=tuple(spec.get("copy-from-primary", ())),
        checkout_argument=_checkout_argument(refuse, spec.get("checkout-argument")),
    )
    _refuse_contradictions(refuse, launcher)
    return launcher


def _checkout_argument(refuse, table: dict | None) -> CheckoutArgument | None:
    if table is None:
        return None
    _refuse_unknown(refuse, table, _CHECKOUT_KEYS, "checkout-argument.")
    for key in ("missing", "gone"):
        if not isinstance(table.get(key), str) or not table[key]:
            raise refuse(f"checkout-argument.{key} is required")
    flags = []
    for name, flag in table.get("flags", {}).items():
        _refuse_unknown(refuse, flag, _FLAG_KEYS, f"checkout-argument.flags.{name}.")
        flags.append(Flag(name, flag.get("app"), flag.get("log")))
    return CheckoutArgument(table["missing"], table["gone"], tuple(flags))


def _refuse_unknown(refuse, table: dict, known: frozenset[str], prefix: str) -> None:
    unknown = sorted(set(table) - known)
    if unknown:
        raise refuse(f"unknown key {', '.join(prefix + key for key in unknown)}")


def _refuse_unreadable_text(refuse, value, key: str = "") -> None:
    """The script host reads a launcher in the ANSI code page rather than as UTF-8,
    and a control character inside a VBScript string hides in whatever it names."""
    if isinstance(value, dict):
        for inner_key, inner in value.items():
            _refuse_unreadable_text(refuse, inner_key, key)
            _refuse_unreadable_text(refuse, inner, f"{key}.{inner_key}" if key else inner_key)
    elif isinstance(value, list):
        for inner in value:
            _refuse_unreadable_text(refuse, inner, key)
    elif isinstance(value, str):
        if not value.isascii():
            raise refuse(f"{key or 'a key'} is not ASCII: {value!r}")
        if any(ord(character) < 32 and character != "\n" for character in value):
            raise refuse(f"{key or 'a key'} holds a control character: {value!r}")


def _refuse_contradictions(refuse, launcher: Launcher) -> None:
    if launcher.interpreter not in INTERPRETERS:
        raise refuse(f"interpreter must be one of {', '.join(INTERPRETERS)}")
    if launcher.venv not in VENVS:
        raise refuse(f"venv must be one of {', '.join(VENVS)}")
    if launcher.watch and not launcher.log:
        raise refuse("watch needs a log: the launch is watched through files beside it")
    if launcher.copy_from_primary and launcher.venv != "primary":
        raise refuse("copy-from-primary needs venv = \"primary\"")
    logs = [launcher.log, *(flag.log for flag in _flags(launcher))]
    for log in filter(None, logs):
        if PureWindowsPath(log).is_absolute() or ".." in PureWindowsPath(log).parts:
            raise refuse(f"log {log!r} must be a path inside the checkout")
    fillable = set(_variables(launcher))
    checks = [("run", launcher.run, fillable)]
    if launcher.checkout_argument:
        checks += [("checkout-argument.missing", launcher.checkout_argument.missing, set()),
                   ("checkout-argument.gone", launcher.checkout_argument.gone, {"checkout"})]
    for key, text, allowed in checks:
        for name in _PLACEHOLDER.findall(text):
            if name not in allowed:
                raise refuse(f"{key} names {{{name}}}, which nothing in this launcher fills")


def _flags(launcher: Launcher) -> tuple[Flag, ...]:
    return launcher.checkout_argument.flags if launcher.checkout_argument else ()


def _variables(launcher: Launcher) -> dict[str, str]:
    """The placeholders a launcher's text may name, and the variable each becomes."""
    variables = {"root": "root"}
    if launcher.checkout_argument:
        variables["checkout"] = "checkout"
    if launcher.venv == "primary":
        variables["primary"] = "primary"
    return variables


# --- Rendering ----------------------------------------------------------------


def render(launcher: Launcher) -> str:
    """The launcher *launcher* specifies, as the ``.vbs`` text to write."""
    sections = [
        _header(launcher),
        ["Option Explicit", "", _declarations(launcher), ""],
        _TOP.splitlines(),
        _decide(launcher),
        _report(launcher),
        _launch(launcher),
        _command(launcher),
        _QUOTE.splitlines(),
        _TELL.splitlines(),
    ]
    if launcher.log:
        sections.append(_LOG.splitlines())
    if launcher.watch:
        sections.append(_started(launcher))
        sections.append(_LAST_LINES.splitlines())
    if launcher.copy_from_primary:
        sections.append(_COPY.splitlines())
    lines: list[str] = []
    for section in sections:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(section)
    return "\n".join(lines).rstrip("\n") + "\n"


def _header(launcher: Launcher) -> list[str]:
    return [
        f"' Rendered from [tool.haglio.launchers.\"{launcher.file}\"] in pyproject.toml.",
        "' Change the spec, then run  python -m app_support.launcher --write  in this",
        "' folder: the suite fails on a launcher that differs from its spec.",
    ]


def _declarations(launcher: Launcher) -> str:
    names = ["fso", "shell", "root", "app", "interpreter", "directory", "arguments"]
    if launcher.venv == "primary":
        names.append("primary")
    if launcher.checkout_argument:
        names += ["checkout", "label"]
    if launcher.log:
        names.append("logPath")
    if launcher.watch:
        names += ["readyFile", "exitedFlag"]
    return "Dim " + ", ".join(names)


_TOP = """\
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
Decide
If shell.Environment("Process").Item("HAGLIO_LAUNCHER_DRY_RUN") = "1" Then
  Report
Else
  Launch
End If
"""


def _text(value: str, variables: Mapping[str, str] | None = None) -> str:
    """*value* as a VBScript expression: quotes doubled, each newline a vbCrLf,
    each ``{placeholder}`` the variable holding it."""
    tokens: list[str] = []
    for index, piece in enumerate(_PLACEHOLDER.split(value)):
        if index % 2:
            tokens.append((variables or {})[piece])
            continue
        for line_number, line in enumerate(piece.split("\n")):
            if line_number:
                tokens.append("vbCrLf")
            if line:
                tokens.append('"' + line.replace('"', '""') + '"')
    return " & ".join(tokens) if tokens else '""'


def _path(base: str, relative: str) -> str:
    return f"fso.BuildPath({base}, {_text(relative)})"


def _log_paths(base: str, log: str, watch: bool, indent: str) -> list[str]:
    lines = [f"{indent}logPath = {_path(base, log)}"]
    if watch:
        log_path = PureWindowsPath(log)
        lines += [
            f"{indent}readyFile = {_path(base, str(log_path.with_suffix('.ready')))}",
            f"{indent}exitedFlag = {_path(base, str(log_path.with_suffix('.exited')))}",
        ]
    return lines


def _decide(launcher: Launcher) -> list[str]:
    base = "checkout" if launcher.checkout_argument else "root"
    venv = "primary" if launcher.venv == "primary" else "root"
    lines = ["Sub Decide()"]
    if launcher.checkout_argument:
        lines.append("  Dim index")
    lines.append(f"  app = {_text(launcher.app)}")
    if launcher.checkout_argument:
        lines += [
            "  If WScript.Arguments.Count = 0 Then",
            f"    Refuse {_text(launcher.checkout_argument.missing)}, vbInformation",
            "  End If",
            "  checkout = WScript.Arguments(0)",
            "  label = checkout",
        ]
    if launcher.venv == "primary":
        lines.append("  primary = fso.GetParentFolderName("
                     "fso.GetParentFolderName(fso.GetParentFolderName(root)))")
    if launcher.log:
        lines += _log_paths(base, launcher.log, launcher.watch, "  ")
    lines.append(f"  arguments = {_text(launcher.run, _variables(launcher))}")
    if launcher.checkout_argument:
        lines += _arguments_after_the_checkout(launcher, base)
    interpreter = _path(venv, ".venv\\Scripts\\" + launcher.interpreter)
    lines.append(f"  interpreter = {interpreter}")
    if launcher.named_interpreter:
        named = _path(venv, ".venv\\Scripts\\" + launcher.named_interpreter)
        lines.append(f"  If fso.FileExists({named}) Then interpreter = {named}")
    lines += ["  directory = root", "End Sub"]
    return lines


def _arguments_after_the_checkout(launcher: Launcher, base: str) -> list[str]:
    lines = [
        "  For index = 1 To WScript.Arguments.Count - 1",
        "    Select Case LCase(WScript.Arguments(index))",
    ]
    for flag in _flags(launcher):
        lines.append(f"      Case {_text(flag.name.lower())}")
        if flag.app:
            lines.append(f"        app = {_text(flag.app)}")
        if flag.log:
            lines += _log_paths(base, flag.log, launcher.watch, "        ")
        lines.append(f"        arguments = arguments & {_text(' ' + flag.name)}")
    lines += [
        "      Case Else",
        "        If index = 1 Then label = WScript.Arguments(index)",
        "    End Select",
        "  Next",
        "  If Not fso.FolderExists(checkout) Then",
        f"    Refuse {_text(launcher.checkout_argument.gone, _variables(launcher))}, vbCritical",
        "  End If",
    ]
    return lines


def _report(launcher: Launcher) -> list[str]:
    lines = ["Sub Report()", '  WScript.Echo "app: " & app']
    if launcher.checkout_argument:
        lines += ['  WScript.Echo "checkout: " & checkout', '  WScript.Echo "label: " & label']
    if launcher.venv == "primary":
        lines.append('  WScript.Echo "primary: " & primary')
    lines += [
        '  WScript.Echo "interpreter: " & interpreter',
        '  WScript.Echo "directory: " & directory',
        '  WScript.Echo "arguments: " & arguments',
    ]
    if launcher.log:
        lines.append('  WScript.Echo "log: " & logPath')
    if launcher.watch:
        lines += ['  WScript.Echo "ready: " & readyFile', '  WScript.Echo "exited: " & exitedFlag']
    for name, value in launcher.environment:
        lines.append(f'  WScript.Echo "environment: " & {_text(name)} & "=" & {_text(value)}')
    for name in launcher.copy_from_primary:
        lines.append(f'  WScript.Echo "copy: " & {_path("primary", name)} & " > " & {_path("root", name)}')
    lines += ['  WScript.Echo "command: " & Command()', "End Sub"]
    return lines


def _launch(launcher: Launcher) -> list[str]:
    if launcher.venv == "primary":
        missing = '"The primary checkout\'s virtual environment is missing:"'
    else:
        missing = 'app & "\'s virtual environment is missing:"'
    lines = [
        "Sub Launch()",
        "  If Not fso.FileExists(interpreter) Then",
        f"    Refuse {missing} & vbCrLf & interpreter, vbCritical",
        "  End If",
    ]
    lines += [f"  CopyFromPrimary {_text(name)}" for name in launcher.copy_from_primary]
    lines += [f'  shell.Environment("Process").Item({_text(name)}) = {_text(value)}'
              for name, value in launcher.environment]
    if launcher.log:
        lines += ["  logPath = FreeLog(logPath)",
                  '  Note logPath, "===== " & Now & " launch: " & Command()']
    else:
        lines.append("  shell.CurrentDirectory = directory")
    if launcher.watch:
        lines += ["  If fso.FileExists(readyFile) Then fso.DeleteFile readyFile",
                  "  If fso.FileExists(exitedFlag) Then fso.DeleteFile exitedFlag"]
    lines.append("  shell.Run Command(), 0, False")
    if launcher.watch:
        lines += ["  If Not Started() Then", "    Refuse FailedStart(), vbCritical", "  End If"]
    lines.append("End Sub")
    return lines


def _command(launcher: Launcher) -> list[str]:
    if launcher.log:
        exit_stamp = ' & type nul > " & Quote(exitedFlag)' if launcher.watch else '"'
        command = ('"cmd /c cd /d " & Quote(directory) & " && " & Quote(interpreter) & " " & '
                   f'arguments & " >> " & Quote(logPath) & " 2>&1{exit_stamp}')
    else:
        command = 'Quote(interpreter) & " " & arguments'
    return ["Function Command()", f"  Command = {command}", "End Function"]


def _started(launcher: Launcher) -> list[str]:
    on_label = ' on " & label & "' if launcher.checkout_argument else ""
    return [
        "Function Started()",
        "  Dim waited",
        "  waited = 0",
        "  Started = False",
        "  Do",
        "    If fso.FileExists(readyFile) Then",
        "      Started = True",
        "      Exit Function",
        "    End If",
        "    If fso.FileExists(exitedFlag) Or waited >= 45000 Then Exit Function",
        "    WScript.Sleep 250",
        "    waited = waited + 250",
        "  Loop",
        "End Function",
        "",
        "Function FailedStart()",
        "  Dim tail",
        (f'  FailedStart = app & " failed to start{on_label}." & vbCrLf & vbCrLf & '
         '"See the full log at:" & vbCrLf & logPath'),
        "  tail = LastLinesOf(logPath, 15)",
        "  If Len(tail) > 0 Then",
        '    FailedStart = FailedStart & vbCrLf & vbCrLf & "Last lines of the log:" & vbCrLf & tail',
        "  End If",
        "End Function",
    ]


_QUOTE = """\
Function Quote(text)
  Quote = Chr(34) & text & Chr(34)
End Function
"""

_TELL = """\
Sub Tell(message, icon)
  If LCase(fso.GetFileName(WScript.FullName)) = "cscript.exe" Then
    WScript.Echo "dialog: " & message
  Else
    MsgBox message, icon, app
  End If
End Sub

Sub Refuse(message, icon)
  Tell message, icon
  WScript.Quit 1
End Sub
"""

_LOG = """\
Function FreeLog(preferred)
  Dim folder, candidate, index
  folder = fso.GetParentFolderName(preferred)
  If Not fso.FolderExists(folder) Then fso.CreateFolder folder
  For index = 1 To 9
    candidate = preferred
    If index > 1 Then
      candidate = fso.BuildPath(folder, fso.GetBaseName(preferred) & "-" & index & "." & fso.GetExtensionName(preferred))
    End If
    RollIfOversize candidate
    If CanAppend(candidate) Then
      FreeLog = candidate
      Exit Function
    End If
  Next
  FreeLog = preferred
End Function

Function CanAppend(path)
  Dim stream
  On Error Resume Next
  Set stream = fso.OpenTextFile(path, 8, True)
  CanAppend = (Err.Number = 0)
  If CanAppend Then stream.Close
  Err.Clear
  On Error GoTo 0
End Function

Sub RollIfOversize(path)
  On Error Resume Next
  If fso.FileExists(path) Then
    If fso.GetFile(path).Size > 1000000 Then
      If fso.FileExists(path & ".1") Then fso.DeleteFile path & ".1"
      fso.MoveFile path, path & ".1"
    End If
  End If
  Err.Clear
  On Error GoTo 0
End Sub

Sub Note(path, line)
  Dim stream
  On Error Resume Next
  Set stream = fso.OpenTextFile(path, 8, True)
  stream.WriteLine line
  stream.Close
  Err.Clear
  On Error GoTo 0
End Sub
"""

_LAST_LINES = """\
Function LastLinesOf(path, count)
  Dim stream, body, lines, first, last, index
  LastLinesOf = ""
  If Not fso.FileExists(path) Then Exit Function
  Set stream = fso.OpenTextFile(path, 1)
  body = ""
  If Not stream.AtEndOfStream Then body = stream.ReadAll
  stream.Close
  lines = Split(Replace(body, vbCr, ""), vbLf)
  last = UBound(lines)
  Do While last >= 0
    If Trim(lines(last)) <> "" Then Exit Do
    last = last - 1
  Loop
  first = last - count + 1
  If first < 0 Then first = 0
  For index = first To last
    LastLinesOf = LastLinesOf & lines(index) & vbCrLf
  Next
End Function
"""

_COPY = """\
Sub CopyFromPrimary(name)
  If fso.FileExists(fso.BuildPath(primary, name)) Then
    fso.CopyFile fso.BuildPath(primary, name), fso.BuildPath(root, name), True
  End If
End Sub
"""


# --- The launchers on disk ----------------------------------------------------


def differences(checkout: Path) -> list[str]:
    """What stands between *checkout*'s launchers and its specs, one line each."""
    checkout = Path(checkout)
    specs = {launcher.file: launcher for launcher in launchers(checkout)}
    problems = []
    for file, launcher in specs.items():
        path = checkout / file
        if not path.is_file():
            problems.append(f"{file}: declared in pyproject.toml and never rendered")
        elif path.read_text(encoding="utf-8", errors="replace") != render(launcher):
            problems.append(f"{file}: differs from its spec in pyproject.toml")
    problems += [f"{path.name}: a launcher with no spec in pyproject.toml"
                 for path in sorted(checkout.glob("*.vbs")) if path.name not in specs]
    return problems


def write(checkout: Path) -> list[str]:
    """Render every launcher *checkout* declares; the files that changed."""
    written = []
    for launcher in launchers(checkout):
        path = Path(checkout) / launcher.file
        rendered = render(launcher)
        if path.is_file() and path.read_text(encoding="utf-8", errors="replace") == rendered:
            continue
        path.write_text(rendered, encoding="ascii", newline="\n")
        written.append(launcher.file)
    return written


def assert_launchers_match_their_specs(checkout: Path) -> None:
    """A launcher that differs from its spec is a hand edit the next render erases,
    or a spec change nobody rendered -- either way not what the shortcut runs."""
    __tracebackhide__ = True
    problems = differences(checkout)
    assert not problems, (
        "these launchers are not what their specs render:\n  " + "\n  ".join(problems)
        + "\nRender them from the checkout: python -m app_support.launcher --write")


# --- Running one under the script host ------------------------------------------


@dataclass(frozen=True)
class ScriptHostRun:
    """What the console script host printed and returned for one launcher."""

    returncode: int
    output: str

    def values(self, key: str) -> list[str]:
        prefix = f"{key}: "
        return [line[len(prefix):] for line in self.output.splitlines() if line.startswith(prefix)]

    def value(self, key: str) -> str:
        values = self.values(key)
        if len(values) != 1:
            raise AssertionError(f"expected one {key!r} line, found {len(values)}:\n{self.output}")
        return values[0]


def run_under_script_host(launcher: Path, *arguments: str, dry_run: bool = True) -> ScriptHostRun:
    """Run *launcher* under Windows' own console script host, as its shortcut
    would run it with *arguments* -- told to report rather than launch unless
    *dry_run* is false."""
    host = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "cscript.exe"
    env = {name: value for name, value in os.environ.items() if name.upper() != DRY_RUN}
    if dry_run:
        env[DRY_RUN] = "1"
    finished = subprocess.run(
        [str(host), "//Nologo", str(launcher), *arguments],
        capture_output=True, text=True, env=env, timeout=60, check=False)
    return ScriptHostRun(finished.returncode, finished.stdout + finished.stderr)


def dry_run(launcher: Path, *arguments: str) -> ScriptHostRun:
    """Run *launcher* through its decisions under the script host, and fail on
    anything short of a whole report: a VBScript error on the way, a refusal, or
    no command at the end."""
    __tracebackhide__ = True
    run = run_under_script_host(launcher, *arguments)
    failure = (f"{Path(launcher).name} did not report a launch under the script host "
               f"(exit {run.returncode}):\n{run.output}")
    assert run.returncode == 0, failure
    assert _SCRIPT_ERROR not in run.output, failure
    assert run.values("command"), failure
    return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app_support.launcher",
        description="Render a checkout's launchers from the specs in its pyproject.toml.")
    parser.add_argument("checkout", nargs="?", default=".", type=Path)
    parser.add_argument("--write", action="store_true",
                        help="render them, rather than only naming the ones that differ")
    options = parser.parse_args(argv)
    if options.write:
        for file in write(options.checkout):
            print(f"rendered {file}")
        return 0
    problems = differences(options.checkout)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
