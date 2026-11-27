from __future__ import annotations

from pathlib import Path

from app_support.pcloud.places import CloudPlaces


def test_a_file_in_a_folder_kept_in_pcloud_has_that_folders_cloud_path_and_its_own_below_it(tmp_path: Path):
    places = CloudPlaces({tmp_path / "library": "/the library"})

    assert places.cloud_path_of(tmp_path / "library" / "videos" / "Video One.mp4") == "/the library/videos/Video One.mp4"


def test_a_file_in_no_folder_kept_in_pcloud_has_no_cloud_path_and_plays_from_where_it_is(tmp_path: Path):
    assert CloudPlaces({tmp_path / "library": "/the library"}).cloud_path_of(tmp_path / "elsewhere" / "video.mp4") is None


def test_a_folder_named_with_other_capitals_still_holds_the_file_whose_own_capitals_are_kept_since_windows_reads_both_alike(
        tmp_path: Path):
    places = CloudPlaces({tmp_path / "Library": "/the library"})

    assert places.cloud_path_of(tmp_path / "library" / "Video One.mp4") == "/the library/Video One.mp4"


def test_a_file_on_a_drive_kept_whole_in_pcloud_has_its_path_from_pclouds_top(tmp_path: Path):
    assert CloudPlaces({tmp_path: "/"}).cloud_path_of(tmp_path / "vr" / "video one.mp4") == "/vr/video one.mp4"


def test_a_cloud_path_leads_back_to_where_its_file_sits_on_this_computer(tmp_path: Path):
    places = CloudPlaces({tmp_path / "library": "/the library", tmp_path / "drive": "/"})

    assert [places.local_path_of("/the library/videos/video one.mp4"), places.local_path_of("/vr/video two.mp4")] == [
        tmp_path / "library" / "videos" / "video one.mp4", tmp_path / "drive" / "vr" / "video two.mp4"]


def test_a_cloud_path_in_no_folder_this_computer_keeps_leads_nowhere(tmp_path: Path):
    assert CloudPlaces({tmp_path / "library": "/the library"}).local_path_of("/elsewhere/video one.mp4") is None
