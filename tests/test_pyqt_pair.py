from __future__ import annotations

from pathlib import Path

import pytest

from app_support.pyqt_pair import assert_pyqt6_and_its_webengine_are_held_to_one_minor


class TestPyqt6AndItsWebengine:
    def _pyproject(self, tmp_path: Path, *dependencies: str) -> Path:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(f'[project]\nname = "someapp"\ndependencies = {list(dependencies)!r}\n'.replace("'", '"'),
                             encoding="utf-8")
        return pyproject

    @pytest.mark.parametrize("dependencies", [
        ("PyQt6>=6.11,<6.12", "PyQt6-WebEngine>=6.11,<6.12"),
        ("PyQt6>=6.11.2,<6.12", "pyqt6_webengine>=6.11,<6.12"),
        ("PyQt6>=6,<7",),
        (),
    ])
    def test_one_minor_for_both_or_no_web_engine_at_all_passes(self, tmp_path: Path, dependencies: tuple[str, ...]):
        assert_pyqt6_and_its_webengine_are_held_to_one_minor(self._pyproject(tmp_path, *dependencies))

    @pytest.mark.parametrize("dependencies", [
        ("PyQt6>=6.11,<6.12", "PyQt6-WebEngine>=6.10,<6.11"),
        ("PyQt6>=6,<7", "PyQt6-WebEngine>=6.11,<6.12"),
        ("PyQt6>=6.11,<6.12", "PyQt6-WebEngine>=6.11,<6.13"),
        ("PyQt6-WebEngine>=6.11,<6.12",),
    ])
    def test_anything_pip_could_pair_two_minors_under_is_refused(self, tmp_path: Path, dependencies: tuple[str, ...]):
        with pytest.raises(AssertionError, match="one minor"):
            assert_pyqt6_and_its_webengine_are_held_to_one_minor(self._pyproject(tmp_path, *dependencies))
