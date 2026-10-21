"""Production checkouts on a workspace of their own, for the tests of the updater and the hotfix route."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app_support import processes, production_update
from app_support.production_update import Outcome


def git(*arguments: str, cwd: Path) -> str:
    return subprocess.run(["git", *arguments], cwd=str(cwd), capture_output=True, text=True,
                          check=True).stdout.strip()


def pins(**versions: str) -> str:
    lines = [f'    "{name.replace("_", "-")} @ git+https://github.com/haglio/{name}@v{version}",'
             for name, version in versions.items()]
    return '[project]\nname = "example"\ndependencies = [\n' + "\n".join(lines) + "\n]\n"


def spec(name: str, version: str) -> str:
    return f"{name.replace('_', '-')} @ git+https://github.com/haglio/{name}@v{version}"


class Machine:
    """A workspace of production checkouts, each cloned from a bare origin of its own,
    and the commands an update runs: git for real, pip only written down."""

    def __init__(self, base: Path):
        self.base = base
        self.workspace = base / "workspace"
        self.workspace.mkdir()
        self.ran: list[tuple[str, ...]] = []
        self.clones = 0
        self.github_down = False

    def checkout(self, name: str = "example", *, venv: bool = True, files: dict[str, str] | None = None) -> Path:
        origin = self.base / "origins" / f"{name}.git"
        origin.parent.mkdir(exist_ok=True)
        git("init", "--bare", "-b", "main", str(origin), cwd=self.base)
        checkout = self.workspace / name
        git("clone", "-q", str(origin), str(checkout), cwd=self.base)
        self._identify(checkout)
        for file, text in (files or {"pyproject.toml": pins()}).items():
            (checkout / file).write_text(text, encoding="utf-8")
        git("add", "-A", cwd=checkout)
        git("commit", "-q", "-m", "seed", cwd=checkout)
        git("push", "-q", "-u", "origin", "main", cwd=checkout)
        git("remote", "set-head", "origin", "main", cwd=checkout)
        on_github = f"git@github.com:haglio/{name}.git"
        git("config", f"url.{origin.as_posix()}.insteadOf", on_github, cwd=checkout)
        git("remote", "set-url", "origin", on_github, cwd=checkout)
        if venv:
            (checkout / ".venv" / "Lib" / "site-packages").mkdir(parents=True)
            (checkout / ".venv" / "Scripts").mkdir()
            (checkout / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
        return checkout

    @staticmethod
    def _identify(repo: Path) -> None:
        git("config", "user.email", "someone@example.com", cwd=repo)
        git("config", "user.name", "Someone", cwd=repo)

    def ship(self, checkout: Path, files: dict[str, str], *, fetched: bool = True, authored: int | None = None) -> str:
        self.clones += 1
        clone = self.base / f"clone-{self.clones}"
        git("clone", "-q", str(self.base / "origins" / f"{checkout.name}.git"), str(clone), cwd=self.base)
        self._identify(clone)
        for name, text in files.items():
            (clone / name).write_text(text, encoding="utf-8")
        git("add", "-A", cwd=clone)
        git("commit", "-q", "-m", "shipped", *([f"--date=@{authored}"] if authored else []), cwd=clone)
        git("push", "-q", "origin", "main", cwd=clone)
        if fetched:
            git("fetch", "-q", "origin", cwd=checkout)
        return git("rev-parse", "HEAD", cwd=clone)

    def hotfix(self, checkout: Path, files: dict[str, str], *,
               stands_for: tuple[tuple[str, int], ...] = (("someone@example.com", 1_700_000_000),),
               on: str = "HEAD") -> str:
        self.clones += 1
        place = self.base / f"hotfix-{self.clones}"
        git("worktree", "add", "-q", "--detach", str(place), on, cwd=checkout)
        for name, text in files.items():
            (place / name).write_text(text, encoding="utf-8")
        git("add", "-A", cwd=place)
        git("commit", "-q", "-m", production_update.hotfix_message("the hotfix", stands_for), cwd=place)
        made = git("rev-parse", "HEAD", cwd=place)
        git("worktree", "remove", "--force", str(place), cwd=checkout)
        git("update-ref", production_update.HOTFIX_REF, made, cwd=checkout)
        return made

    def take_back(self, checkout: Path, commit: str) -> str:
        self.clones += 1
        clone = self.base / f"clone-{self.clones}"
        git("clone", "-q", str(self.base / "origins" / f"{checkout.name}.git"), str(clone), cwd=self.base)
        self._identify(clone)
        git("revert", "--no-edit", commit, cwd=clone)
        git("push", "-q", "origin", "main", cwd=clone)
        git("fetch", "-q", "origin", cwd=checkout)
        return git("rev-parse", "HEAD", cwd=clone)

    @staticmethod
    def release(checkout: Path, tag: str, commit: str = "origin/main") -> str:
        git("tag", tag, commit, cwd=checkout)
        return git("rev-parse", f"{tag}^{{commit}}", cwd=checkout)

    @staticmethod
    def hotfix_asked_for(checkout: Path) -> str | None:
        asked = subprocess.run(["git", "rev-parse", "--verify", "--quiet", production_update.HOTFIX_REF],
                               cwd=str(checkout), capture_output=True, text=True)
        return asked.stdout.strip() or None

    @staticmethod
    def install(checkout: Path, name: str, version: str) -> None:
        (checkout / ".venv" / "Lib" / "site-packages" / f"{name}-{version}.dist-info").mkdir()

    @staticmethod
    def head(checkout: Path) -> str:
        return git("rev-parse", "HEAD", cwd=checkout)

    @staticmethod
    def origin_head(checkout: Path) -> str:
        return git("rev-parse", "origin/main", cwd=checkout)

    def run(self, arguments, *, cwd=None, timeout=production_update.GIT_TIMEOUT_S, env=None) -> str:
        if arguments[:3] == ["gh", "api", "graphql"]:
            self.ran.append(("github",))
            if self.github_down:
                raise production_update.StepFailed("gh api said: could not reach api.github.com")
            return json.dumps({"data": {"repositoryOwner": {"repositories": {"nodes": [
                {"name": origin.stem, "defaultBranchRef": {"name": "main", "target": {
                    "oid": git("rev-parse", "main", cwd=origin)}}}
                for origin in sorted((self.base / "origins").glob("*.git"))]}}}})
        if "pip" in arguments:
            self.ran.append(("pip", *arguments[arguments.index("pip") + 1:]))
            return ""
        if arguments[1:2] == ["fetch"]:
            self.ran.append(("fetch", Path(cwd).name))
        elif arguments[1:2] == ["merge"]:
            self.ran.append(("merge",))
        return production_update.run(arguments, cwd=cwd, timeout=timeout, env=env)

    def bring_up(self, checkout: Path, **kwargs) -> Outcome:
        kwargs.setdefault("in_use", lambda venvs: [])
        kwargs.setdefault("wait_s", 5.0)
        return production_update.bring_up(checkout, workspace=self.workspace, run=self.run, **kwargs)


def a_process(name: str, pid: int = 4242) -> processes.Process:
    return processes.Process(pid=pid, ppid=1, started=0.0, name=name, exe=f"C:\\somewhere\\{name}",
                             cmdline=name)
