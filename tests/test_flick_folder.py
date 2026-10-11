from pathlib import Path

from app_support.flick_folder import (
    flat_flicks_in,
    flicks_folder_in,
    vr_flicks_in,
    weird_dir_for_flicks_folder,
)


def test_weird_dir_sits_beside_the_flicks_folder():
    assert weird_dir_for_flicks_folder(Path("C:/videos/genau/flicks")) == Path("C:/videos/genau/weird")


def test_the_flicks_folder_forks_into_the_2d_flicks_and_the_vr_flicks():
    flicks = Path("C:/videos/genau/flicks")

    assert (flat_flicks_in(flicks), vr_flicks_in(flicks)) == (flicks / "2D", flicks / "VR")


def _genau_holding_flicks_in(root: Path, name: str) -> Path:
    flicks = root / "genau" / name
    weird = weird_dir_for_flicks_folder(flicks)
    for folder in (root / "genau" / "audio", flat_flicks_in(flicks) / "AI", vr_flicks_in(flicks),
                   flat_flicks_in(weird), vr_flicks_in(weird)):
        folder.mkdir(parents=True)
    return root / "genau"


def test_finds_the_flicks_by_the_shape_of_their_folder_whatever_it_is_called(tmp_path):
    assert flicks_folder_in(_genau_holding_flicks_in(tmp_path / "a", "clips")) == tmp_path / "a" / "genau" / "clips"
    assert flicks_folder_in(_genau_holding_flicks_in(tmp_path / "b", "flicks")) == tmp_path / "b" / "genau" / "flicks"


def test_finds_no_flicks_where_genau_has_no_folder_yet(tmp_path):
    assert flicks_folder_in(tmp_path / "genau") is None


def test_finds_no_flicks_where_two_folders_have_their_shape(tmp_path):
    genau = _genau_holding_flicks_in(tmp_path, "clips")
    flat_flicks_in(genau / "flicks").mkdir(parents=True)

    assert flicks_folder_in(genau) is None


def test_the_weird_pile_is_never_taken_for_the_flicks(tmp_path):
    weird = weird_dir_for_flicks_folder(tmp_path / "genau" / "flicks")
    flat_flicks_in(weird).mkdir(parents=True)

    assert flicks_folder_in(tmp_path / "genau") is None
