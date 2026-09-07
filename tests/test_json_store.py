"""The lock and the whole-file write two processes editing one document need."""
from __future__ import annotations

import json
import os
import threading
import time

import pytest

from app_support.json_store import STALE_S, locked_update, read_json


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_a_document_that_is_not_there_reads_as_an_empty_one(tmp_path):
    assert read_json(tmp_path / "absent.json") == {}


def test_a_document_that_will_not_parse_raises_rather_than_reading_as_empty(tmp_path):
    path = tmp_path / "torn.json"
    path.write_text('{"video": {"act"', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        read_json(path)


def test_a_document_that_is_not_an_object_raises_rather_than_reading_as_empty(tmp_path):
    path = tmp_path / "list.json"
    _write(path, ["alpha", "beta"])
    with pytest.raises(ValueError):
        read_json(path)


def test_an_update_writes_the_document_the_change_hands_back(tmp_path):
    path = tmp_path / "clip.json"
    _write(path, {"video": {"act": "alpha"}})

    def name_the_act(payload):
        payload["video"]["act"] = "beta"
        return payload

    assert locked_update(path, name_the_act) == {"video": {"act": "beta"}}
    assert read_json(path) == {"video": {"act": "beta"}}


def test_a_change_that_hands_back_nothing_leaves_the_document_alone(tmp_path):
    path = tmp_path / "clip.json"
    _write(path, {"video": {"act": "alpha"}})

    assert locked_update(path, lambda payload: None) is None
    assert json.loads(path.read_text(encoding="utf-8")) == {"video": {"act": "alpha"}}
    assert list(tmp_path.iterdir()) == [path]


def test_a_second_writer_waits_rather_than_writing_over_the_first(tmp_path):
    """The lost update this module exists to stop: two processes hold one
    document, and the one that writes second erases the first one's field."""
    path = tmp_path / "clip.json"
    _write(path, {})
    inside = threading.Event()
    may_finish = threading.Event()

    def add_alpha(payload):
        inside.set()
        assert may_finish.wait(5)
        payload["alpha"] = 1
        return payload

    def add_beta(payload):
        payload["beta"] = 2
        return payload

    first = threading.Thread(target=locked_update, args=(path, add_alpha))
    first.start()
    assert inside.wait(5)
    second = threading.Thread(target=locked_update, args=(path, add_beta))
    second.start()
    # Long enough for the second writer to have read the document, had it been
    # let in: without the lock it reads the empty one and writes beta alone.
    second.join(0.3)
    may_finish.set()
    first.join(5)
    second.join(5)

    assert read_json(path) == {"alpha": 1, "beta": 2}


def test_a_lock_a_dead_process_left_behind_is_taken_over_once_it_is_stale(tmp_path):
    path = tmp_path / "clip.json"
    _write(path, {"video": {"act": "alpha"}})
    lock = tmp_path / "clip.json.lock"
    lock.touch()
    long_ago = time.time() - STALE_S - 1
    os.utime(lock, (long_ago, long_ago))

    written = locked_update(path, lambda payload: {**payload, "beta": 2},
                            wait_s=0.05)

    assert written == {"video": {"act": "alpha"}, "beta": 2}
    assert not lock.exists()


def test_a_lock_its_holder_still_owns_is_waited_for_and_then_refused(tmp_path):
    path = tmp_path / "clip.json"
    _write(path, {"video": {"act": "alpha"}})
    (tmp_path / "clip.json.lock").touch()

    with pytest.raises(TimeoutError):
        locked_update(path, lambda payload: {**payload, "beta": 2}, wait_s=0.05)

    assert read_json(path) == {"video": {"act": "alpha"}}


def test_a_change_that_raises_still_gives_the_lock_back(tmp_path):
    path = tmp_path / "clip.json"
    _write(path, {"video": {"act": "alpha"}})

    def give_up(payload):
        raise RuntimeError("nothing to record")

    with pytest.raises(RuntimeError):
        locked_update(path, give_up)

    assert list(tmp_path.iterdir()) == [path]
    assert locked_update(path, lambda payload: {**payload, "beta": 2})


def test_a_document_that_will_not_parse_stops_the_update_before_it_writes(tmp_path):
    path = tmp_path / "clip.json"
    path.write_text('{"video": {"act"', encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        locked_update(path, lambda payload: {**payload, "beta": 2})

    assert path.read_text(encoding="utf-8") == '{"video": {"act"'
    assert list(tmp_path.iterdir()) == [path]


def test_an_update_leaves_the_document_and_nothing_beside_it(tmp_path):
    path = tmp_path / "mirrored" / "tree" / "clip.json"

    locked_update(path, lambda payload: {**payload, "alpha": 1})

    assert read_json(path) == {"alpha": 1}
    assert list(path.parent.iterdir()) == [path]
