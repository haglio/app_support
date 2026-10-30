"""Reading what a repository holds at a revision.  Every file here is invented."""
from __future__ import annotations

from app_support.git_files import files_at


def test_the_files_a_revision_holds_are_read_without_checking_it_out(branch_from):
    repo = branch_from({"widgetlib/__init__.py": "", "widgetlib/colors.py": "GRAY = 1\n", "notes.txt": "a note\n"})
    repo.commit({"widgetlib/colors.py": "GRAY = 2\n"})

    assert files_at(repo.path, "main", lambda path: path.startswith("widgetlib/")) == {
        "widgetlib/__init__.py": "", "widgetlib/colors.py": "GRAY = 1\n"}
