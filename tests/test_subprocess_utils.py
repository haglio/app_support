from __future__ import annotations

from unittest.mock import MagicMock, patch

from app_support.subprocess_utils import hidden_subprocess_kwargs


class TestHiddenSubprocessKwargs:
    def test_returns_empty_dict_on_non_windows(self):
        with patch("app_support.subprocess_utils.os.name", "posix"), \
             patch("app_support.subprocess_utils.sys.platform", "linux"):
            assert hidden_subprocess_kwargs() == {}

    def test_returns_windows_flags_on_nt(self):
        fake_startupinfo = MagicMock(dwFlags=0)
        with patch("app_support.subprocess_utils.os.name", "nt"), \
             patch("app_support.subprocess_utils.sys.platform", "win32"), \
             patch("app_support.subprocess_utils.subprocess.STARTUPINFO", return_value=fake_startupinfo), \
             patch("app_support.subprocess_utils.subprocess.STARTF_USESHOWWINDOW", 1), \
             patch("app_support.subprocess_utils.subprocess.CREATE_NO_WINDOW", 2), \
             patch("app_support.subprocess_utils.subprocess.SW_HIDE", 0):
            result = hidden_subprocess_kwargs()

        assert result["creationflags"] == 2
        assert result["startupinfo"] is fake_startupinfo
        assert fake_startupinfo.dwFlags == 1

    def test_both_suppressions_are_applied_not_just_one(self):
        # CREATE_NO_WINDOW alone leaves a child that explicitly asks for a window
        # showing one, and SW_HIDE alone still allocates the console; a console
        # flashing over the video is the bug either half on its own permits.
        fake_startupinfo = MagicMock(dwFlags=0)
        with patch("app_support.subprocess_utils.os.name", "nt"), \
             patch("app_support.subprocess_utils.sys.platform", "win32"), \
             patch("app_support.subprocess_utils.subprocess.STARTUPINFO", return_value=fake_startupinfo), \
             patch("app_support.subprocess_utils.subprocess.STARTF_USESHOWWINDOW", 1), \
             patch("app_support.subprocess_utils.subprocess.CREATE_NO_WINDOW", 2), \
             patch("app_support.subprocess_utils.subprocess.SW_HIDE", 0):
            result = hidden_subprocess_kwargs()

        assert set(result) == {"creationflags", "startupinfo"}
        assert fake_startupinfo.wShowWindow == 0
