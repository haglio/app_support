from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app_support.releases import is_urgent, main, makes_a_release

_PYPROJECT = ('[project]\nname = "widgetlib"\ndependencies = ["numpy>=2,<3"]\n'
              '[project.optional-dependencies]\ndev = ["{dev}"]\n'
              '[tool.setuptools.packages.find]\ninclude = ["widgetlib*"]\n')


def _pyproject(dev: str = "partslib @ git+https://github.com/haglio/partslib@v0.1.4") -> str:
    return _PYPROJECT.format(dev=dev)


class TestMakesARelease:
    def test_a_change_to_the_package_makes_a_release(self):
        assert makes_a_release(["widgetlib/core.py"], _pyproject(), _pyproject())

    def test_a_change_only_to_tests_docs_and_tools_makes_none(self):
        assert not makes_a_release(["tests/test_core.py", "README.md", "tools/build.py"], _pyproject(), _pyproject())

    def test_moving_only_the_pin_its_own_tests_install_makes_none(self):
        newer = _pyproject(dev="partslib @ git+https://github.com/haglio/partslib@v0.1.5")

        assert not makes_a_release(["pyproject.toml"], _pyproject(), newer)

    def test_a_change_to_what_an_app_installs_with_it_makes_a_release(self):
        newer = _pyproject().replace("numpy>=2,<3", "numpy>=2.4,<3")

        assert makes_a_release(["pyproject.toml"], _pyproject(), newer)


class TestIsUrgent:
    def test_an_urgent_trailer_on_any_landed_commit_makes_it_urgent(self):
        assert is_urgent(["Tidy a test", "Stop the crash at start\n\nUrgent: Fun Time will not open\n"])

    def test_the_word_urgent_in_a_sentence_does_not(self):
        assert not is_urgent(["Say why the urgent row is red\n\nThe urgent: label was cut off.\n"])


def _git(checkout: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-C", str(checkout), *arguments], check=True, capture_output=True,
                          encoding="utf-8").stdout


def _commit(checkout: Path, path: str, text: str, message: str) -> None:
    (checkout / path).parent.mkdir(parents=True, exist_ok=True)
    (checkout / path).write_text(text, encoding="utf-8")
    _git(checkout, "add", path)
    _git(checkout, "-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-q", "-m", message)


@pytest.fixture
def library(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, "pyproject.toml", _pyproject(), "Start")
    _commit(tmp_path, "widgetlib/core.py", "ANSWER = 1\n", "Add the core")
    _git(tmp_path, "tag", "v0.1.2")
    return tmp_path


class TestMain:
    def test_a_landing_that_changed_only_tests_says_no_release(self, library, capsys):
        _commit(library, "tests/test_core.py", "def test_it(): pass\n", "Test the core")

        assert main(["--checkout", str(library)]) == 0
        assert capsys.readouterr().out == "release=false\nurgent=false\n"

    def test_a_landing_that_changed_the_package_says_release_and_whether_it_is_urgent(self, library, capsys):
        _commit(library, "widgetlib/core.py", "ANSWER = 2\n", "Fix the answer\n\nUrgent: it crashed")

        main(["--checkout", str(library)])

        assert capsys.readouterr().out == "release=true\nurgent=true\n"

    def test_a_library_never_released_says_release(self, tmp_path, capsys):
        _git(tmp_path, "init", "-q")
        _commit(tmp_path, "README.md", "widgetlib\n", "Start")

        main(["--checkout", str(tmp_path)])

        assert capsys.readouterr().out == "release=true\nurgent=false\n"
