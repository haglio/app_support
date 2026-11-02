from __future__ import annotations

from pathlib import Path

import pytest

from app_support.misnamed_tests import (
    assert_every_file_holding_tests_is_named_test,
    files_holding_tests_pytest_never_runs,
)


def _tests(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / "tests" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return tmp_path / "tests"


@pytest.mark.parametrize("source", [
    "def test_one():\n    assert True\n",
    "async def test_one():\n    assert True\n",
    "class TestOne:\n    def test_two(self):\n        assert True\n",
])
def test_a_file_holding_tests_under_another_name_is_found(tmp_path: Path, source: str):
    tests = _tests(tmp_path, "features.py", source)

    assert files_holding_tests_pytest_never_runs(tests) == [tests / "features.py"]


def test_one_in_a_folder_below_is_found(tmp_path: Path):
    tests = _tests(tmp_path, "integration/features.py", "def test_one():\n    assert True\n")

    assert files_holding_tests_pytest_never_runs(tests) == [tests / "integration" / "features.py"]


@pytest.mark.parametrize(("name", "source"), [
    ("test_features.py", "def test_one():\n    assert True\n"),
    ("helpers.py", "def tests_to_run():\n    return []\n"),
    ("helpers.py", "def make_one():\n    return 1\n"),
    ("helpers.py", "class TestDouble:\n    def answer(self):\n        return 1\n"),
    ("conftest.py", "def pytest_configure(config):\n    config.first = True\n"),
])
def test_what_pytest_runs_and_what_holds_no_tests_are_left_alone(tmp_path: Path, name: str, source: str):
    assert files_holding_tests_pytest_never_runs(_tests(tmp_path, name, source)) == []


def test_the_refusal_names_the_file(tmp_path: Path):
    tests = _tests(tmp_path, "features.py", "def test_one():\n    assert True\n")

    with pytest.raises(AssertionError, match=r"features[.]py"):
        assert_every_file_holding_tests_is_named_test(tests)


def test_a_repo_with_no_tests_folder_has_nothing_misnamed(tmp_path: Path):
    assert_every_file_holding_tests_is_named_test(tmp_path / "tests")
