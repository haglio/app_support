"""The content overlay: which file answers, what a partial one is short of, and
the three answers a repo can give for a missing key.  Every value here is
fabricated."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app_support.overlay import (
    MissingOverlayKey,
    backfilled,
    documented_keys,
    missing_keys,
    overlay_path,
    overlay_value,
    read_overlay,
)


def _json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestReadOverlay:
    def test_the_committed_example_answers_when_there_is_no_local_overlay(self, tmp_path: Path):
        example = _json(tmp_path / "content.example.json", {"suite_root": "C:/example"})

        assert read_overlay(tmp_path / "content.local.json", example) == {"suite_root": "C:/example"}
        assert overlay_path(tmp_path / "content.local.json", example) == example

    def test_the_local_overlay_answers_instead_when_it_is_there(self, tmp_path: Path):
        example = _json(tmp_path / "content.example.json", {"suite_root": "C:/example", "acts": ["a"]})
        local = _json(tmp_path / "content.local.json", {"suite_root": "D:/mine"})

        # Instead of, not on top of: what a missing key means is the repo's to say.
        assert read_overlay(local, example) == {"suite_root": "D:/mine"}
        assert overlay_path(local, example) == local


_EXAMPLE = {"_comment": "what this file is", "phrases": ["skip ahead"],
            "acts": {"alpha": ["alpha"]}, "web_providers": [{"marker": "example"}]}


class TestBackfilled:
    def test_a_missing_key_takes_the_examples_value(self):
        data = backfilled({"acts": {"zeta": ["zeta"]}}, _EXAMPLE, empty_when_absent={})

        assert data["phrases"] == ["skip ahead"]

    def test_a_present_key_is_not_overwritten_by_the_example(self):
        data = backfilled({"phrases": ["rewind that"]}, _EXAMPLE)

        assert data["phrases"] == ["rewind that"]

    def test_a_key_named_empty_when_absent_takes_that_value_not_the_placeholder(self):
        # Gallery URLs the example fills with markers, which written verbatim
        # into a favorites file would be worse than nothing.
        data = backfilled({"acts": {}}, _EXAMPLE, empty_when_absent={"web_providers": []})

        assert data["web_providers"] == []

    def test_the_examples_comment_is_not_a_key_to_copy(self):
        assert "_comment" not in backfilled({}, _EXAMPLE)

    def test_it_is_the_same_dictionary_filled_in(self):
        data = {"acts": {}}

        assert backfilled(data, _EXAMPLE) is data


class TestMissingKeys:
    def test_a_local_overlay_missing_a_key_the_example_documents_is_named(self, tmp_path: Path):
        example = _json(tmp_path / "content.example.json",
                        {"suite_root": "C:/x", "genau_source": "a", "labels": ["b"]})
        local = _json(tmp_path / "content.local.json", {"labels": ["mine"]})

        assert missing_keys(local, example) == ("genau_source", "suite_root")

    def test_a_complete_overlay_is_missing_nothing(self, tmp_path: Path):
        example = _json(tmp_path / "content.example.json", {"suite_root": "C:/x"})
        local = _json(tmp_path / "content.local.json", {"suite_root": "D:/y"})

        assert missing_keys(local, example) == ()

    def test_a_key_present_but_empty_is_not_missing(self, tmp_path: Path):
        """How you switch a feature off: the key is there with nothing in it."""
        example = _json(tmp_path / "content.example.json", {"suite_root": "C:/x", "synonyms": [["a"]]})
        local = _json(tmp_path / "content.local.json", {"suite_root": "D:/y", "synonyms": []})

        assert missing_keys(local, example) == ()

    def test_no_local_overlay_at_all_is_missing_nothing(self, tmp_path: Path):
        """A fresh or public checkout: the example is not compared against
        itself, it IS what loads."""
        example = _json(tmp_path / "content.example.json", {"suite_root": "C:/x"})

        assert missing_keys(tmp_path / "content.local.json", example) == ()

    def test_the_comment_the_example_carries_is_not_a_key_to_copy(self, tmp_path: Path):
        example = _json(tmp_path / "content.example.json", {"_comment": "prose", "suite_root": "C:/x"})
        local = _json(tmp_path / "content.local.json", {"suite_root": "D:/y"})

        assert missing_keys(local, example) == ()
        assert documented_keys(json.loads(example.read_text())) == {"suite_root"}


class TestOverlayValue:
    def test_the_value_at_a_path_of_keys(self):
        assert overlay_value({"a": {"b": 1}}, "a", "b") == 1

    def test_an_absent_key_is_named_with_how_far_the_path_got(self, tmp_path: Path):
        with pytest.raises(MissingOverlayKey) as raised:
            overlay_value({"a": {}}, "a", "b", path=tmp_path / "content.local.json")

        assert raised.value.keys == ("a", "b")
        assert "a -> b" in str(raised.value)
        assert "content.local.json" in str(raised.value)

    def test_a_value_that_is_not_an_object_cannot_be_reached_into(self):
        with pytest.raises(MissingOverlayKey) as raised:
            overlay_value({"a": 3}, "a", "b")

        assert raised.value.keys == ("a", "b")

    def test_it_is_a_lookup_error_so_a_bare_except_keyerror_no_longer_hides_it_either(self):
        assert issubclass(MissingOverlayKey, LookupError)
