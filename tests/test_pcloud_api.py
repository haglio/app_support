from __future__ import annotations

import json
from urllib.parse import parse_qsl

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


def test_a_videos_running_time_comes_with_its_listing_as_pcloud_reads_it_and_a_file_without_one_has_none():
    get, _ = _answering({"result": 0, "metadata": {"isfolder": True, "name": "library", "contents": [
        {"isfolder": False, "name": "video one.mp4", "fileid": 7, "size": 1234, "hash": 99, "duration": "5.03"},
        {"isfolder": False, "name": "notes.json", "fileid": 8, "size": 56, "hash": 98},
    ]}})

    listed = PCloud("api.example.test", auth="made-up-token", get=get).list_folder("/library")

    assert [listed["video one.mp4"].duration_s, listed["notes.json"].duration_s] == [5.03, None]


def test_signing_in_posts_pclouds_form_for_a_two_year_login_and_hands_back_the_login():
    posted: list[tuple[str, dict]] = []

    def post(url: str, body: bytes) -> bytes:
        posted.append((url, dict(parse_qsl(body.decode("utf-8")))))
        return json.dumps({"result": 0, "auth": "made-up-login"}).encode("utf-8")

    auth = PCloud("api.example.test", auth="", post=post).login("jane@example.test", "made up + secret", code="654321")

    assert (auth, posted) == ("made-up-login", [("https://api.example.test/login", {
        "getauth": "1", "username": "jane@example.test", "password": "made up + secret", "authexpire": "63072000",
        "device": "Haglio", "deviceid": "haglio-pc", "os": "4", "emailtfacode": "654321", "code": "654321",
        "trusted": "1", "trustdevice": "1", "timeformat": "timestamp"})])


def test_a_refusal_that_opens_a_second_factor_challenge_carries_its_token_and_whether_other_devices_can_send_a_code():
    get, _ = _answering({"result": 2297, "error": "Two factor required.", "token": "made-up-challenge", "hasdevices": True})

    with pytest.raises(PCloudRefused) as refused:
        PCloud("api.example.test", auth="", get=get).email_login_code("jane@example.test")

    assert (refused.value.token, refused.value.has_devices) == ("made-up-challenge", True)


def test_a_second_factors_code_is_sent_by_text_message_or_to_the_accounts_other_devices_as_asked():
    get, asked = _answering({"result": 0})
    pcloud = PCloud("api.example.test", auth="", get=get)

    pcloud.send_second_factor_code("made-up-challenge", by_sms=True)
    pcloud.send_second_factor_code("made-up-challenge", by_sms=False)

    assert asked == ["https://api.example.test/tfa_sendcodeviasms?token=made-up-challenge&timeformat=timestamp",
                     "https://api.example.test/tfa_sendcodeviasysnotification?token=made-up-challenge&timeformat=timestamp"]
