"""Every repo taking the newest release of each library it pins.  Every repo, package and
tag here is invented."""
from __future__ import annotations

import base64
import json
import subprocess

import pytest

from app_support.dependencies import sibling_pins_in
from app_support.newest_pins import (
    BRANCH,
    IN_MERGE_QUEUE,
    GhGitHub,
    Move,
    bring_up,
    main,
    newest_release,
    newest_taken,
)


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
        self.commits: dict[str, str] = {}
        self.queued: set[tuple[str, int]] = set()
        self.refuse_to_move: dict[str, Exception] = {}
        self.pulls: dict[str, dict] = {}
        self.armed: list[tuple[str, int]] = []
        self.withdrawn: list[tuple[str, int, str]] = []
        self._numbers = iter(range(1, 100))

    def repos(self) -> list[str]:
        return list(self.mains)

    def main_of(self, repo):
        return ("main", f"{repo}-head")

    def file_at(self, repo, ref, path):
        return self.branches.get((repo, ref)) if ref == BRANCH else self.mains[repo]

    def tags(self, repo):
        return self._tags.get(repo, [])

    def in_merge_queue(self, repo, number):
        return (repo, number) in self.queued

    def point(self, repo, branch, sha):
        assert not any(queued == repo for queued, _ in self.queued)
        if repo in self.refuse_to_move:
            raise self.refuse_to_move[repo]
        if sha == f"{repo}-head":
            self.pulls.pop(repo, None)
            self.branches[repo, branch] = self.mains[repo]
        else:
            self.branches[repo, branch] = self.commits[sha]

    def commit_pyproject(self, repo, parent, text, *, message):
        assert parent == f"{repo}-head"
        sha = f"commit-{len(self.commits)}"
        self.commits[sha] = text
        return sha

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

        said = bring_up(github).said

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

        said = bring_up(github).said

        assert github.armed == [("someapp", 1)]
        assert said == ["someapp: #1 already takes widgetlib v0.1.10"]

    def test_a_pull_request_on_its_way_to_main_is_left_to_ship_and_the_newer_release_waits(self):
        github = FakeGitHub({"someapp": _pyproject(_pin("widgetlib", "v0.1.9")), "widgetlib": None},
                            {"widgetlib": ["v0.1.10"]})
        bring_up(github)
        offered = github.branches["someapp", BRANCH]
        github.queued.add(("someapp", 1))
        github._tags["widgetlib"] = ["v0.1.10", "v0.1.11"]

        said = bring_up(github).said

        assert github.branches["someapp", BRANCH] == offered
        assert said == ["someapp: #1 is on its way to main, so widgetlib v0.1.11 waits for the next release"]

    def test_a_pull_request_main_no_longer_needs_is_withdrawn(self):
        github = FakeGitHub({"someapp": _pyproject(_pin("widgetlib", "v0.1.9")), "widgetlib": None},
                            {"widgetlib": ["v0.1.10"]})
        bring_up(github)
        github.mains["someapp"] = _pyproject(_pin("widgetlib", "v0.1.10"))

        said = bring_up(github).said

        assert github.withdrawn == [("someapp", 1, "main takes the newest release of each library already.")]
        assert said == ["someapp: withdrew #1, as main takes the newest release of each library already"]

    def test_a_pull_request_github_would_not_set_to_ship_by_itself_says_so(self):
        github = FakeGitHub({"someapp": _pyproject(_pin("widgetlib", "v0.1.9")), "widgetlib": None},
                            {"widgetlib": ["v0.1.10"]})
        github.refuse_to_arm = "auto-merge is not allowed for this repository"

        assert bring_up(github).said == [
            ("someapp: #1 Take widgetlib v0.1.10 (not set to ship by itself: auto-merge is not allowed for this "
             "repository)")]

    def test_a_repo_github_refuses_is_named_in_github_s_words_and_the_rest_are_still_offered(self):
        github = FakeGitHub({"firstapp": _pyproject(_pin("widgetlib", "v0.1.9")),
                             "secondapp": _pyproject(_pin("widgetlib", "v0.1.9")), "widgetlib": None},
                            {"widgetlib": ["v0.1.10"]})
        github.refuse_to_move["firstapp"] = subprocess.CalledProcessError(
            1, "gh", stderr="gh: Reference update failed (HTTP 422)")

        brought = bring_up(github)

        assert brought.said == ["secondapp: #1 Take widgetlib v0.1.10"]
        assert brought.failed == ["firstapp: gh: Reference update failed (HTTP 422)"]

    def test_a_run_that_could_not_offer_a_repo_fails_after_saying_all_of_it(self, capsys):
        github = FakeGitHub({"firstapp": _pyproject(_pin("widgetlib", "v0.1.9")),
                             "secondapp": _pyproject(_pin("widgetlib", "v0.1.9")), "widgetlib": None},
                            {"widgetlib": ["v0.1.10"]})
        github.refuse_to_move["firstapp"] = subprocess.CalledProcessError(
            1, "gh", stderr="gh: Reference update failed (HTTP 422)")

        assert main([], github=github) == 1
        said = capsys.readouterr().out
        assert "secondapp: #1 Take widgetlib v0.1.10" in said
        assert "firstapp: gh: Reference update failed (HTTP 422)" in said

    def test_a_run_that_offered_every_repo_succeeds(self):
        github = FakeGitHub({"someapp": _pyproject(_pin("widgetlib", "v0.1.9")), "widgetlib": None},
                            {"widgetlib": ["v0.1.10"]})

        assert main([], github=github) == 0

    def test_a_repo_taking_the_newest_of_each_or_pinning_nothing_is_left_alone(self):
        github = FakeGitHub({"someapp": _pyproject(_pin("widgetlib", "v0.1.10")), "plainapp": _pyproject(),
                             "widgetlib": None}, {"widgetlib": ["v0.1.10"]})

        assert bring_up(github).said == []
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
        listing = json.dumps({"content": base64.b64encode(b"GRAY = 1\n").decode("ascii")})
        github, _ = self._github({("gh", "api", "repos/someorg/someapp/contents/pyproject.toml?ref=main"): listing})

        assert github.file_at("someapp", "main", "pyproject.toml") == "GRAY = 1\n"

    def test_a_file_github_does_not_have_is_none(self):
        missing = subprocess.CalledProcessError(1, "gh", stderr="gh: Not Found (HTTP 404)")
        github, _ = self._github({("gh", "api", "repos/someorg/someapp/contents/pyproject.toml?ref=main"): missing})

        assert github.file_at("someapp", "main", "pyproject.toml") is None

    def test_any_other_failure_of_github_is_raised(self):
        refused = subprocess.CalledProcessError(1, "gh", stderr="gh: Bad credentials (HTTP 401)")
        github, _ = self._github({("gh", "api", "repos/someorg/someapp/contents/pyproject.toml?ref=main"): refused})

        with pytest.raises(subprocess.CalledProcessError):
            github.file_at("someapp", "main", "pyproject.toml")

    def test_github_says_whether_a_pull_request_is_in_the_merge_queue(self):
        def queued(answer: bool) -> str:
            return json.dumps({"data": {"repository": {"pullRequest": {"isInMergeQueue": answer}}}})

        def asked_about(number: int) -> tuple[str, ...]:
            return ("gh", "api", "graphql", "-f", f"query={IN_MERGE_QUEUE}", "-f", "org=someorg", "-f", "repo=someapp",
                    "-F", f"number={number}")

        github, _ = self._github({asked_about(7): queued(True), asked_about(8): queued(False)})

        assert github.in_merge_queue("someapp", 7) is True
        assert github.in_merge_queue("someapp", 8) is False

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

    def test_a_commit_changes_only_the_pyproject_on_top_of_its_parent(self):
        github, asked = self._github({
            ("gh", "api", "repos/someorg/someapp/git/commits/c1"): json.dumps({"tree": {"sha": "t1"}}),
            ("gh", "api", "-X", "POST", "repos/someorg/someapp/git/trees", "-f", "base_tree=t1",
             "-f", "tree[][path]=pyproject.toml", "-f", "tree[][mode]=100644", "-f", "tree[][type]=blob",
             "-f", "tree[][content]=GRAY = 2\n"): json.dumps({"sha": "t2"}),
            ("gh", "api", "-X", "POST", "repos/someorg/someapp/git/commits", "-f", "message=Take widgetlib v0.1.10",
             "-f", "tree=t2", "-f", "parents[]=c1"): json.dumps({"sha": "c2"})})

        assert github.commit_pyproject("someapp", "c1", "GRAY = 2\n", message="Take widgetlib v0.1.10") == "c2"
        assert len(asked) == 3

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
