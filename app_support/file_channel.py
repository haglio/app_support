"""The file channel one process steers another through, and the files it publishes back.

Every player in this family is a separate process that an orchestrator steers
without a socket: it appends verbs to a *command file* the player drains each
tick, and owns pause through a *flag file* the player simply obeys.  The broker
is steered the same way, and it publishes what it knows -- a mode, a heartbeat,
when the device last spoke -- through files of its own that the orchestrator
polls.  Reading is best-effort by design: a missing file, a half-written one, or
one being replaced mid-read must never raise into a run loop, because the next
tick is milliseconds away and will see the settled value.  Writing is whole or
not at all, for that reader's sake.

Pause rides its own file rather than the command channel so that being paused is
a *state* the player converges on, not an event it can miss: a player that
starts late, restarts, or drops a verb still reads the flag and lands correctly.

This was ``player_core.file_channel``, which re-exports it so the players are
untouched.  It moved because the broker, which is no player, had grown its own
consumer that read the file and then truncated it -- a hole one verb wide that a
verb written into it fell through -- and because the files' names were spelled
by hand in four repos (see :mod:`app_support.state_files`).  Standard library
only.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path


def publish_whole(
    path: Path, text: str, *, attempts: int = 5, delay_s: float = 0.005,
) -> bool:
    """Write *text* to *path* so a concurrent poller reads all of it or none.

    The reader polls several times a second while the writer republishes several
    times a second, so an ordinary truncate-and-write leaves a window in which
    the file is empty — and a poller cannot tell "I caught it mid-write" from
    "there is nothing here", so it acts on the blank.  Writing a sibling temp
    file and renaming it over closes that window.

    The rename itself is retried: Windows refuses to replace a file another
    process holds open, so a publish landing inside one of those reads fails
    with a sharing violation.  Retrying turns that into a sub-millisecond wait;
    a file locked for longer reports False, leaving the previous whole record in
    place for the next tick to replace — never a half-published one.
    """
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
    except OSError:
        return False
    for attempt in range(attempts):
        try:
            os.replace(tmp, path)
            return True
        except OSError:
            if attempt < attempts - 1:
                time.sleep(delay_s)
    # Nothing landed, so nothing is left behind: the temp file lives in the
    # state directory beside the real one, where a stray copy per failed publish
    # would accumulate and read as a file some component owns.
    tmp.unlink(missing_ok=True)
    return False


def append_command(
    path: Path, line: str, *, attempts: int = 5, delay_s: float = 0.005,
) -> bool:
    """Queue one verb on *path*, keeping whatever is already waiting there.

    The channel is a queue and this is how a verb joins it.  Writing the file
    whole instead silently drops any verb queued since the last drain, which is
    how an edge-triggered command that fires once and is never re-asserted goes
    missing for good.

    The verb is put on a line of its own even when what is already queued does not
    end in a newline.  A writer that replaces the file whole rarely bothers with a
    trailing one, and appending straight onto that welds the two into a single word
    matching neither, which loses both.

    The reader drains this ~20x/s by rewriting it, so a write that overlaps a
    drain hits a transient Windows sharing violation.  Retrying briefly turns
    that into a millisecond's delay instead of a lost verb; a file locked for
    longer drops the line (the next one lands) rather than raising into a run
    loop that has a frame to draw.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    for attempt in range(attempts):
        try:
            # Checked inside the retry loop: the queue can be drained between
            # attempts, and whether a separator is needed goes with it.
            with path.open("a+", encoding="utf-8") as handle:
                handle.seek(0, 2)
                if handle.tell():
                    handle.seek(handle.tell() - 1)
                    unterminated = handle.read(1) not in ("\n", "\r")
                    handle.seek(0, 2)
                    if unterminated:
                        handle.write("\n")
                handle.write(line + "\n")
            return True
        except OSError:
            if attempt < attempts - 1:
                time.sleep(delay_s)
    return False


def _read_text(path: Path) -> str:
    """*path*'s text, trimmed and without a leading byte-order mark.

    These files are written by whatever tool is nearest — a shell here, an AHK
    script there, PowerShell somewhere else — and a Windows one that writes
    UTF-8 leads with a BOM, which would otherwise be part of the first verb, or
    glue itself to a flag's one character and hide it.
    """
    return path.read_text(encoding="utf-8").replace("﻿", "").strip()


def consume_command_file(
    path: Path, *, logger: logging.Logger | None = None, uppercase: bool = True
) -> list[str]:
    """Take every queued command line, emptying the file so none replays.

    *uppercase* folds the whole payload, which suits a player whose verbs carry
    no arguments.  A player whose commands take a case-sensitive argument (a
    path) passes ``uppercase=False`` and folds just the keyword itself.

    The queue is CLAIMED by renaming it aside and read from the claimed copy.
    A rename is atomic against appenders: the writer lands either in the claimed
    file (drained now) or in a fresh queue (drained next tick), never in between.
    """
    claimed = path.with_suffix(path.suffix + ".consuming")
    try:
        if not path.exists():
            return []
        try:
            os.replace(path, claimed)
        except OSError:
            # A writer holds the file this instant (Windows sharing violation).
            # The queue is intact; next tick is milliseconds away.
            return []
        text = _read_text(claimed)
        claimed.unlink(missing_ok=True)
        if uppercase:
            text = text.upper()
        if not text:
            return []
        return [line.strip() for line in text.splitlines() if line.strip()]
    except Exception:
        if logger is not None:
            logger.exception("Failed to consume command file %s", path)
        return []


def read_flag(path: Path, *, default: bool, logger: logging.Logger | None = None) -> bool:
    """A one-character flag file: ``"1"`` is True, ``"0"`` is False, and anything
    else is *default* -- no file, a blank one, a torn one, one nobody here can read.

    *default* is the caller's word for what the flag means when it says nothing.
    ``genau_enabled.txt`` is on until somebody turns it off, so a missing or
    half-written one reads as enabled; a paused flag is off until somebody sets
    it, so the same file reads as running.  The test is always for the character
    that means the switch was thrown, never for the absence of the other.
    """
    try:
        if not path.exists():
            return default
        text = _read_text(path)
    except Exception:
        if logger is not None:
            logger.exception("Failed to read flag file %s", path)
        return default
    if text == "1":
        return True
    if text == "0":
        return False
    return default


def write_flag(path: Path, value: bool, *, attempts: int = 5, delay_s: float = 0.005) -> bool:
    """Set *path* to ``"1"`` or ``"0"``, published whole.

    Even a one-character file has a truncate-and-write window in which it is
    blank -- and blank reads as the flag's default, which for an enabled-flag
    being turned off is a flicker of *enabled* at the exact moment it was not.
    """
    return publish_whole(path, "1" if value else "0", attempts=attempts, delay_s=delay_s)


def read_paused_state(path: Path, *, logger: logging.Logger | None = None) -> bool:
    """Whether the orchestrator has the player paused; no file means running."""
    return read_flag(path, default=False, logger=logger)


def publish_stamp(
    path: Path, now: float | None = None, *, attempts: int = 5, delay_s: float = 0.005,
) -> bool:
    """Set *path* to the wall clock as text: a heartbeat, or when a device last spoke.

    The wall clock -- ``time.time()`` -- and not the monotonic clock a loop times
    itself with, because the process that reads the stamp is not the one that
    wrote it, and the two share no other clock.
    """
    stamp = time.time() if now is None else now
    return publish_whole(path, str(stamp), attempts=attempts, delay_s=delay_s)


def stamp_age(path: Path, now: float | None = None) -> float | None:
    """Seconds since *path* was stamped, or None when it never was or cannot be read.

    None rather than infinity so a caller can tell "stale" from "never", and
    None for a torn read too: a stamp read mid-publish is not an old one.
    """
    try:
        if not path.exists():
            return None
        stamped = float(_read_text(path))
    except (OSError, ValueError):
        return None
    return (time.time() if now is None else now) - stamped


def read_key_values(path: Path) -> dict[str, str]:
    """One ``key=value``-per-line status file as a dict; raises what the file raises.

    A status is published whole, so a read either sees a complete record or the
    file mid-replace -- and what to do then (hand back the last good snapshot,
    usually) is the reader's to decide, which it cannot if the failure is hidden
    behind an empty dict.
    """
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
