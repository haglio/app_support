"""Shared fixtures — and the process every test here borrows a piece of.

This package's whole job is the process-wide scaffolding eight apps install, so
its tests install it too: exception hooks, faulthandler's stream, a rotating file
handler on a named logger. None of that belongs to the next test, and pytest's
own reporting is the first casualty when it is left standing.
"""
from __future__ import annotations

import faulthandler
import logging
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import app_support
from app_support.siblings import assert_imported_from_checkout


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
    """A git repository checked out on ``branch``, which forks from ``main``."""

    def __init__(self, path: Path):
        self.path = path

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.path), *args], check=True, capture_output=True)

    def commit(self, files: dict[str, str], message: str = "a change") -> None:
        for name, text in files.items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)


@pytest.fixture
def branch_from(tmp_path):
    """Make a repository whose ``main`` holds *files*, on a branch just made from it."""
    def make(files: dict[str, str]) -> Branch:
        branch = Branch(tmp_path / "repo")
        branch.path.mkdir()
        branch.git("init", "-q", "-b", "main")
        branch.git("config", "user.email", "someone@example.com")
        branch.git("config", "user.name", "Someone")
        branch.commit(files, "the base")
        branch.git("checkout", "-q", "-b", "branch")
        return branch
    return make


@pytest.fixture(autouse=True)
def _the_process_is_given_back():
    """Put back the process-wide things a test installed.

    * Both exception hooks, so a thread that dies later reaches pytest's
      reporting rather than a log file in a `tmp_path` already deleted.
    * faulthandler, so a native crash after a test that called
      ``enable_faulthandler`` still prints a traceback — the tests used to
      switch it off in their own teardown, which switched pytest's off too.
    * Every handler on a logger the test brought into being: an open
      ``RotatingFileHandler`` holds its file, and thirteen of them were being
      carried to the end of the run.
    """
    hooks = (sys.excepthook, threading.excepthook)
    faulthandler_was_on = faulthandler.is_enabled()
    loggers_before = set(logging.Logger.manager.loggerDict)

    yield

    sys.excepthook, threading.excepthook = hooks
    for name in set(logging.Logger.manager.loggerDict) - loggers_before:
        logger = logging.Logger.manager.loggerDict.get(name)
        if not isinstance(logger, logging.Logger):
            continue  # a placeholder for a child logger; it holds nothing
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
    # Unconditionally, not only when it was switched off: a test that called
    # enable_faulthandler leaves it on and pointed at a file it is about to
    # close, which is worse than off. There is no way to read back the stream it
    # had, so it goes back to the one a crash should reach.
    if faulthandler_was_on:
        faulthandler.enable(sys.__stderr__, all_threads=True)
    else:
        faulthandler.disable()
