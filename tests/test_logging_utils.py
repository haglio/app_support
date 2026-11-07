from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import sys
import threading
from pathlib import Path

from app_support.logging_utils import (
    configure_logging,
    enable_faulthandler,
    install_exception_logging,
)


class TestConfigureLogging:
    def test_the_caller_gets_a_logger_it_can_log_through(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        logger = configure_logging("test.cfg.basic", log_file)
        assert isinstance(logger, logging.Logger)

    def test_creates_log_directory(self, tmp_path: Path):
        log_file = tmp_path / "subdir" / "app.log"
        configure_logging("test.cfg.mkdir", log_file)
        assert log_file.parent.exists()

    def test_file_handler_attached(self, tmp_path: Path):
        log_file = tmp_path / "app.log"
        logger = configure_logging("test.cfg.filehandler", log_file)
        handler_types = [type(h) for h in logger.handlers]
        assert logging.handlers.RotatingFileHandler in handler_types

    def test_no_console_handler_by_default(self, tmp_path: Path):
        log_file = tmp_path / "app.log"
        logger = configure_logging("test.cfg.noconsole", log_file)
        for h in logger.handlers:
            assert not isinstance(h, logging.StreamHandler) or isinstance(
                h, logging.handlers.RotatingFileHandler
            )

    def test_console_handler_added_when_requested(self, tmp_path: Path):
        log_file = tmp_path / "app.log"
        logger = configure_logging("test.cfg.console", log_file, console=True)
        stream_handlers = [
            h for h in logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(stream_handlers) == 1

    def test_existing_handlers_replaced_on_reconfigure(self, tmp_path: Path):
        log_file = tmp_path / "app.log"
        name = "test.cfg.reconfigure"
        configure_logging(name, log_file)
        configure_logging(name, log_file)
        logger = logging.getLogger(name)
        assert len(logger.handlers) == 1

    def test_logger_level_is_info(self, tmp_path: Path):
        log_file = tmp_path / "app.log"
        logger = configure_logging("test.cfg.level", log_file)
        assert logger.level == logging.INFO

    def test_propagation_disabled(self, tmp_path: Path):
        log_file = tmp_path / "app.log"
        logger = configure_logging("test.cfg.propagate", log_file)
        assert not logger.propagate

    def test_writes_to_log_file(self, tmp_path: Path):
        log_file = tmp_path / "app.log"
        logger = configure_logging("test.cfg.write", log_file)
        logger.info("hello test")
        for h in logger.handlers:
            h.flush()
        assert log_file.exists()
        assert "hello test" in log_file.read_text(encoding="utf-8")


class TestInstallExceptionLogging:
    def test_replaces_sys_excepthook(self, tmp_path: Path):
        original = sys.excepthook
        log_file = tmp_path / "exc.log"
        logger = configure_logging("test.exc.syshook", log_file)
        try:
            install_exception_logging(logger)
            assert sys.excepthook is not original
        finally:
            sys.excepthook = original

    def test_replaces_threading_excepthook(self, tmp_path: Path):
        original = threading.excepthook
        log_file = tmp_path / "exc.log"
        logger = configure_logging("test.exc.threadhook", log_file)
        try:
            install_exception_logging(logger)
            assert threading.excepthook is not original
        finally:
            threading.excepthook = original

    def test_sys_excepthook_ignores_keyboard_interrupt(self, tmp_path: Path):
        log_file = tmp_path / "exc.log"
        logger = configure_logging("test.exc.ki", log_file)
        install_exception_logging(logger)
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        for h in logger.handlers:
            h.flush()
        content = log_file.read_text(encoding="utf-8")
        assert "KeyboardInterrupt" not in content

    def test_an_exception_that_kills_a_real_thread_reaches_the_log_a_hook_merely_installed_could_still_swallow_it(
            self, tmp_path: Path):
        log_file = tmp_path / "exc.log"
        logger = configure_logging("test.exc.threadcrash", log_file)
        install_exception_logging(logger)

        def die():
            raise RuntimeError("boom in worker")

        worker = threading.Thread(target=die, name="worker-under-test")
        worker.start()
        worker.join()
        for h in logger.handlers:
            h.flush()
        content = log_file.read_text(encoding="utf-8")
        assert "boom in worker" in content
        assert "thread:worker-under-test" in content

    def test_sys_excepthook_logs_other_exceptions(self, tmp_path: Path):
        log_file = tmp_path / "exc.log"
        logger = configure_logging("test.exc.other", log_file)
        install_exception_logging(logger)
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            exc_type, exc, tb = sys.exc_info()
        sys.excepthook(exc_type, exc, tb)
        for h in logger.handlers:
            h.flush()
        assert "boom" in log_file.read_text(encoding="utf-8")


class TestEnableFaulthandler:
    def test_a_log_directory_that_does_not_exist_yet_is_made_before_the_first_write(self, tmp_path: Path):
        # CPython's faulthandler writes a hard crash's C-level traceback straight to this handle.
        log_file = tmp_path / "subdir" / "fault.log"

        handle = enable_faulthandler(log_file)
        try:
            assert log_file.parent.is_dir()
            assert not handle.closed
        finally:
            handle.close()

    def test_arms_faulthandler_not_just_the_file(self, tmp_path: Path):
        faulthandler.disable()  # pytest arms it for its own crash report, and would pass this with the function doing nothing
        log_file = tmp_path / "fault.log"

        handle = enable_faulthandler(log_file)
        try:
            assert faulthandler.is_enabled()
        finally:
            handle.close()

    def test_appends_rather_than_truncating_so_the_last_crash_survives_while_the_next_is_diagnosed(self, tmp_path: Path):
        log_file = tmp_path / "fault.log"
        log_file.write_text("earlier crash\n", encoding="utf-8")

        handle = enable_faulthandler(log_file)
        try:
            handle.write("later\n")
            handle.flush()
        finally:
            handle.close()

        assert log_file.read_text(encoding="utf-8") == "earlier crash\nlater\n"
