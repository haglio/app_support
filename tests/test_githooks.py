"""Pointing a checkout's git hooks at the ones its tree defines."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app_support import githooks


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def _hooks_path(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "config", "--local", "core.hooksPath"],
                          capture_output=True, text=True, check=False).stdout.strip()


@pytest.fixture
def checkout(branch_from):
    return branch_from({"tools/githooks/pre-commit": "#!/bin/sh\n"}).path


def test_installing_points_git_at_the_hooks_the_tree_defines(checkout, monkeypatch, capsys):
    monkeypatch.chdir(checkout)

    assert githooks.main([]) == 0

    assert _hooks_path(checkout) == "tools/githooks"
    assert capsys.readouterr().out.strip() == "core.hooksPath = tools/githooks"


def test_installing_again_changes_nothing_and_says_so(checkout, monkeypatch, capsys):
    monkeypatch.chdir(checkout)
    githooks.main([])
    capsys.readouterr()

    assert githooks.main([]) == 0

    assert capsys.readouterr().out.strip() == "already installed: core.hooksPath = tools/githooks"


def test_installing_over_another_setting_says_what_it_replaced(checkout, monkeypatch, capsys):
    _git(checkout, "config", "--local", "core.hooksPath", ".hooks")
    monkeypatch.chdir(checkout)

    assert githooks.main([]) == 0

    assert _hooks_path(checkout) == "tools/githooks"
    assert capsys.readouterr().out.strip() == "core.hooksPath was '.hooks' — replaced with 'tools/githooks'"


def test_one_install_covers_every_worktree_of_the_checkout(checkout, monkeypatch, tmp_path):
    monkeypatch.chdir(checkout)
    githooks.main([])

    _git(checkout, "worktree", "add", "-q", str(tmp_path / "a-worktree"))

    assert _git(tmp_path / "a-worktree", "config", "core.hooksPath") == "tools/githooks"


def test_installing_from_inside_the_tree_installs_for_the_whole_checkout(checkout, monkeypatch):
    monkeypatch.chdir(checkout / "tools")

    assert githooks.main([]) == 0

    assert _hooks_path(checkout) == "tools/githooks"


def test_a_checkout_whose_tree_defines_no_hooks_is_refused(branch_from, monkeypatch, capsys):
    bare = branch_from({"README.md": "no hooks here\n"}).path
    monkeypatch.chdir(bare)

    assert githooks.main([]) == 1

    assert _hooks_path(bare) == ""
    top = Path(_git(bare, "rev-parse", "--show-toplevel"))
    assert capsys.readouterr().err.strip() == f"no tools/githooks/pre-commit in {top}"


def test_uninstalling_gives_git_back_its_own_hooks_folder(checkout, monkeypatch, capsys):
    monkeypatch.chdir(checkout)
    githooks.main([])
    capsys.readouterr()

    assert githooks.main(["--uninstall"]) == 0

    assert _hooks_path(checkout) == ""
    assert capsys.readouterr().out.strip() == "core.hooksPath unset; git is back to .git/hooks"
