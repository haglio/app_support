from __future__ import annotations

from app_support.osr2_slot import TAKEN, hello, read_hello, says_it_was_taken


def test_a_sender_says_its_name_lowercased_on_a_line_of_its_own():
    assert hello("Portrait") == b"portrait\n"


def test_the_broker_reads_the_name_a_hello_says():
    assert read_hello(hello("Portrait")) == "portrait"


def test_a_name_sent_in_capitals_or_ended_windows_style_is_still_that_name():
    assert read_hello("  Main\r\n") == "main"


def test_a_blank_hello_names_nobody():
    assert read_hello(b"\r\n") == ""


def test_a_hello_that_is_not_ascii_is_read_rather_than_raised_on():
    assert read_hello(b"caf\xe9\n") == "caf\N{REPLACEMENT CHARACTER}"


def test_a_sender_the_broker_hung_up_on_for_another_hears_that_it_was_taken():
    assert says_it_was_taken(TAKEN)


def test_a_hang_up_that_says_nothing_is_the_broker_going_away():
    assert not says_it_was_taken(b"")
