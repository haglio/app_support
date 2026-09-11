"""What a ``.funscript`` file is: the document, the actions in it, and reading one.

A funscript is a JSON document of timed positions -- ``{"at": <ms>, "pos": 0..100}``
-- authored against one video and played back by a haptic device.  Four repos in
this family read or write one, and each had written down for itself what the file
is: two spellings of the document, and three different answers to a document that
lists no actions -- one raised, one answered nothing, one answered none.  A
caller therefore had to know which repo's reader it was holding before it could
say what "no actions" looked like.

The document's shape is a contract with players outside this family too, which is
why the metadata block here carries every key the fullest writer wrote, empty
ones included: a player that reads a key and finds it missing is not in the same
position as one that reads it and finds it empty.

A format, not a domain -- the bytes several apps agree on, owned by none of
them, standard library only.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app_support.file_channel import write_whole

logger = logging.getLogger(__name__)

#: The document version every writer in this family stamps.
VERSION = "1.0"

#: The top of the position scale; ``pos`` runs from 0 to this.
RANGE = 100


def document(
    actions: list[dict], *, duration_seconds: int, creator: str = ""
) -> dict:
    """A whole funscript document over *actions*, in time order.

    *duration_seconds* is the video the script was authored against, which a
    player shows beside the script and which no reader can recover from the
    actions alone -- a script can stop long before its video does.
    """
    return {
        "actions": sorted(actions, key=lambda action: action["at"]),
        "inverted": False,
        "metadata": {
            "bookmarks": [],
            "chapters": [],
            "creator": creator,
            "description": "",
            "duration": duration_seconds,
            "license": "",
            "notes": "",
            "performers": [],
            "script_url": "",
            "tags": [],
            "title": "",
            "type": "basic",
            "video_url": "",
        },
        "range": RANGE,
        "version": VERSION,
    }


def actions_of(payload: dict) -> list[dict]:
    """The timed positions *payload* lists -- none when it lists none.

    The one answer.  Every caller of the three it replaces went on to do the
    same thing with an empty list, so "no actions" is what a document listing
    none says, rather than a raise at one call site and a None at the next.
    """
    actions = payload.get("actions")
    return actions if isinstance(actions, list) else []


def read(path: Path) -> dict:
    """The document at *path* -- empty when there is nothing readable there.

    Absent is the ordinary case: most videos have no script, and every caller
    asks before it knows.  A file that is *there* and will not read is a broken
    one, so it is logged rather than returned in silence -- no caller of this
    can act on it, and the run loops among them have a frame to draw.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        logger.warning("Unreadable funscript %s", path, exc_info=True)
        return {}
    if not isinstance(payload, dict):
        logger.warning(
            "%s holds %s, not a funscript document", path, type(payload).__name__
        )
        return {}
    return payload


def read_actions(path: Path | None) -> list[dict]:
    """The timed positions the script at *path* holds, or none.

    *path* may be None, which is what "the script this video has" answers for a
    video with none -- so that answer is handed straight here rather than
    guarded again at every call site.
    """
    return actions_of(read(path)) if path is not None else []


def write(path: Path, payload: dict) -> None:
    """Write *payload* to *path*, whole and minified.

    Minified because a script runs to thousands of actions and every writer of
    one outside this family emits it on a single line.  Whole because these are
    read by other processes while one writes them.
    """
    write_whole(Path(path), json.dumps(payload))
