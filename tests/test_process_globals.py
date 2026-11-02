from __future__ import annotations

import faulthandler
import logging
import sys
import threading


def test_no_test_before_this_left_this_packages_hooks_installed():
    for hook in (sys.excepthook, threading.excepthook):
        assert getattr(hook, "__module__", None) != "app_support.logging_utils", (
            f"{hook!r} is still installed — a thread that dies from here on is "
            "written to some finished test's log file instead of being reported"
        )


def test_faulthandler_is_still_watching_for_the_next_native_crash():
    assert faulthandler.is_enabled()


def test_no_test_before_this_left_a_log_file_open():
    still_open = sorted(
        f"{name} -> {handler.baseFilename}"
        for name, logger in logging.Logger.manager.loggerDict.items()
        if isinstance(logger, logging.Logger)
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler)
    )

    assert not still_open, f"log files still open: {still_open}"
