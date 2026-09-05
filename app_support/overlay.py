"""The content overlay: the values that must not be published, loaded at runtime.

Every app keeps what describes the machine and the library -- roots, profiles,
vocabularies, class labels -- out of source, in a git-ignored
``content.local.json``; a committed ``content.example.json`` documents every
key with a tame placeholder and is what a fresh or public checkout loads.  Five
repos each wrote that loader, and only one of them answered the question the
others left to a bare ``KeyError`` far from here: what a local overlay written
before a key existed should do about that key.

Three answers, and each repo says which, per key:

  * **backfill** it from the example -- a phrase list, a vocabulary, anything
    whose placeholder is a usable fallback (:func:`backfilled`);
  * leave it **empty** -- a list of gallery URLs the example fills with
    ``example.com`` markers, which written verbatim into a favorites file would
    be worse than nothing (:func:`backfilled`'s ``empty_when_absent``);
  * **refuse** -- a suite root, a model path, where a placeholder is a launch
    that fails somewhere far from the cause (:func:`missing_keys` before there is
    a window to say so, or :func:`overlay_value` at the read).

The loader itself never merges: a local file answers instead of the example,
and what a missing key means is the repo's to say.  Caching is the repo's too --
one caches the file's text so its twenty importers read it once, one caches the
dict -- because how often a file is read is a fact about who imports it.
Standard library only.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def overlay_path(local_path: Path, example_path: Path) -> Path:
    """The file :func:`read_overlay` will read: the local overlay, or the example."""
    return local_path if local_path.exists() else example_path


def read_overlay(local_path: Path, example_path: Path) -> dict[str, Any]:
    """The local overlay's content when there is one, else the committed example.

    As written, never merged; see :func:`backfilled` for the repos that want the
    example's placeholders behind a partial overlay.
    """
    return json.loads(overlay_path(local_path, example_path).read_text(encoding="utf-8"))


def documented_keys(example: Mapping[str, Any]) -> set[str]:
    """The keys the example documents: every one that is not a comment.

    The example IS the list of what an overlay carries -- it is the file whose
    job is to document the shape -- so there is no second list to keep in step.
    A key beginning with ``_`` is prose about the file, not a value in it.
    """
    return {key for key in example if not key.startswith("_")}


def backfilled(
    data: dict[str, Any], example: Mapping[str, Any], *,
    empty_when_absent: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """*data* with every documented key present: the example's value behind each
    one it lacks, except the keys in *empty_when_absent*, which get that value.

    A partial overlay -- one that exists but omits a key -- then never trips a
    ``data[key]`` far from here.  *empty_when_absent* names the keys whose
    placeholder must never stand in for real data.
    """
    absent = empty_when_absent or {}
    for key, example_value in example.items():
        if key.startswith("_") or key in data:
            continue
        data[key] = absent.get(key, example_value)
    return data


def missing_keys(local_path: Path, example_path: Path) -> tuple[str, ...]:
    """Keys the committed example documents that the local overlay does not have.

    The local overlay is git-ignored and hand-maintained, so it does not grow a
    key when the app does.  A key present but EMPTY is not missing: that is how a
    feature is switched off.  Empty when there is no local overlay at all: a
    fresh or public checkout runs on the example, so there is nothing to be
    short of.
    """
    if not local_path.exists():
        return ()
    documented = documented_keys(json.loads(example_path.read_text(encoding="utf-8")))
    present = set(json.loads(local_path.read_text(encoding="utf-8")))
    return tuple(sorted(documented - present))


class MissingOverlayKey(LookupError):
    """A key the overlay has to carry, and does not -- named, with its file.

    A bare ``KeyError`` out of a module scope says neither which key nor which
    file, and arrives before there is a window to say it in.
    """

    def __init__(self, keys: tuple[str, ...], path: Path | None = None):
        self.keys = tuple(keys)
        self.path = path
        where = f"the content overlay {path}" if path is not None else "the content overlay"
        super().__init__(
            f"{where} has no {' -> '.join(self.keys)}. It replaces content.example.json "
            f"rather than merging with it, so it has to carry every key that one does."
        )


def overlay_value(content: Mapping[str, Any], *keys: str, path: Path | None = None) -> Any:
    """The value at *keys*, or :class:`MissingOverlayKey` naming what is absent.

    For the values a consumer genuinely cannot work without.  Where it can -- a
    list of optional entries, a folder that may not be configured -- read the
    overlay tolerantly instead (``content.get(key) or default``).
    """
    here: Any = content
    for depth, key in enumerate(keys, start=1):
        if not isinstance(here, Mapping) or key not in here:
            raise MissingOverlayKey(keys[:depth], path)
        here = here[key]
    return here
