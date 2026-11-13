from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from app_support.subprocess_utils import hidden_subprocess_kwargs

NEW_SESSION_IN_CLAUDE_DESKTOP = "claude://code/new"
_BACKGROUNDED = re.compile(r"backgrounded\W+([0-9a-f]{8})\b")


class CommandFailed(Exception):
    pass


def run_command(command: Sequence[str], cwd: Path | str | None = None) -> str:
    try:
        done = subprocess.run(list(command), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", check=False, **hidden_subprocess_kwargs())
    except OSError as error:
        raise CommandFailed(f"{' '.join(command)} could not start: {error}") from None
    if done.returncode:
        raise CommandFailed(f"{' '.join(command)}: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text))


def claude_command(local_app_data: str | None = None, which: Callable[[str], str | None] = shutil.which) -> str:
    kept = Path(local_app_data or os.environ.get("LOCALAPPDATA", "")).glob(
        "Packages/Claude_*/LocalCache/Roaming/Claude/claude-code/*/*/claude.exe")
    newest = max(kept, key=lambda copy: _version(copy.parent.parent.name), default=None)
    return str(newest) if newest else which("claude") or "claude"


@dataclass(frozen=True)
class NewSession:
    title: str
    brief: str
    cwd: Path | str


def start_in_background(claude: str, session: NewSession, shell=run_command,
                        once_signed_in: Callable[[], object] = lambda: None) -> str:
    try:
        shell([claude, "auth", "status"])
    except CommandFailed:
        raise CommandFailed("the Claude command line is not signed in") from None
    once_signed_in()
    answer = shell([claude, "--bg", "--name", session.title, "--permission-mode", "auto", session.brief],
                   cwd=session.cwd)
    started = _BACKGROUNDED.search(answer)
    if started is None:
        raise CommandFailed(f"the Claude command line did not say it started the session: {answer.strip()}")
    return started.group(1)


def background_sessions(claude: str, shell=run_command) -> list[dict]:
    answer = shell([claude, "agents", "--json", "--all"])
    try:
        return json.loads(answer)
    except ValueError:
        raise CommandFailed(f"claude agents did not answer with a list of sessions: {answer.strip()[:200]}") from None


def open_in_claude_desktop(claude: str, short_id: str, session: str, cwd: Path | str,
                           run: Callable[..., object] = subprocess.run) -> None:
    run([claude, "stop", short_id], cwd=cwd, capture_output=True, **hidden_subprocess_kwargs())
    run([claude, "--desktop", "--resume", session], cwd=cwd, **hidden_subprocess_kwargs())


def new_session_link(folder: Path | str, brief: str) -> str:
    return f"{NEW_SESSION_IN_CLAUDE_DESKTOP}?folder={quote(str(folder), safe='')}&q={quote(brief, safe='')}"
