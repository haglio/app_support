from __future__ import annotations

import json

import pytest

from app_support.pcloud.api import CloudFile, FileLink, PCloud, PCloudRefused


def _answering(answer: dict):
    asked: list[str] = []

    def get(url: str) -> bytes:
        asked.append(url)
        return json.dumps(answer).encode("utf-8")

    return get, asked


def test_an_answer_pcloud_refused_raises_its_code_and_message_since_pcloud_answers_every_call_with_http_200():
    get, _ = _answering({"result": 2005, "error": "Directory does not exist."})

    with pytest.raises(PCloudRefused) as refused:
        PCloud("api.example.test", auth="made-up-token", get=get).list_folder("/library/gone")

    assert (refused.value.code, str(refused.value)) == (2005, "pCloud refused listfolder: Directory does not exist. (2005)")


def test_a_files_link_is_its_nearest_host_and_path_with_the_path_spelled_for_a_url():
    get, asked = _answering({"result": 0, "hosts": ["c1.example.test", "c2.example.test"],
                             "path": "/cB2/video one #2.mp4", "expires": 1767225600})

    link = PCloud("api.example.test", auth="made-up-token", get=get).file_link(7)

    assert (link, asked) == (
        FileLink(url="https://c1.example.test/cB2/video%20one%20%232.mp4", expires=1767225600.0),
        ["https://api.example.test/getfilelink?fileid=7&timeformat=timestamp&auth=made-up-token"],
    )


def test_a_folders_listing_names_each_file_in_it_by_its_id_size_and_hash_and_leaves_its_folders_out():
    get, asked = _answering({"result": 0, "metadata": {"isfolder": True, "name": "library", "contents": [
        {"isfolder": False, "name": "video one.mp4", "fileid": 7, "size": 1234, "hash": 99},
        {"isfolder": True, "name": "kept", "folderid": 3},
        {"isfolder": False, "name": "video two.mp4", "fileid": 8, "size": 5678, "hash": 98},
    ]}})

    listed = PCloud("api.example.test", auth="made-up-token", get=get).list_folder("/library")

    assert (listed, asked) == (
        {"video one.mp4": CloudFile(fileid=7, size=1234, hash=99), "video two.mp4": CloudFile(fileid=8, size=5678, hash=98)},
        ["https://api.example.test/listfolder?path=%2Flibrary&timeformat=timestamp&auth=made-up-token"],
    )
