from __future__ import annotations

import pytest

from app_support.pcloud.api import PCloud, PCloudRefused, read_span
from app_support.pcloud.testing import FakePCloud


def test_the_client_reaches_pcloud_over_http_with_its_login():
    with FakePCloud({"/library/video one.mp4": b"0123456789"}) as cloud:
        assert PCloud(cloud.origin, auth=cloud.auth).list_folder("/library")["video one.mp4"].size == 10


def test_a_login_pcloud_no_longer_takes_is_refused_as_one_that_needs_signing_in_again():
    with FakePCloud({"/library/video one.mp4": b"0123456789"}) as cloud, \
            pytest.raises(PCloudRefused) as refused:
        PCloud(cloud.origin, auth="a-token-nobody-issued").list_folder("/library")

    assert refused.value.needs_signing_in


def test_a_span_of_a_file_comes_down_as_just_those_bytes():
    content = bytes(range(256)) * 40
    with FakePCloud({"/library/video one.mp4": content}) as cloud:
        pcloud = PCloud(cloud.origin, auth=cloud.auth)
        link = pcloud.file_link(pcloud.list_folder("/library")["video one.mp4"].fileid)

        assert (read_span(link.url, 1000, 1010), cloud.downloads) == (
            content[1000:1010], [("/library/video one.mp4", 1000, 1010)])
