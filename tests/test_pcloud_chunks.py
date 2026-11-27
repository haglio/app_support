from __future__ import annotations

from pathlib import Path

from app_support.pcloud.chunks import ABANDONED_AFTER_S, ChunkStore


def test_a_chunk_written_through_its_claim_reads_back_once_kept(tmp_path: Path):
    store = ChunkStore(tmp_path)

    claim = store.claim("7-99", 0)
    claim.write(b"abc")
    claim.write(b"def")
    claim.keep()

    assert (store.has("7-99", 0), store.read("7-99", 0)) == (True, b"abcdef")


def test_a_chunk_another_writer_has_claimed_is_not_claimed_twice_so_two_apps_never_fetch_it_both(tmp_path: Path):
    store = ChunkStore(tmp_path)
    store.claim("7-99", 3)

    assert store.claim("7-99", 3) is None


def test_a_claim_whose_writer_went_quiet_long_ago_is_taken_over_since_that_writer_has_died(tmp_path: Path):
    now = [1_000_000.0]
    store = ChunkStore(tmp_path, now=lambda: now[0])
    store.claim("7-99", 3).write(b"half of it")
    now[0] += ABANDONED_AFTER_S + 1

    claim = store.claim("7-99", 3)
    claim.write(b"all of it")
    claim.keep()

    assert store.read("7-99", 3) == b"all of it"


def test_a_claim_still_being_written_is_not_taken_over(tmp_path: Path):
    now = [1_000_000.0]
    store = ChunkStore(tmp_path, now=lambda: now[0])
    claim = store.claim("7-99", 3)
    now[0] += ABANDONED_AFTER_S - 1
    claim.write(b"more of it")
    now[0] += ABANDONED_AFTER_S - 1

    assert store.claim("7-99", 3) is None


def _kept(store: ChunkStore, key: str, index: int, data: bytes) -> None:
    claim = store.claim(key, index)
    claim.write(data)
    claim.keep()


def test_trimming_takes_out_the_chunks_read_longest_ago_until_the_store_is_under_its_cap(tmp_path: Path):
    now = [1_000_000.0]
    store = ChunkStore(tmp_path, now=lambda: now[0])
    for key in ("1-1", "2-2", "3-3"):
        _kept(store, key, 0, b"x" * 10)
        now[0] += 1
    store.read("1-1", 0)

    store.trim(cap_bytes=20, keeping=set())

    assert [store.has(key, 0) for key in ("1-1", "2-2", "3-3")] == [True, False, True]


def test_trimming_never_takes_a_chunk_of_a_file_that_is_about_to_be_played(tmp_path: Path):
    store = ChunkStore(tmp_path)
    for key in ("1-1", "2-2", "3-3"):
        _kept(store, key, 0, b"x" * 10)

    store.trim(cap_bytes=0, keeping={"2-2"})

    assert [store.has(key, 0) for key in ("1-1", "2-2", "3-3")] == [False, True, False]


def test_a_chunk_the_disk_refuses_to_delete_is_passed_over_and_the_next_one_taken_since_windows_keeps_a_file_another_app_reads(
        tmp_path: Path):
    def remove(chunk: Path) -> None:
        if chunk.parent.name == "1-1":
            raise PermissionError(chunk)
        chunk.unlink()

    now = [1_000_000.0]
    store = ChunkStore(tmp_path, now=lambda: now[0], remove=remove)
    for key in ("1-1", "2-2"):
        _kept(store, key, 0, b"x" * 10)
        now[0] += 1

    store.trim(cap_bytes=10, keeping=set())

    assert [store.has(key, 0) for key in ("1-1", "2-2")] == [True, False]


def test_trimming_also_leaves_the_disk_the_free_space_asked_for_whatever_the_cap_allows(tmp_path: Path):
    now = [1_000_000.0]
    store = ChunkStore(tmp_path, now=lambda: now[0], free_bytes=lambda: 5)
    for key in ("1-1", "2-2", "3-3"):
        _kept(store, key, 0, b"x" * 10)
        now[0] += 1

    store.trim(cap_bytes=100, keeping=set(), leave_free_bytes=20)

    assert [store.has(key, 0) for key in ("1-1", "2-2", "3-3")] == [False, False, True]
