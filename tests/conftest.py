from __future__ import annotations

import contextlib
import ctypes
import faulthandler
import logging
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from desktop_of_its_own import DesktopOfItsOwn
from git_bash_programs import GitBashPrograms
from production_machine import git

import app_support
from app_support.siblings import assert_imported_from_checkout

_DELETE = 0x00010000
_SHARED_WITH_EVERYONE = 0x1 | 0x2 | 0x4
_OPEN_EXISTING = 3


def pytest_configure(config):
    """Refuse a run that is testing a different checkout than the one it is in.

    This repo's directory is named for the package inside it, and every consumer
    installs the package editable from the primary checkout -- so from a
    worktree, ``python -m pytest`` resolves ``app_support`` to the primary and
    the suite goes green about code the branch never touched.  It is silent:
    only a module the primary does not have at all fails, and an edit to one it
    does have passes while never being run.  ``PYTHONPATH=<this checkout>``
    is the fix, and the message says so.
    """
    assert_imported_from_checkout(app_support, checkout=config.rootpath)


class Branch:
    def __init__(self, path: Path):
        self.path = path

    def git(self, *args: str) -> None:
        git(*args, cwd=self.path)

    def track(self, files: dict[str, str]) -> None:
        for name, text in files.items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        self.git("add", "-A")

    def commit(self, files: dict[str, str], message: str = "a change") -> None:
        self.track(files)
        self.git("commit", "-q", "-m", message)


@pytest.fixture
def repository_named(tmp_path):
    def make(name: str, files: dict[str, str]) -> Branch:
        repository = Branch(tmp_path / name)
        repository.path.mkdir()
        repository.git("init", "-q", "-b", "main")
        repository.git("config", "user.email", "someone@example.com")
        repository.git("config", "user.name", "Someone")
        repository.commit(files, "the base")
        return repository
    return make


@pytest.fixture
def branch_from(repository_named):
    def make(files: dict[str, str]) -> Branch:
        branch = repository_named("repo", files)
        branch.git("checkout", "-q", "-b", "branch")
        return branch
    return make


@pytest.fixture
def checkout_tracking(tmp_path):
    def make(name: str, files: dict[str, str]) -> Path:
        checkout = Branch(tmp_path / name)
        checkout.path.mkdir()
        checkout.git("init", "-q")
        checkout.track(files)
        return checkout.path
    return make


@contextlib.contextmanager
def _held_open(path: Path, *, access: int, share: int, disposition: int):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong,
                                     ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                                     ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    normal = 0x80
    handle = kernel32.CreateFileW(str(path), access, share, None, disposition, normal, None)
    assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
    still_open = [handle]

    def let_go() -> None:
        while still_open:
            kernel32.CloseHandle(still_open.pop())

    try:
        yield let_go
    finally:
        let_go()


@pytest.fixture
def held_open():
    return _held_open


@pytest.fixture
def desktop_of_its_own():
    desktop = DesktopOfItsOwn()
    try:
        yield desktop
    finally:
        desktop.close()


@pytest.fixture
def child_on_its_own_desktop(desktop_of_its_own):
    pid = desktop_of_its_own.start([sys._base_executable, "-c", "import time; time.sleep(120)"], suspended=True)
    return desktop_of_its_own.name, pid


@pytest.fixture
def started_by_git_bash():
    programs = GitBashPrograms()
    try:
        yield programs.start
    finally:
        programs.close()


@pytest.fixture
def being_replaced():
    @contextlib.contextmanager
    def replacing(path: Path):
        with (
            _held_open(path, access=_DELETE, share=_SHARED_WITH_EVERYONE,
                       disposition=_OPEN_EXISTING) as the_replace_finishes,
            patch("app_support.file_channel.time.sleep",
                  side_effect=lambda _: the_replace_finishes()),
        ):
            yield
    return replacing


@pytest.fixture(autouse=True)
def _the_process_is_given_back():
    hooks = (sys.excepthook, threading.excepthook)
    faulthandler_was_on = faulthandler.is_enabled()
    loggers_before = set(logging.Logger.manager.loggerDict)

    yield

    sys.excepthook, threading.excepthook = hooks
    for name in set(logging.Logger.manager.loggerDict) - loggers_before:
        logger = logging.Logger.manager.loggerDict.get(name)
        if not isinstance(logger, logging.Logger):
            continue
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
    if faulthandler_was_on:
        faulthandler.enable(sys.__stderr__, all_threads=True)
    else:
        faulthandler.disable()


@pytest.fixture(autouse=True)
def _the_updaters_log_is_given_back():
    logger = logging.getLogger("production_update")
    yield
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.propagate = True
