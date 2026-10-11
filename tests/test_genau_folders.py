from pathlib import Path

from app_support import genau_folders


def _genau_holding_flicks_in(root: Path, name: str) -> Path:
    genau = root / "genau"
    for folder in (genau / "audio", genau / name / "2D" / "AI", genau / name / "VR",
                   genau / genau_folders.WEIRD_PILE / "2D", genau / genau_folders.WEIRD_PILE / "VR"):
        folder.mkdir(parents=True)
    return genau


def test_finds_the_flicks_by_the_shape_of_their_folder_whatever_it_is_called(tmp_path):
    assert genau_folders.flicks_folder(_genau_holding_flicks_in(tmp_path / "a", "clips")) \
        == tmp_path / "a" / "genau" / "clips"
    assert genau_folders.flicks_folder(_genau_holding_flicks_in(tmp_path / "b", "flicks")) \
        == tmp_path / "b" / "genau" / "flicks"


def test_finds_no_flicks_where_genau_has_no_folder_yet(tmp_path):
    assert genau_folders.flicks_folder(tmp_path / "genau") is None


def test_finds_no_flicks_where_two_folders_have_their_shape(tmp_path):
    genau = _genau_holding_flicks_in(tmp_path, "clips")
    (genau / "flicks" / "2D").mkdir(parents=True)

    assert genau_folders.flicks_folder(genau) is None


def test_the_weird_pile_is_never_taken_for_the_flicks(tmp_path):
    genau = tmp_path / "genau"
    (genau / genau_folders.WEIRD_PILE / "2D").mkdir(parents=True)

    assert genau_folders.flicks_folder(genau) is None
