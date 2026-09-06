"""This repo's own dead-code gate. The scan it calls is `app_support.dead_code`.

**The tests are scanned alongside the package, and that is the whole design.**
Every consumer of this library lives in another repo, so no production call site
here reaches any published name: vulture pointed at `app_support/` alone reports
essentially the entire surface, and the whitelist needed to quiet it would be a
restatement of the API -- a gate that cannot fail, which is what `player_core`
declined to keep for exactly this reason.

Scanning `tests/` alongside asks a question that has an answer: is every name
this package publishes reached by *something* in this repo? A name no test
touches is either dead or untested, and both want the same next move. What it
gives up is a name a test exercises and no consumer wants; the consumer-import
scan `player_core` carries is the shape that catches those, and it needs the
sibling checkouts this gate deliberately does not read.
"""
from __future__ import annotations

from pathlib import Path

from app_support.dead_code import assert_no_dead_code, assert_whitelist_is_live

ROOT = Path(__file__).resolve().parent.parent
# Named one by one rather than scanning `.` under an `--exclude` list: vulture
# matches those patterns against absolute paths, and this checkout may itself be
# `<repo>/.claude/worktrees/<name>`, where `--exclude .claude` matches the root
# of the tree being scanned and quietly excludes every file in it.
SCANNED = (ROOT / "app_support", ROOT / "tests", ROOT / "tools")
WHITELIST = ROOT / "vulture_whitelist.txt"


def test_no_dead_code():
    assert_no_dead_code(*SCANNED, whitelist=WHITELIST)


def test_the_whitelist_still_suppresses_what_it_claims_to():
    assert_whitelist_is_live(*SCANNED, whitelist=WHITELIST)
