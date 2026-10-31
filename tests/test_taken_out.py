"""What a change takes out of a library, and which open branch of another repo
still uses it.  Every package, module and name here is invented."""
from __future__ import annotations

import json

import pytest

from app_support.git_files import files_at
from app_support.taken_out import (
    OpenBranch,
    StillUsed,
    broken_by,
    fetched,
    main,
    names_taken_out,
    open_on_github,
    still_used,
    surface,
)

PACKAGE_FIND = '[tool.setuptools.packages.find]\ninclude = ["widgetlib*"]\n'


class TestSurface:
    def test_a_package_answers_to_its_modules_and_to_each_name_one_defines(self):
        sources = {
            "widgetlib/__init__.py": "",
            "widgetlib/colors.py": "GRAY = 1\n",
            "widgetlib/parts/__init__.py": "from widgetlib.colors import GRAY\n",
        }

        assert surface(sources) == {
            "widgetlib", "widgetlib.colors", "widgetlib.colors.GRAY", "widgetlib.parts", "widgetlib.parts.GRAY"}


class TestBrokenBy:
    TAKEN_OUT = frozenset({"widgetlib.parts", "widgetlib.colors.GRAY"})

    def test_a_use_of_a_name_taken_out_breaks_on_that_name(self):
        assert broken_by("widgetlib.colors.GRAY.value", self.TAKEN_OUT) == "widgetlib.colors.GRAY"

    def test_a_use_of_anything_in_a_module_taken_out_breaks_on_the_module(self):
        assert broken_by("widgetlib.parts.Lever", self.TAKEN_OUT) == "widgetlib.parts"

    def test_a_use_of_what_stays_breaks_on_nothing(self):
        assert broken_by("widgetlib.colors.RED", self.TAKEN_OUT) is None


class TestNamesTakenOut:
    def test_what_a_branch_removes_from_the_package_is_taken_out_and_nothing_else(self, branch_from):
        library = branch_from({
            "pyproject.toml": PACKAGE_FIND,
            "widgetlib/__init__.py": "",
            "widgetlib/colors.py": "GRAY = 1\nRED = 2\n",
            "widgetlib/parts.py": "class Lever: pass\n",
            "tests/test_colors.py": "CHECKED = 1\n",
        })
        library.commit({"widgetlib/colors.py": "GRAY = 1\n", "tests/test_colors.py": ""})
        library.git("rm", "-q", "widgetlib/parts.py")
        library.git("commit", "-q", "-m", "take out the parts")

        assert names_taken_out(library.path, "main", "HEAD") == {
            "widgetlib.colors.RED", "widgetlib.parts", "widgetlib.parts.Lever"}

    def test_what_main_added_since_the_branch_left_it_is_not_taken_out_by_the_branch(self, branch_from):
        library = branch_from({"pyproject.toml": PACKAGE_FIND, "widgetlib/__init__.py": "", "widgetlib/colors.py": ""})
        library.git("checkout", "-q", "main")
        library.commit({"widgetlib/colors.py": "GRAY = 1\n"}, "main gains a name")
        library.git("checkout", "-q", "branch")
        library.commit({"widgetlib/parts.py": "class Lever: pass\n"})

        assert names_taken_out(library.path, "main", "HEAD") == set()

    def test_a_library_whose_pyproject_names_no_package_is_refused_rather_than_read_as_offering_nothing(
            self, branch_from):
        library = branch_from({"pyproject.toml": '[project]\nname = "widgetlib"\n', "widgetlib/colors.py": ""})

        with pytest.raises(ValueError, match="names no package"):
            names_taken_out(library.path, "main", "HEAD")


class TestStillUsed:
    TAKEN_OUT = frozenset({"widgetlib.parts", "widgetlib.parts.Lever"})

    def test_a_name_taken_out_that_an_open_branch_imports_is_still_used_there(self, branch_from):
        consumer = branch_from({"someapp/hud.py": "from widgetlib.colors import GRAY\n"})
        consumer.commit({"someapp/levers.py": "from widgetlib.parts import Lever\n"})
        on_main = OpenBranch("someapp", "main", "main", consumer.path)
        on_branch = OpenBranch("someapp", "claude/levers", "branch", consumer.path)

        assert still_used(self.TAKEN_OUT, [on_main, on_branch], ("widgetlib",)) == [
            StillUsed("widgetlib.parts", on_branch, ("someapp/levers.py",))]

    def test_a_module_named_in_a_settings_file_or_a_launcher_is_still_used_there(self, branch_from):
        consumer = branch_from({
            "pyproject.toml": '[tool.pytest.ini_options]\naddopts = "-p widgetlib.parts"\n',
            "Start Someapp.vbs": 'shell.Run "pythonw -m widgetlib.parts.Lever", 0\n',
            "notes.md": "widgetlib.parts was where the levers lived\n",
        })
        on_main = OpenBranch("someapp", "main", "main", consumer.path)

        assert still_used(self.TAKEN_OUT, [on_main], ("widgetlib",)) == [
            StillUsed("widgetlib.parts", on_main, ("Start Someapp.vbs", "pyproject.toml"))]

    def test_a_python_file_that_cannot_be_parsed_is_read_as_text(self, branch_from):
        consumer = branch_from({"someapp/half_written.py": 'from widgetlib.parts import (Lever\nRUN = "x"\n'})
        on_main = OpenBranch("someapp", "main", "main", consumer.path)

        assert still_used(self.TAKEN_OUT, [on_main], ("widgetlib",)) == [
            StillUsed("widgetlib.parts", on_main, ("someapp/half_written.py",))]


class TestOpenOnGitHub:
    def test_every_other_repos_main_and_open_pull_requests_are_what_is_read(self):
        answer = {"data": {"organization": {"repositories": {"nodes": [
            {"name": "widgetlib", "defaultBranchRef": {"name": "main"},
             "pullRequests": {"nodes": [{"headRefName": "claude/own", "isCrossRepository": False}]}},
            {"name": "someapp", "defaultBranchRef": {"name": "main"},
             "pullRequests": {"nodes": [
                 {"headRefName": "claude/levers", "isCrossRepository": False},
                 {"headRefName": "main", "isCrossRepository": True}]}},
            {"name": "emptyrepo", "defaultBranchRef": None, "pullRequests": {"nodes": []}},
        ]}}}}
        asked = []

        def ask(query: str) -> str:
            asked.append(query)
            return json.dumps(answer)

        assert open_on_github("someorg", but="widgetlib", ask=ask) == [("someapp", "main"), ("someapp", "claude/levers")]
        assert 'organization(login: "someorg")' in asked[0]


class TestFetched:
    def test_each_open_branch_is_fetched_into_one_repository_for_its_repo(self, branch_from, tmp_path):
        consumer = branch_from({"someapp/hud.py": "SHADE = 1\n"})
        consumer.commit({"someapp/levers.py": "PULL = 2\n"})
        into = tmp_path / "fetched"
        into.mkdir()

        branches = fetched([("someapp", "main"), ("someapp", "branch")], into,
                           url_of=lambda repo: str(consumer.path))

        assert [(branch.repo, branch.branch) for branch in branches] == [("someapp", "main"), ("someapp", "branch")]
        assert files_at(branches[1].git_dir, branches[1].commit, lambda path: True) == {
            "someapp/hud.py": "SHADE = 1\n", "someapp/levers.py": "PULL = 2\n"}


def _nobody_may_ask(query: str) -> str:
    raise AssertionError("GitHub was asked about open work when nothing was taken out")


class TestMain:
    def _library(self, repository_named, *, parts: str = "class Lever: pass\n"):
        library = repository_named("widgetlib", {
            "pyproject.toml": PACKAGE_FIND, "widgetlib/__init__.py": "", "widgetlib/parts.py": parts})
        library.git("checkout", "-q", "-b", "branch")
        return library

    def _on_github(self, *repos: str) -> str:
        return json.dumps({"data": {"organization": {"repositories": {"nodes": [
            {"name": repo, "defaultBranchRef": {"name": "main"},
             "pullRequests": {"nodes": []}} for repo in repos]}}}})

    def test_a_change_that_takes_out_nothing_asks_github_about_nothing(self, repository_named, capsys):
        library = self._library(repository_named)
        library.commit({"widgetlib/colors.py": "GRAY = 1\n"})

        assert main(["--base", "main", "--checkout", str(library.path)], ask=_nobody_may_ask) == 0
        assert "takes out no module or name" in capsys.readouterr().out

    def test_a_change_taking_out_what_another_repos_main_uses_is_refused_saying_where(
            self, repository_named, capsys):
        library = self._library(repository_named)
        library.git("rm", "-q", "widgetlib/parts.py")
        library.git("commit", "-q", "-m", "take out the parts")
        consumer = repository_named("someapp", {"someapp/levers.py": "from widgetlib.parts import Lever\n"})

        refused = main(["--base", "main", "--checkout", str(library.path)],
                       ask=lambda query: self._on_github("someapp"), url_of=lambda repo: str(consumer.path))

        said = capsys.readouterr().out
        assert refused == 1
        assert "widgetlib.parts: someapp main (someapp/levers.py)" in said

    def test_a_change_taking_out_what_nothing_uses_passes_saying_what_it_read(self, repository_named, capsys):
        library = self._library(repository_named)
        library.git("rm", "-q", "widgetlib/parts.py")
        library.git("commit", "-q", "-m", "take out the parts")
        consumer = repository_named("someapp", {"someapp/hud.py": "from widgetlib import colors\n"})

        passed = main(["--base", "main", "--checkout", str(library.path)],
                      ask=lambda query: self._on_github("someapp"), url_of=lambda repo: str(consumer.path))

        said = capsys.readouterr().out
        assert passed == 0
        assert "takes out widgetlib.parts and widgetlib.parts.Lever" in said
        assert "read 1 branch of 1 other repo, and none uses any of it" in said

    def test_a_change_that_takes_something_out_when_github_lists_no_other_repo_is_refused(
            self, repository_named, capsys):
        library = self._library(repository_named)
        library.git("rm", "-q", "widgetlib/parts.py")
        library.git("commit", "-q", "-m", "take out the parts")

        refused = main(["--base", "main", "--checkout", str(library.path)], ask=lambda query: self._on_github())

        assert refused == 2
        assert "listed no repo but this one" in capsys.readouterr().out
