from __future__ import annotations

import json
from pathlib import Path

import pytest

from app_support import glossary


def _row(row_id: str = "alpha", **fields) -> dict:
    return {"id": row_id, "thing": "the small square", "screen": "Square", "his_word": "square",
            "code_today": ["square"], "code_word": "square", "status": "agreed"} | fields


def _glossary(tmp_path: Path, *rows: dict) -> Path:
    path = tmp_path / "glossary.json"
    path.write_text(json.dumps({"things": list(rows)}), encoding="utf-8")
    return path


def test_two_rows_with_one_id_are_refused(tmp_path):
    with pytest.raises(AssertionError, match="two rows share an id"):
        glossary.assert_rows_are_whole(_glossary(tmp_path, _row(), _row()))


def test_a_row_lacking_a_column_is_refused_by_name(tmp_path):
    row = _row()
    del row["his_word"]
    with pytest.raises(AssertionError, match=r"alpha lacks \['his_word'\]"):
        glossary.assert_rows_are_whole(_glossary(tmp_path, row))


@pytest.mark.parametrize(("fields", "told"), [
    ({"status": "pending"}, "alpha: unknown status 'pending'"),
    ({"thing": "  "}, "alpha does not say what it is"),
    ({"code_today": []}, "alpha names no word the code says today"),
    ({"status": "ruled"}, "alpha is ruled but says not when or where"),
    ({"status": "ruled", "ruled": "2026-01-01", "code_word": None}, "alpha is ruled but names no code word"),
], ids=["unknown status", "blank thing", "no code word today", "ruled with no ruling", "ruled with no code word"])
def test_a_row_short_of_what_its_status_asks_is_refused(tmp_path, fields, told):
    with pytest.raises(AssertionError, match=told):
        glossary.assert_rows_are_whole(_glossary(tmp_path, _row(**fields)))


@pytest.mark.parametrize("status", ["his_word", "agreed", "unruled", "kept"])
def test_a_whole_row_passes_in_every_status_that_asks_for_no_ruling(tmp_path, status):
    glossary.assert_rows_are_whole(_glossary(tmp_path, _row(status=status, code_word=None)))


def test_a_ruled_row_with_its_ruling_and_code_word_passes(tmp_path):
    glossary.assert_rows_are_whole(_glossary(tmp_path, _row(status="ruled", ruled="2026-01-01")))


def _source(tmp_path: Path, files: dict[str, str]) -> list[glossary.SourceLine]:
    for name, text in files.items():
        path = tmp_path / "pkg" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return glossary.source_lines([tmp_path / "pkg"])


def test_a_code_word_the_code_no_longer_says_is_named(tmp_path):
    source = _source(tmp_path, {"a.py": "other = 1\n"})
    with pytest.raises(AssertionError, match="alpha: 'square'"):
        glossary.assert_code_today_still_said(_glossary(tmp_path, _row()), source)


@pytest.mark.parametrize("code", ["square = 1\n", "the_square = 1\n", "class BigSquare: pass\n", "SQUARE = 1\n"],
                         ids=["word", "part of a snake name", "part of a camel name", "constant"])
def test_a_code_word_said_any_way_counts_as_said(tmp_path, code):
    glossary.assert_code_today_still_said(_glossary(tmp_path, _row()), _source(tmp_path, {"a.py": code}))


def test_a_phrase_with_a_number_in_it_matches_the_one_name_it_runs_together_as(tmp_path):
    source = _source(tmp_path, {"a.py": "class Osr2Controls: pass\n"})
    glossary.assert_code_today_still_said(_glossary(tmp_path, _row(code_today=["osr2 controls"])), source)


def test_a_code_word_matches_whole_words_only(tmp_path):
    source = _source(tmp_path, {"a.py": "squares = 1\n"})
    with pytest.raises(AssertionError, match="alpha: 'square'"):
        glossary.assert_code_today_still_said(_glossary(tmp_path, _row()), source)


def test_source_lines_reach_every_python_file_under_each_folder_and_say_where_from_the_folders_own_name(tmp_path):
    source = _source(tmp_path, {"deep/a.py": "first\nsecond_word\n", "notes.txt": "third\n"})
    assert [(line.where, line.number, line.tokens) for line in source] == [
        ("pkg/deep/a.py", 1, ["first"]), ("pkg/deep/a.py", 2, ["second_word"])]


def test_a_retired_word_still_in_the_code_is_named_with_its_place(tmp_path):
    source = _source(tmp_path, {"a.py": "\nold_square = 1\n"})
    with pytest.raises(AssertionError, match=r"alpha retired 'square': pkg/a.py:2 old_square"):
        glossary.assert_retired_words_gone(_glossary(tmp_path, _row(retired=["square"])), source)


def _retired_says(tmp_path: Path, code: str, retired: str = "square", keep: tuple[str, ...] = ()) -> bool:
    row = _row(retired=[retired], keep=list(keep))
    try:
        glossary.assert_retired_words_gone(_glossary(tmp_path, row), _source(tmp_path, {"a.py": code}))
    except AssertionError:
        return True
    return False


@pytest.mark.parametrize(("code", "retired", "found"), [
    ("squares = 1\n", "square", True),
    ("boxes = 1\n", "box", True),
    ("squarely = 1\n", "square", False),
    ("BigSquare = 1\n", "square", True),
    ("SQUARE = 1\n", "square", False),
    ("OLD_SQUARE = 1\n", "square", True),
    ("big_square = 1\n", "big square", True),
    ("big, other, square = 1\n", "big square", False),
    ("big, square = 1\n", "big square", True),
    ("big_squares = 1\n", "big square", True),
    ("bigs_square = 1\n", "big square", False),
], ids=["plural", "plural in es", "longer word", "camel part", "bare capitals are an acronym", "constant",
        "two words in one name", "two words apart", "two words across names", "last word plural", "first word plural"])
def test_what_counts_as_saying_a_retired_word(tmp_path, code, retired, found):
    assert _retired_says(tmp_path, code, retired) is found


@pytest.mark.parametrize(("code", "keep", "found"), [
    ("square_root = 1\n", ("square_root",), False),
    ("Square_Root = 1\n", ("square_root",), False),
    ("square_root = square\n", ("square_root",), True),
    ("# the square wave\n", ("the square wave",), False),
    ("# the square\n", ("the square wave",), True),
], ids=["kept name", "kept name in any case", "another name on the line", "kept phrase on its line", "phrase elsewhere"])
def test_keep_spares_the_name_it_says_or_the_line_holding_the_phrase_it_says(tmp_path, code, keep, found):
    assert _retired_says(tmp_path, code, keep=keep) is found


def test_a_long_list_of_retired_words_left_is_cut_at_forty(tmp_path):
    source = _source(tmp_path, {"a.py": "square = 1\n" * 41})
    with pytest.raises(AssertionError) as raised:
        glossary.assert_retired_words_gone(_glossary(tmp_path, _row(retired=["square"])), source)
    assert "pkg/a.py:40 " in str(raised.value)
    assert "pkg/a.py:41 " not in str(raised.value)


def test_a_screen_noun_in_the_code_with_no_row_is_named(tmp_path):
    source = _source(tmp_path, {"a.py": "tile = 1\n"})
    with pytest.raises(AssertionError, match=r"\['tile'\]"):
        glossary.assert_screen_nouns_have_rows(_glossary(tmp_path, _row()), source)


@pytest.mark.parametrize("fields", [
    {"code_today": ["tile"]},
    {"code_word": "tile"},
    {"code_word": None, "code_today": ["big tile"]},
    {"retired": ["tile"]},
], ids=["code today", "code word", "second word of a phrase", "retired"])
def test_a_screen_noun_named_in_any_of_a_rows_word_columns_has_its_row(tmp_path, fields):
    source = _source(tmp_path, {"a.py": "tile = 1\n"})
    glossary.assert_screen_nouns_have_rows(_glossary(tmp_path, _row(**fields)), source)


def test_a_screen_noun_is_found_inside_a_longer_name(tmp_path):
    source = _source(tmp_path, {"a.py": "class NewTile: pass\n"})
    with pytest.raises(AssertionError, match=r"\['tile'\]"):
        glossary.assert_screen_nouns_have_rows(_glossary(tmp_path, _row()), source)


def test_an_app_can_hold_more_nouns_than_the_family_lists(tmp_path):
    source = _source(tmp_path, {"a.py": "lantern = 1\n"})
    path = _glossary(tmp_path, _row())
    glossary.assert_screen_nouns_have_rows(path, source)
    with pytest.raises(AssertionError, match=r"\['lantern'\]"):
        glossary.assert_screen_nouns_have_rows(path, source, more_nouns=["lantern"])
