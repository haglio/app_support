"""No test may hand the next one a piece of the process.

The three things this package installs are all process-wide: the two exception
hooks, faulthandler's stream, and a rotating file handler on a named logger.
A test that installs one and walks away changes what every later test runs
under -- a thread that dies is written to a file in a `tmp_path` pytest has
already deleted instead of reaching pytest's own reporting, and a native crash
prints no traceback at all because faulthandler was switched off on the way out.

These read whatever the tests before them left behind, so they are green on
their own and red exactly when something has leaked.
"""
from __future__ import annotations

import faulthandler
import logging
import sys
import threading


def test_no_test_before_this_left_this_packages_hooks_installed():
    """Not "the default hook" — pytest installs its own, which is the point:
    an app_support hook sitting there is one pytest is no longer holding."""
    for hook in (sys.excepthook, threading.excepthook):
        assert getattr(hook, "__module__", None) != "app_support.logging_utils", (
            f"{hook!r} is still installed — a thread that dies from here on is "
            "written to some finished test's log file instead of being reported"
        )


def test_faulthandler_is_still_watching_for_the_next_native_crash():
    assert faulthandler.is_enabled()


def test_no_test_before_this_left_a_log_file_open():
    """pytest's own capture handlers are its business; a file handler on a named
    logger is ours, and it is holding a file in a directory already deleted."""
    still_open = sorted(
        f"{name} -> {handler.baseFilename}"
        for name, logger in logging.Logger.manager.loggerDict.items()
        if isinstance(logger, logging.Logger)
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler)
    )

    assert not still_open, f"log files still open: {still_open}"
