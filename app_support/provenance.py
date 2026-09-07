"""What made a file, recorded beside the file, in a form that outlives the app.

Two questions get asked of an old artifact, and nothing in this family could
answer either.  *Which build of which app produced this* -- so a sweep can find
everything made before a fix and remake it.  *Under which recipe, at which
version of that recipe* -- so two outputs that differ only in the code that made
them stay two things rather than collapsing into one.  A stamp answers both, in
seven keys, wherever the app that made the file chooses to keep it.

Both halves are needed and neither substitutes for the other.  The recipe
version is the meaningful axis and the one a person reasons about, but it is
bumped by hand, so it is coarse and it can be forgotten; the commit is exact and
free and never wrong, but it moves for reasons that have nothing to do with the
output.  An upgrade sweep reads the recipe version to decide *what* to redo and
the commit to pin down *exactly* what produced it when the version is too coarse
or was never bumped.

Read from git at runtime rather than baked in at build time: nothing here is
built, every app runs editable out of its checkout, and a version literal in a
source file is one more thing to forget -- the eight ``pyproject.toml`` files in
this family have all said ``0.1.0`` since the day they were written.

**The checkout is read once per process.**  Evolver's tray is up for days at a
time and holds the modules it imported at launch, while the checkout underneath
it moves as the merge queue lands work; asking git again would report a commit
the running code is not.  Once, on the first stamp, is the closest thing
available to "the code that is running", and it also keeps a sweep over hundreds
of clips from spawning hundreds of subprocesses.  Both facts come out of one
``git status`` so they cannot disagree with each other.

**A fact nobody knows is an explicit ``None``, never an absent key.**  A wrong
version is worse than a missing one -- an upgrade sweep skips the file believing
it current -- and a reader opening a ten-year-old artifact should not have to
work out which shape it got.  ``SCHEMA`` says which shape that is.
"""
from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs

# The shape below. Bumped when a key is added, removed or re-meant, so a reader
# of an old artifact knows what it is holding.
SCHEMA = 1

# A ceiling on a git that stops answering, not a budget: this runs inside a
# windowed app, where a child that never returns is a frozen window with
# nothing to read.
_GIT_TIMEOUT_SECONDS = 10

# What `git status --porcelain=v2 --branch` calls the commit, in the header
# block it prints before the changed paths.
_OID_HEADER = "# branch.oid "


def _status(directory: Path) -> str | None:
    """``git status`` for the checkout holding *directory*, or ``None`` when
    there is no answer -- no repository, no git, a directory that is not there.

    ``--porcelain=v2 --branch`` rather than a ``rev-parse`` and a ``status``:
    one command reports the commit and the changed paths together, so the two
    halves of a stamp cannot come from different moments.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(directory), "status", "--porcelain=v2", "--branch"],
            capture_output=True, text=True, check=True,
            timeout=_GIT_TIMEOUT_SECONDS, **hidden_subprocess_kwargs())
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout


@cache
def _code_version(directory: str) -> tuple[str | None, bool | None]:
    """The commit the code under *directory* sits at, and whether the tree
    carried edits that commit does not describe.

    Cached for the life of the process; see the module docstring.
    """
    reported = _status(Path(directory))
    if reported is None:
        return None, None
    lines = reported.splitlines()
    commit = next((line[len(_OID_HEADER):] for line in lines
                   if line.startswith(_OID_HEADER)), None)
    if commit is None or not commit[:1].isalnum():
        return None, None  # an unborn HEAD reports "(initial)"
    return commit, any(not line.startswith("#") for line in lines)


def stamp(app: str, *, anchor: str | Path,
          recipe: str | None = None, recipe_version: str | None = None) -> dict:
    """The provenance block for something *app* is writing now.

    *anchor* is a file of the app's own code -- pass ``__file__`` -- and is what
    says which checkout to read.  A worktree answers for itself, which is the
    point: content generated off a preview branch records that branch's commit.

    *recipe* and *recipe_version* are the app's own vocabulary for what it ran
    (Origenerator passes its workflow's name and ``version``); an app whose
    output has only one shape leaves both unset.
    """
    commit, dirty = _code_version(str(Path(anchor).parent))
    return {"schema": SCHEMA, "app": app, "app_commit": commit, "app_dirty": dirty,
            "recipe": recipe, "recipe_version": recipe_version,
            "stamped_at": datetime.now(UTC).isoformat()}
