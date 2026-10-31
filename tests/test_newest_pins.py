"""Every repo taking the newest release of each library it pins.  Every repo, package and
tag here is invented."""
from __future__ import annotations

import base64
import json
import subprocess

import pytest

from app_support.dependencies import sibling_pins_in
from app_support.newest_pins import BRANCH, GhGitHub, Move, bring_up, newest_release, newest_taken


def _pin(repo: str, tag: str) -> str:
    return f'"{repo.replace("_", "-")} @ git+https://github.com/haglio/{repo}@{tag}"'


def _pyproject(*pins: str, dev: tuple[str, ...] = ()) -> str:
    return ('[project]\nname = "someapp"\ndependencies = [\n' + "".join(f"    {pin},\n" for pin in pins) + "]\n"
            "[project.optional-dependencies]\ndev = [" + ", ".join(dev) + "]\n")


def pinned_siblings_in(text: str) -> dict[str, str]:
    return {pin.repo: pin.tag for pin in sibling_pins_in(text)}


class TestNewestTaken:
    def test_a_pin_older_than_the_newest_release_moves_and_one_at_it_stays(self):
        text = _pyproject(_pin("widgetlib", "v0.1.9"), _pin("partslib", "v0.1.4"))

        taken, moved = newest_taken(text, {"widgetlib": "v0.1.10", "partslib": "v0.1.4"})

        assert moved == [Move("widgetlib", "v0.1.9", "v0.1.10")]
        assert pinned_siblings_in(taken) == {"widgetlib": "v0.1.10", "partslib": "v0.1.4"}

    def test_a_pin_ahead_of_the_newest_release_named_is_left_where_it_is(self):
        text = _pyproject(_pin("widgetlib", "v0.1.12"))

        assert newest_taken(text, {"widgetlib": "v0.1.10"}) == (text, [])

    def test_a_pin_in_an_extra_moves_too(self):
        text = _pyproject(dev=(_pin("widgetlib", "v0.1.9"),))

        taken, moved = newest_taken(text, {"widgetlib": "v0.1.10"})

        assert moved == [Move("widgetlib", "v0.1.9", "v0.1.10")]
        assert pinned_siblings_in(taken) == {"widgetlib": "v0.1.10"}


class TestNewestRelease:
    def test_the_newest_release_is_read_by_number_and_other_tags_are_passed_over(self):
        assert newest_release(["v0.1.9", "v0.1.10", "v0.1.10-hotfix", "nightly", "v0.1.2"]) == "v0.1.10"

    def test_a_repo_with_no_release_has_no_newest(self):
        assert newest_release(["nightly"]) is None


class FakeGitHub:
    """The organization's repos, each a main holding one pyproject (or none), its tags,
    and the pull requests offered in it, all in memory."""

    def __init__(self, mains: dict[str, str | None], tags: dict[str, list[str]]):
        self.mains = dict(mains)
        self._tags = tags
        self.branches: dict[tuple[str, str], str] = {}
        self.pulls: dict[str, dict] = {}
        self.armed: list[tuple[str, int]] = []
        self.withdrawn: list[tuple[str, int, str]] = []
        self._numbers = iter(range(1, 100))

    def repos(self) -> list[str]:
        return list(self.mains)

    def main_of(self, repo):
        return ("main", f"{repo}-head")

    def file_at(self, repo, ref, path):
        text = self.branches.get((repo, ref)) if ref == BRANCH else self.mains[repo]
        return None if text is None else (text, f"blob-of-{ref}")

    def tags(self, repo):
        return self._tags.get(repo, [])

    def point(self, repo, branch, sha):
        assert sha == f"{repo}-head"
        self.branches[repo, branch] = self.mains[repo]

    def write_pyproject(self, repo, branch, text, *, blob, message):
        assert blob == f"blob-of-{repo}-head"
        self.branches[repo, branch] = text

    def open_pull(self, repo, branch):
        pull = self.pulls.get(repo)
        return pull["number"] if pull else None

    def offer(self, repo, branch, base, title, body):
        number = next(self._numbers)
        self.pulls[repo] = {"number": number, "title": title, "body": body, "base": base}
        return number

    def retitle(self, repo, number, title, body):
        self.pulls[repo].update(title=title, body=body)

    refuse_to_arm = None

    def arm(self, repo, number):
        self.armed.append((repo, number))
        return self.refuse_to_arm

    def withdraw(self, repo, number, branch, why):
        self.withdrawn.append((repo, number, why))
        del self.pulls[repo]


class TestBringUp:
    def test_a_repo_behind_on_a_library_is_offered_one_pull_request_taking_the_newest_and_it_is_armed(self):
        github = FakeGitHub(
            {"someapp": _pyproject(_pin("widgetlib", "v0.1.9"), _pin("partslib", "v0.1.3")), "widgetlib": None,
             "partslib": None},
            {"widgetlib": ["v0.1.9", "v0.1.10"], "partslib": ["v0.1.3", "v0.1.4"]})

        said = bring_up(github)

        assert pinned_siblings_in(github.branches["someapp", BRANCH]) == {"widgetlib": "v0.1.10", "partslib": "v0.1.4"}
        assert github.pulls["someapp"]["title"] == "Take widgetlib v0.1.10 and partslib v0.1.4"
        assert github.pulls["someapp"]["base"] == "main"
        assert github.armed == [("someapp", 1)]
        assert said == ["someapp: #1 Take widgetlib v0.1.10 and partslib v0.1.4"]

    def test_the_pull_request_already_open_is_brought_up_to_date_rather_than_a_second_opened(self):
        github = FakeGitHub({"someapp": _pyproject(_pin("widgetlib", "v0.1.9")), "widgetlib": None},
                            {"widgetlib": ["v0.1.10"]})
        bring_up(github)
        github._tags["widgetlib"] = ["v0.1.10", "v0.1.11"]

        bring_up(github)

        assert list(github.pulls) == ["someapp"]
        assert github.pulls["someapp"]["number"] == 1
        assert github.pulls["someapp"]["title"] == "Take widgetlib v0.1.11"
        assert github.armed == [("someapp", 1), ("someapp", 1)]

    def test_a_pull_request_already_taking_the_newest_is_left_alone(self):
        github = FakeGitHub({"someapp": _pyproject(_pin("widgetlib", "v0.1.9")), "widgetlib": None},
                            {"widgetlib": ["v0.1.10"]})
        bring_up(github)

        said = bring_up(github)

        assert github.armed == [("someapp", 1)]
        assert said == ["someapp: #1 already takes widgetlib v0.1.10"]

    def test_a_pull_request_main_no_longer_needs_is_withdrawn(self):
        github = FakeGitHub({"someapp": _pyproject(_pin("widgetlib", "v0.1.9")), "widgetlib": None},
                            {"widgetlib": ["v0.1.10"]})
        bring_up(github)
        github.mains["someapp"] = _pyproject(_pin("widgetlib", "v0.1.10"))

        said = bring_up(github)

        assert github.withdrawn == [("someapp", 1, "main takes the newest release of each library already.")]
        assert said == ["someapp: withdrew #1, as main takes the newest release of each library already"]

    def test_a_pull_request_github_would_not_set_to_ship_by_itself_says_so(self):
        github = FakeGitHub({"someapp": _pyproject(_pin("widgetlib", "v0.1.9")), "widgetlib": None},
                            {"widgetlib": ["v0.1.10"]})
        github.refuse_to_arm = "auto-merge is not allowed for this repository"

        assert bring_up(github) == [
            ("someapp: #1 Take widgetlib v0.1.10 (not set to ship by itself: auto-merge is not allowed for this "
             "repository)")]

    def test_a_repo_taking_the_newest_of_each_or_pinning_nothing_is_left_alone(self):
        github = FakeGitHub({"someapp": _pyproject(_pin("widgetlib", "v0.1.10")), "plainapp": _pyproject(),
                             "widgetlib": None}, {"widgetlib": ["v0.1.10"]})

        assert bring_up(github) == []
        assert github.pulls == {}


class TestGhGitHub:
    def _github(self, answers: dict[tuple[str, ...], str | Exception]):
        asked = []

        def run(command):
            asked.append(tuple(command))
            answer = answers.get(tuple(command), "")
            if isinstance(answer, Exception):
                raise answer
            return answer

        return GhGitHub("someorg", run=run), asked

    def test_a_file_at_a_revision_is_read_off_the_contents_api(self):
        listing = json.dumps({"content": base64.b64encode(b"GRAY = 1\n").decode("ascii"), "sha": "b1"})
        github, _ = self._github({("gh", "api", "repos/someorg/someapp/contents/pyproject.toml?ref=main"): listing})

        assert github.file_at("someapp", "main", "pyproject.toml") == ("GRAY = 1\n", "b1")

    def test_a_file_github_does_not_have_is_none(self):
        missing = subprocess.CalledProcessError(1, "gh", stderr="gh: Not Found (HTTP 404)")
        github, _ = self._github({("gh", "api", "repos/someorg/someapp/contents/pyproject.toml?ref=main"): missing})

        assert github.file_at("someapp", "main", "pyproject.toml") is None

    def test_any_other_failure_of_github_is_raised(self):
        refused = subprocess.CalledProcessError(1, "gh", stderr="gh: Bad credentials (HTTP 401)")
        github, _ = self._github({("gh", "api", "repos/someorg/someapp/contents/pyproject.toml?ref=main"): refused})

        with pytest.raises(subprocess.CalledProcessError):
            github.file_at("someapp", "main", "pyproject.toml")

    def test_a_branch_that_does_not_exist_yet_is_made_and_one_that_does_is_moved(self):
        missing = subprocess.CalledProcessError(1, "gh", stderr="gh: Not Found (HTTP 404)")
        github, asked = self._github({("gh", "api", f"repos/someorg/someapp/git/ref/heads/{BRANCH}"): missing})

        github.point("someapp", BRANCH, "c1")

        assert asked[-1] == ("gh", "api", "-X", "POST", "repos/someorg/someapp/git/refs",
                             "-f", f"ref=refs/heads/{BRANCH}", "-f", "sha=c1")

    def test_a_branch_that_exists_is_moved_by_force(self):
        github, asked = self._github({("gh", "api", f"repos/someorg/someapp/git/ref/heads/{BRANCH}"):
                                      json.dumps({"object": {"sha": "c0"}})})

        github.point("someapp", BRANCH, "c1")

        assert asked[-1] == ("gh", "api", "-X", "PATCH", f"repos/someorg/someapp/git/refs/heads/{BRANCH}",
                             "-f", "sha=c1", "-F", "force=true")

    def test_a_refusal_to_set_a_pull_request_to_ship_by_itself_is_handed_back(self):
        refused = subprocess.CalledProcessError(1, "gh", stderr="auto-merge is not allowed\n")
        github, _ = self._github({("gh", "pr", "merge", "7", "--repo", "someorg/someapp", "--auto"): refused})

        assert github.arm("someapp", 7) == "auto-merge is not allowed"

    def test_the_repos_are_the_unarchived_ones_the_organization_lists(self):
        github, _ = self._github({("gh", "api", "--paginate", "orgs/someorg/repos?per_page=100",
                                   "--jq", ".[] | select(.archived | not) | .name"): "someapp\nwidgetlib\n"})

        assert github.repos() == ["someapp", "widgetlib"]

    def test_a_repos_main_is_its_default_branch_and_where_that_branch_stands(self):
        github, _ = self._github({
            ("gh", "api", "repos/someorg/someapp"): json.dumps({"default_branch": "trunk"}),
            ("gh", "api", "repos/someorg/someapp/git/ref/heads/trunk"): json.dumps({"object": {"sha": "c9"}})})

        assert github.main_of("someapp") == ("trunk", "c9")

    def test_an_empty_repo_has_no_main(self):
        missing = subprocess.CalledProcessError(1, "gh", stderr="gh: Not Found (HTTP 404)")
        github, _ = self._github({
            ("gh", "api", "repos/someorg/someapp"): json.dumps({"default_branch": "main"}),
            ("gh", "api", "repos/someorg/someapp/git/ref/heads/main"): missing})

        assert github.main_of("someapp") is None

    def test_a_file_is_written_onto_the_branch_over_the_copy_it_replaces(self):
        github, asked = self._github({})

        github.write_pyproject("someapp", BRANCH, "GRAY = 2\n", blob="b1", message="Take widgetlib v0.1.10")

        assert asked == [("gh", "api", "-X", "PUT", "repos/someorg/someapp/contents/pyproject.toml",
                          "-f", "message=Take widgetlib v0.1.10",
                          "-f", f"content={base64.b64encode(b'GRAY = 2' + bytes([10])).decode('ascii')}",
                          "-f", "sha=b1", "-f", f"branch={BRANCH}")]

    def test_the_open_pull_request_from_the_branch_is_found_by_its_number(self):
        github, _ = self._github({("gh", "api", f"repos/someorg/someapp/pulls?head=someorg:{BRANCH}&state=open"):
                                  json.dumps([{"number": 12}])})

        assert github.open_pull("someapp", BRANCH) == 12

    def test_a_branch_with_no_open_pull_request_has_none(self):
        github, _ = self._github({("gh", "api", f"repos/someorg/someapp/pulls?head=someorg:{BRANCH}&state=open"):
                                  "[]"})

        assert github.open_pull("someapp", BRANCH) is None

    def test_a_pull_request_is_offered_from_the_branch_to_main_and_retitled_as_it_moves(self):
        github, asked = self._github({("gh", "api", "-X", "POST", "repos/someorg/someapp/pulls",
                                       "-f", "title=Take widgetlib v0.1.10", "-f", f"head={BRANCH}",
                                       "-f", "base=main", "-f", "body=Moves it."): json.dumps({"number": 13})})

        assert github.offer("someapp", BRANCH, "main", "Take widgetlib v0.1.10", "Moves it.") == 13
        github.retitle("someapp", 13, "Take widgetlib v0.1.11", "Moves it again.")
        assert asked[-1] == ("gh", "api", "-X", "PATCH", "repos/someorg/someapp/pulls/13",
                             "-f", "title=Take widgetlib v0.1.11", "-f", "body=Moves it again.")

    def test_a_pull_request_another_landing_opened_a_moment_before_is_the_one_used(self):
        taken = subprocess.CalledProcessError(1, "gh", stderr="gh: A pull request already exists (HTTP 422)")
        github, _ = self._github({
            ("gh", "api", "-X", "POST", "repos/someorg/someapp/pulls", "-f", "title=Take widgetlib v0.1.10",
             "-f", f"head={BRANCH}", "-f", "base=main", "-f", "body=Moves it."): taken,
            ("gh", "api", f"repos/someorg/someapp/pulls?head=someorg:{BRANCH}&state=open"):
                json.dumps([{"number": 14}])})

        assert github.offer("someapp", BRANCH, "main", "Take widgetlib v0.1.10", "Moves it.") == 14

    def test_a_branch_another_landing_made_a_moment_before_is_moved_instead(self):
        missing = subprocess.CalledProcessError(1, "gh", stderr="gh: Not Found (HTTP 404)")
        taken = subprocess.CalledProcessError(1, "gh", stderr="gh: Reference already exists (HTTP 422)")
        github, asked = self._github({
            ("gh", "api", f"repos/someorg/someapp/git/ref/heads/{BRANCH}"): missing,
            ("gh", "api", "-X", "POST", "repos/someorg/someapp/git/refs", "-f", f"ref=refs/heads/{BRANCH}",
             "-f", "sha=c1"): taken})

        github.point("someapp", BRANCH, "c1")

        assert asked[-1] == ("gh", "api", "-X", "PATCH", f"repos/someorg/someapp/git/refs/heads/{BRANCH}",
                             "-f", "sha=c1", "-F", "force=true")

    def test_a_pull_request_withdrawn_says_why_closes_and_takes_its_branch_with_it(self):
        github, asked = self._github({})

        github.withdraw("someapp", 13, BRANCH, "main takes the newest release of each library already.")

        assert asked == [
            ("gh", "api", "-X", "POST", "repos/someorg/someapp/issues/13/comments",
             "-f", "body=main takes the newest release of each library already."),
            ("gh", "api", "-X", "PATCH", "repos/someorg/someapp/pulls/13", "-f", "state=closed"),
            ("gh", "api", "-X", "DELETE", f"repos/someorg/someapp/git/refs/heads/{BRANCH}")]

    def test_the_newest_release_comes_from_the_tags_the_repository_lists(self):
        listing = "a1\trefs/tags/v0.1.9\nb2\trefs/tags/v0.1.10\n"
        github, _ = self._github({("git", "ls-remote", "--tags", "--refs", "https://github.com/someorg/widgetlib.git"):
                                  listing})

        assert github.tags("widgetlib") == ["v0.1.9", "v0.1.10"]
