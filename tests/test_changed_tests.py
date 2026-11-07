from __future__ import annotations

from app_support.changed_tests import changed_test_ids

BASE = (
    "def helper():\n    return 1\n\n\n"
    "def test_one():\n    assert helper() == 1\n\n\n"
    "def test_two():\n    assert True\n"
)


def test_a_test_the_branch_added_is_named(branch_from):
    branch = branch_from({"tests/test_things.py": BASE})
    branch.commit({"tests/test_things.py": BASE + "\n\ndef test_three():\n    assert 3\n"})

    assert changed_test_ids(branch.path, "main") == ["tests/test_things.py::test_three"]


def test_a_test_the_branch_edited_is_named_and_its_neighbor_is_not(branch_from):
    branch = branch_from({"tests/test_things.py": BASE})
    branch.commit({"tests/test_things.py": BASE.replace("assert True", "assert 2 == 2")})

    assert changed_test_ids(branch.path, "main") == ["tests/test_things.py::test_two"]


def test_an_edited_helper_names_the_tests_that_call_it_and_no_others_since_one_helper_line_would_repeat_every_test_in_its_file(
        branch_from):
    branch = branch_from({"tests/test_things.py": BASE})
    branch.commit({"tests/test_things.py": BASE.replace("return 1", "return 2 - 1")})

    assert changed_test_ids(branch.path, "main") == ["tests/test_things.py::test_one"]


TWO_HELPERS_DEEP = (
    "def inner():\n    return 1\n\n\n"
    "def outer():\n    return inner()\n\n\n"
    "def test_one():\n    assert outer() == 1\n\n\n"
    "def test_two():\n    assert True\n"
)


def test_a_helper_a_helper_calls_names_the_tests_that_reach_it(branch_from):
    branch = branch_from({"tests/test_things.py": TWO_HELPERS_DEEP})
    branch.commit({"tests/test_things.py": TWO_HELPERS_DEEP.replace("return 1", "return 2 - 1")})

    assert changed_test_ids(branch.path, "main") == ["tests/test_things.py::test_one"]


WITH_A_FIXTURE = (
    "import pytest\n\n\n"
    "@pytest.fixture\ndef thing():\n    return 1\n\n\n"
    "def test_one(thing):\n    assert thing == 1\n\n\n"
    "def test_two():\n    assert True\n"
)


def test_an_edited_fixture_names_only_the_tests_that_ask_for_it(branch_from):
    branch = branch_from({"tests/test_things.py": WITH_A_FIXTURE})
    branch.commit({"tests/test_things.py": WITH_A_FIXTURE.replace("return 1", "return 2 - 1")})

    assert changed_test_ids(branch.path, "main") == ["tests/test_things.py::test_one"]


def test_a_fixture_asked_for_by_name_in_a_mark_is_still_reached(branch_from):
    marked = WITH_A_FIXTURE.replace(
        "def test_one(thing):\n    assert thing == 1",
        '@pytest.mark.usefixtures("thing")\ndef test_one():\n    assert True')
    branch = branch_from({"tests/test_things.py": marked})
    branch.commit({"tests/test_things.py": marked.replace("return 1", "return 2 - 1")})

    assert changed_test_ids(branch.path, "main") == ["tests/test_things.py::test_one"]


AUTOUSE = WITH_A_FIXTURE.replace("@pytest.fixture\n", "@pytest.fixture(autouse=True)\n")


def test_an_edited_autouse_fixture_names_every_test_in_its_file(branch_from):
    branch = branch_from({"tests/test_things.py": AUTOUSE})
    branch.commit({"tests/test_things.py": AUTOUSE.replace("return 1", "return 2 - 1")})

    assert changed_test_ids(branch.path, "main") == [
        "tests/test_things.py::test_one", "tests/test_things.py::test_two"]


BEHIND_AN_IF = "import sys\n\nif sys.platform:\n    SIZE = 1\n\n\n" + BASE


def test_module_level_code_the_walk_cannot_follow_names_every_test(branch_from):
    branch = branch_from({"tests/test_things.py": BEHIND_AN_IF})
    branch.commit({"tests/test_things.py": BEHIND_AN_IF.replace("SIZE = 1", "SIZE = 2")})

    assert changed_test_ids(branch.path, "main") == [
        "tests/test_things.py::test_one", "tests/test_things.py::test_two"]


MARKED = "import pytest\n\npytestmark = pytest.mark.slow\n\n\n" + BASE


def test_an_edited_file_wide_mark_names_every_test(branch_from):
    branch = branch_from({"tests/test_things.py": MARKED})
    branch.commit({"tests/test_things.py": MARKED.replace("mark.slow", "mark.quick")})

    assert changed_test_ids(branch.path, "main") == [
        "tests/test_things.py::test_one", "tests/test_things.py::test_two"]


def test_a_helper_the_branch_added_names_nothing_on_its_own(branch_from):
    branch = branch_from({"tests/test_things.py": BASE})
    branch.commit({"tests/test_things.py": BASE + "\n\ndef unused():\n    return 2\n"})

    assert changed_test_ids(branch.path, "main") == []


def test_a_branch_that_edits_only_production_code_names_nothing(branch_from):
    branch = branch_from({"tests/test_things.py": BASE, "app.py": "SIZE = 1\n"})
    branch.commit({"app.py": "SIZE = 2\n"})

    assert changed_test_ids(branch.path, "main") == []


def test_a_test_that_only_moved_down_the_file_names_nothing(branch_from):
    branch = branch_from({"tests/test_things.py": BASE})
    branch.commit({"tests/test_things.py": "\n\n\n" + BASE})

    assert changed_test_ids(branch.path, "main") == []


def test_a_deleted_test_file_names_nothing(branch_from):
    branch = branch_from({"tests/test_things.py": BASE})
    branch.git("rm", "-q", "tests/test_things.py")
    branch.git("commit", "-q", "-m", "retire the file")

    assert changed_test_ids(branch.path, "main") == []


def test_a_whole_new_test_file_names_all_of_its_tests(branch_from):
    branch = branch_from({"tests/test_things.py": BASE})
    branch.commit({"tests/test_more.py": "def test_a():\n    assert 1\n"})

    assert changed_test_ids(branch.path, "main") == ["tests/test_more.py::test_a"]


def test_a_test_inside_a_class_carries_its_class(branch_from):
    branch = branch_from({"tests/test_things.py": BASE})
    added = "\n\nclass TestGroup:\n    def test_inside(self):\n        assert 1\n"
    branch.commit({"tests/test_things.py": BASE + added})

    assert changed_test_ids(branch.path, "main") == ["tests/test_things.py::TestGroup::test_inside"]


def test_an_async_test_is_named_like_any_other(branch_from):
    branch = branch_from({"tests/test_things.py": BASE})
    branch.commit({"tests/test_things.py": BASE + "\n\nasync def test_later():\n    assert 1\n"})

    assert changed_test_ids(branch.path, "main") == ["tests/test_things.py::test_later"]


def test_an_import_the_branch_added_for_its_new_test_names_only_that_test(branch_from):
    branch = branch_from({"tests/test_things.py": BASE})
    branch.commit({"tests/test_things.py": "import os\n\n\n" + BASE
                   + "\n\ndef test_three():\n    assert os.sep\n"})

    assert changed_test_ids(branch.path, "main") == ["tests/test_things.py::test_three"]


def test_an_import_that_loses_a_name_names_every_test_in_its_file(branch_from):
    branch = branch_from({"tests/test_things.py": "from os import curdir, sep\n\n\n" + BASE})
    branch.commit({"tests/test_things.py": "from os import curdir\n\n\n" + BASE})

    assert changed_test_ids(branch.path, "main") == [
        "tests/test_things.py::test_one", "tests/test_things.py::test_two"]


def test_an_import_repointed_at_a_module_that_moved_names_nothing(branch_from):
    branch = branch_from({"tests/test_things.py": "from os.path import sep\n\n\n" + BASE})
    branch.commit({"tests/test_things.py": "from os import sep\n\n\n" + BASE})

    assert changed_test_ids(branch.path, "main") == []


def test_a_star_import_pointed_at_another_module_names_every_test(branch_from):
    branch = branch_from({"tests/test_things.py": "from os.path import *\n\n\n" + BASE})
    branch.commit({"tests/test_things.py": "from posixpath import *\n\n\n" + BASE})

    assert changed_test_ids(branch.path, "main") == [
        "tests/test_things.py::test_one", "tests/test_things.py::test_two"]


def test_a_rewritten_file_docstring_names_nothing(branch_from):
    branch = branch_from({"tests/test_things.py": '"""What these cover."""\n' + BASE})
    branch.commit({"tests/test_things.py": '"""What these cover, said better."""\n' + BASE})

    assert changed_test_ids(branch.path, "main") == []


WITH_A_DESCRIBED_HELPER = (
    'def helper():\n    """What this stands in for."""\n    return 1\n\n\n'
    "def test_one():\n    assert helper() == 1\n"
)


def test_a_rewritten_helper_docstring_names_nothing_since_nothing_runs_one_and_a_rename_touches_hundreds(branch_from):
    branch = branch_from({"tests/test_things.py": WITH_A_DESCRIBED_HELPER})
    branch.commit({"tests/test_things.py":
                   WITH_A_DESCRIBED_HELPER.replace("What this stands in for.", "Said better.")})

    assert changed_test_ids(branch.path, "main") == []


def test_a_curly_quote_in_the_file_does_not_stop_it_being_read(branch_from):
    quoted = BASE.replace("assert True", 'assert "“one”"')
    branch = branch_from({"tests/test_things.py": quoted})
    branch.commit({"tests/test_things.py": quoted.replace("return 1", "return 2 - 1")})

    assert changed_test_ids(branch.path, "main") == ["tests/test_things.py::test_one"]


def test_a_fixture_taken_out_of_the_file_names_the_tests_that_asked_for_it(branch_from):
    branch = branch_from({"tests/test_things.py": WITH_A_FIXTURE})
    branch.commit({"tests/test_things.py": WITH_A_FIXTURE.replace(
        "@pytest.fixture\ndef thing():\n    return 1\n\n\n", "")})

    assert changed_test_ids(branch.path, "main") == ["tests/test_things.py::test_one"]
