"""The OSR2's slot, both ends of it: the broker's, which hands on the T-Code of
the one sender holding it, and a sender's, which holds it only while it wants
the device.

Most of the broker's side is served one end of a connected pair on the test's
own thread, so what it did is settled by the time the call returns; the ones
about two senders at once go through a listening slot.
"""
from __future__ import annotations

import contextlib
import logging
import queue
import socket
import threading
import time
import types
from unittest.mock import MagicMock

import pytest

from app_support import osr2_slot as slot_module
from app_support.osr2_slot import Osr2Sender, Osr2Slot
from app_support.threading_utils import start_daemon_thread

_LOGGER = "test.app_support.osr2_slot"
_WITHIN_S = 5.0


def _slot() -> Osr2Slot:
    return Osr2Slot(port=0, logger=logging.getLogger(_LOGGER), start_thread=None)


class _Written:
    """A session's writer: every line it was handed, and whose."""

    def __init__(self):
        self._lines: queue.Queue[tuple[str, str]] = queue.Queue()

    def __call__(self, sender: str, line: str) -> None:
        self._lines.put((sender, line))

    def so_far(self) -> list[tuple[str, str]]:
        lines = []
        while not self._lines.empty():
            lines.append(self._lines.get_nowait())
        return lines

    def next(self) -> tuple[str, str]:
        return self._lines.get(timeout=_WITHIN_S)


@pytest.fixture
def listening():
    slot = Osr2Slot(port=0, logger=logging.getLogger(_LOGGER), start_thread=start_daemon_thread)
    slot.start()
    yield slot
    slot.close()


@pytest.fixture
def heard(caplog):
    caplog.set_level(logging.INFO, logger=_LOGGER)
    return caplog


def _the_log_says(caplog, words: str) -> str:
    deadline = time.monotonic() + _WITHIN_S
    while time.monotonic() < deadline:
        for message in caplog.messages:
            if words in message:
                return message
        time.sleep(0.01)
    raise AssertionError(f"nothing logged said {words!r}: {caplog.messages}")


@contextlib.contextmanager
def _connected(slot: Osr2Slot, name: bytes):
    """A sender connected to a listening slot, having named itself."""
    with socket.create_connection(slot.address, timeout=_WITHIN_S) as sender:
        sender.sendall(name + b"\n")
        yield sender


def _a_sender_that_says(*sent: bytes) -> tuple[socket.socket, socket.socket]:
    """The slot's end and the sender's of one connection, everything the sender
    will ever say already said."""
    ours, theirs = socket.socketpair()
    for each in sent:
        theirs.sendall(each)
    theirs.shutdown(socket.SHUT_WR)
    return ours, theirs


def _hung_up_on(theirs: socket.socket) -> bool:
    """Whether the slot closed the sender's line, whatever it said first.  A close
    with what the sender sent still unread reaches it as a reset rather than an end."""
    theirs.settimeout(_WITHIN_S)
    try:
        while theirs.recv(16):
            pass
    except (ConnectionResetError, ConnectionAbortedError):
        pass
    return True


def _what_it_heard_until_hung_up_on(theirs: socket.socket) -> bytes:
    theirs.settimeout(_WITHIN_S)
    heard = b""
    while True:
        data = theirs.recv(64)
        if not data:
            return heard
        heard += data


def _serve_on_a_thread(slot: Osr2Slot, ours: socket.socket) -> threading.Thread:
    serving = threading.Thread(target=slot.serve, args=(ours,), daemon=True)
    serving.start()
    return serving


class TestTheBrokersSide:
    def test_a_sender_that_names_itself_has_its_t_code_written_through(self):
        slot = _slot()
        written = _Written()
        slot.write_through(written)
        ours, _theirs = _a_sender_that_says(b"portrait\nL05000I33\n")

        slot.serve(ours)

        assert written.so_far() == [("portrait", "L05000I33")]

    def test_a_name_sent_in_capitals_or_ended_windows_style_is_still_that_name(self):
        slot = _slot()
        written = _Written()
        slot.write_through(written)
        ours, _theirs = _a_sender_that_says(b"  Main\r\nL05000I33\n")

        slot.serve(ours)

        assert written.so_far() == [("main", "L05000I33")]

    def test_a_name_that_is_not_ascii_is_read_rather_than_raised_on(self):
        slot = _slot()
        written = _Written()
        slot.write_through(written)
        ours, _theirs = _a_sender_that_says(b"caf\xe9\nL05000I33\n")

        slot.serve(ours)

        assert written.so_far() == [("caf\N{REPLACEMENT CHARACTER}", "L05000I33")]

    def test_a_connection_that_says_nothing_for_a_second_is_hung_up_on(self):
        """Both bounds: it is given its second, and not much more.  Without the
        upper one a connection that never speaks holds a thread for good; without
        the lower one a sender that is slow to start is turned away."""
        ours, theirs = socket.socketpair()

        started = time.monotonic()
        serving = _serve_on_a_thread(_slot(), ours)
        serving.join(timeout=_WITHIN_S)
        took = time.monotonic() - started

        assert not serving.is_alive()
        assert 0.9 <= took < 2.5, took
        assert _hung_up_on(theirs)

    def test_a_name_said_a_piece_at_a_time_still_has_only_its_second(self, monkeypatch):
        """Each piece arriving inside the second must not start the second over: the
        second is up when the clock says so, not a second after the last piece.  So
        once a piece has come and the clock is past the second, the slot hangs up at
        once rather than waiting on the next."""
        readings = iter([100.0, 100.0])
        monkeypatch.setattr(slot_module, "time",
                            types.SimpleNamespace(monotonic=lambda: next(readings, 101.0)))
        ours, theirs = socket.socketpair()
        theirs.sendall(b"port")

        started = time.monotonic()
        _slot().serve(ours)
        took = time.monotonic() - started

        assert took < 0.5, took
        assert _hung_up_on(theirs)

    def test_a_connection_that_closes_before_finishing_its_name_is_never_the_holder(self):
        slot = _slot()
        ours, _theirs = _a_sender_that_says(b"portr")

        slot.serve(ours)

        assert slot.holder is None

    def test_a_connection_that_names_nobody_is_hung_up_on_and_reaches_nothing(self):
        slot = _slot()
        written = _Written()
        slot.write_through(written)
        ours, theirs = _a_sender_that_says(b"\r\nL05000I33\n")

        slot.serve(ours)

        assert written.so_far() == []
        assert _hung_up_on(theirs)

    def test_lines_sent_before_a_hold_took_the_osr2_are_not_handed_on_after_it(self):
        """What the sender had already sent is still in hand when the hold lands;
        handing it on would undo the hold with the sender's last word."""
        slot = _slot()
        handed_on = []

        def writer(_sender, line):
            handed_on.append(line)
            slot.kick("The park")

        slot.write_through(writer)
        ours, _theirs = _a_sender_that_says(b"portrait\nL01000I33\nL02000I33\n")

        slot.serve(ours)

        assert handed_on == ["L01000I33"]

    def test_the_log_says_who_has_the_osr2_and_when_they_let_go_of_it(self, heard):
        ours, _theirs = _a_sender_that_says(b"portrait\n")

        _slot().serve(ours)

        assert heard.messages[-2:] == ["The OSR2 is portrait's", "portrait let go of the OSR2"]

    def test_the_newest_sender_takes_the_osr2_and_the_one_before_is_hung_up_on(
            self, listening, heard):
        written = _Written()
        listening.write_through(written)

        with _connected(listening, b"portrait") as portrait:
            portrait.sendall(b"L01000I33\n")
            assert written.next() == ("portrait", "L01000I33")

            with _connected(listening, b"main") as main:
                main.sendall(b"L02000I33\n")

                assert written.next() == ("main", "L02000I33")
                assert _the_log_says(heard, "took") == "main took the OSR2 from portrait"
                assert _hung_up_on(portrait)

    def test_the_sender_a_newer_one_takes_the_osr2_from_hears_that_it_was_taken(self, listening):
        written = _Written()
        listening.write_through(written)

        with _connected(listening, b"portrait") as portrait:
            portrait.sendall(b"L01000I33\n")
            written.next()
            with _connected(listening, b"main") as main:
                main.sendall(b"L02000I33\n")
                written.next()

                assert _what_it_heard_until_hung_up_on(portrait) == b"taken\n"

    def test_the_sender_a_hold_takes_the_osr2_from_hears_that_it_was_taken(self, listening):
        written = _Written()
        listening.write_through(written)

        with _connected(listening, b"portrait") as portrait:
            portrait.sendall(b"L01000I33\n")
            written.next()

            listening.kick("The park")

            assert _what_it_heard_until_hung_up_on(portrait) == b"taken\n"

    def test_a_sender_the_osr2_was_taken_from_may_go_on_sending_unheard_until_it_hangs_up(
            self, listening):
        written = _Written()
        listening.write_through(written)

        with _connected(listening, b"portrait") as portrait:
            portrait.sendall(b"L01000I33\n")
            written.next()
            listening.kick("The park")

            portrait.sendall(b"L02000I33\n")
            portrait.sendall(b"L03000I33\n")

            assert _what_it_heard_until_hung_up_on(portrait) == b"taken\n"
        assert written.so_far() == []

    def test_a_hold_takes_the_osr2_from_its_sender_and_leaves_the_slot_empty(
            self, listening, heard):
        written = _Written()
        listening.write_through(written)

        with _connected(listening, b"portrait") as portrait:
            portrait.sendall(b"L01000I33\n")
            written.next()

            listening.kick("The park")

            assert _the_log_says(heard, "took") == "The park took the OSR2 from portrait"
            assert _hung_up_on(portrait)
        with _connected(listening, b"main"):
            assert _the_log_says(heard, "main") == "The OSR2 is main's"

    def test_the_slot_says_who_holds_it_from_their_name_until_they_let_go(self, listening, heard):
        written = _Written()
        listening.write_through(written)
        nobody_yet = listening.holder

        with _connected(listening, b"portrait") as portrait:
            portrait.sendall(b"L01000I33\n")
            written.next()

            assert listening.holder == "portrait"
        _the_log_says(heard, "let go")

        assert nobody_yet is None
        assert listening.holder is None

    def test_nobody_holds_the_slot_once_a_hold_has_taken_it(self, listening):
        written = _Written()
        listening.write_through(written)

        with _connected(listening, b"portrait") as portrait:
            portrait.sendall(b"L01000I33\n")
            written.next()

            listening.kick("The retract")

            assert listening.holder is None

    def test_a_hold_with_nobody_holding_the_slot_takes_nothing(self):
        logger = MagicMock()

        Osr2Slot(port=0, logger=logger, start_thread=None).kick("The park")

        logger.info.assert_not_called()

    def test_a_slot_that_cannot_listen_says_so_rather_than_stopping_the_broker(self, heard):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as somebody_else:
            somebody_else.bind(("127.0.0.1", 0))
            somebody_else.listen()
            slot = Osr2Slot(port=somebody_else.getsockname()[1],
                            logger=logging.getLogger(_LOGGER), start_thread=start_daemon_thread)

            slot.start()

            assert "could not listen" in _the_log_says(heard, "slot")
            slot.close()

    def test_a_failed_accept_does_not_stop_the_slot_listening(self, monkeypatch, heard):
        """Windows can fail an accept for a connection its sender dropped before it
        was taken; a slot that stopped listening then would keep every sender off
        the OSR2 until the broker was started again."""
        real_accept = socket.socket.accept
        failures = [ConnectionResetError("dropped before it was taken")]

        def accept(listener):
            if failures:
                raise failures.pop()
            return real_accept(listener)

        monkeypatch.setattr(socket.socket, "accept", accept)
        slot = Osr2Slot(port=0, logger=logging.getLogger(_LOGGER), start_thread=start_daemon_thread)
        written = _Written()
        slot.write_through(written)

        slot.start()
        try:
            with _connected(slot, b"portrait") as portrait:
                portrait.sendall(b"L01000I33\n")

                assert written.next() == ("portrait", "L01000I33")
                assert "dropped before it was taken" in _the_log_says(
                    heard, "could not take a connection")
        finally:
            slot.close()

    def test_the_slot_listens_on_loopback_only(self, listening):
        """T-Code drives the device, so a slot reachable from the network is one
        anybody on it can drive."""
        host, _port = listening.address

        assert host == "127.0.0.1"

    def test_closing_the_slot_hangs_up_on_its_sender_and_stops_listening(self):
        slot = Osr2Slot(port=0, logger=logging.getLogger(_LOGGER), start_thread=start_daemon_thread)
        slot.start()
        address = slot.address
        written = _Written()
        slot.write_through(written)

        with _connected(slot, b"portrait") as portrait:
            portrait.sendall(b"L01000I33\n")
            written.next()

            slot.close()

            assert _what_it_heard_until_hung_up_on(portrait) == b""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as nothing_listens_there:
            nothing_listens_there.bind(address)

    def test_a_sender_stays_connected_while_the_serial_session_opens_again(self, listening):
        """The slot outlives the serial session, which a port error ends and the
        broker opens again: the sender goes on where it was, into the new one."""
        before, after = _Written(), _Written()
        listening.write_through(before)

        with _connected(listening, b"portrait") as portrait:
            portrait.sendall(b"L01000I33\n")
            assert before.next() == ("portrait", "L01000I33")

            listening.write_through(None)
            listening.write_through(after)
            portrait.sendall(b"L02000I33\n")

            assert after.next() == ("portrait", "L02000I33")
        assert before.so_far() == []

    def test_t_code_sent_while_no_session_is_up_is_dropped_rather_than_kept_for_the_next(self):
        """Kept, it would reach the device late, all at once, as moves nobody is
        making any more."""
        slot = _slot()
        ours, _theirs = _a_sender_that_says(b"portrait\nL01000I33\n")
        slot.serve(ours)
        written = _Written()

        slot.write_through(written)

        assert written.so_far() == []

    def test_lines_reach_the_writer_whole_however_the_connection_splits_them(self):
        slot = _slot()
        written = _Written()
        slot.write_through(written)
        ours, theirs = socket.socketpair()

        serving = _serve_on_a_thread(slot, ours)
        theirs.sendall(b"portrait\nL050")
        serving.join(timeout=0.05)
        theirs.sendall(b"00I33\r\n\nL09999I33\n")
        theirs.shutdown(socket.SHUT_WR)
        serving.join(timeout=_WITHIN_S)

        assert written.so_far() == [("portrait", "L05000I33"), ("portrait", "L09999I33")]

    def test_a_sender_whose_line_could_not_be_handed_on_does_not_keep_the_slot(self, heard):
        """Left holding it, a sender nothing reads any more would keep every other
        sender off the device for good."""
        slot = _slot()

        def broken(_sender, _line):
            raise RuntimeError("the writer broke")

        slot.write_through(broken)
        portrait, _theirs = _a_sender_that_says(b"portrait\nL01000I33\n")
        with pytest.raises(RuntimeError):
            slot.serve(portrait)
        main, _theirs = _a_sender_that_says(b"main\n")

        slot.serve(main)

        assert heard.messages[-2] == "The OSR2 is main's"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _keep_sending(sender: Osr2Sender, until, *, within_s: float = _WITHIN_S) -> bool:
    """Send the way a Funestra's frame loop does, a line a frame, until *until*
    holds; the sender dials and names itself over its first few sends."""
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        sender.send("L05000I100")
        if until():
            return True
        time.sleep(0.005)
    return until()


@pytest.fixture
def written(listening) -> _Written:
    written = _Written()
    listening.write_through(written)
    return written


def _a_sender(listening: Osr2Slot, name: str, **kwargs) -> Osr2Sender:
    return Osr2Sender(name, port=listening.address[1], **kwargs)


class TestASendersSide:
    def test_a_sender_that_wants_the_osr2_connects_and_holds_it_under_its_name(self, listening):
        sender = _a_sender(listening, "Portrait")
        sender.want(True)

        assert _keep_sending(sender, lambda: listening.holder == "portrait")
        sender.close()

    def test_what_a_sender_sends_while_it_holds_the_osr2_reaches_the_osr2(
            self, listening, written):
        sender = _a_sender(listening, "main")
        sender.want(True)
        reached = []

        def something_reached_the_osr2():
            reached.extend(written.so_far())
            return bool(reached)

        _keep_sending(sender, something_reached_the_osr2)

        assert reached[0] == ("main", "L05000I100")
        sender.close()

    def test_a_sender_that_does_not_want_the_osr2_never_connects(self, listening, heard):
        sender = _a_sender(listening, "landscape")
        sender.want(True)
        sender.want(False)

        _keep_sending(sender, lambda: False, within_s=0.3)

        assert listening.holder is None
        assert not [message for message in heard.messages if "landscape" in message]

    def test_a_sender_that_lets_go_hangs_up(self, listening, heard):
        sender = _a_sender(listening, "main")
        sender.want(True)
        _keep_sending(sender, lambda: listening.holder == "main")

        sender.want(False)

        assert _the_log_says(heard, "let go") == "main let go of the OSR2"

    def test_the_newer_of_two_senders_holds_the_osr2_and_the_older_never_takes_it_back(
            self, listening, written):
        older, newer = _a_sender(listening, "portrait"), _a_sender(listening, "main")
        older.want(True)
        newer.want(True)
        _keep_sending(older, lambda: listening.holder == "portrait")

        _keep_sending(newer, lambda: listening.holder == "main")
        written.so_far()

        def both_go_on_sending():
            older.send("L01000I100")
            return False

        _keep_sending(newer, both_go_on_sending, within_s=0.5)

        assert listening.holder == "main"
        assert {sender for sender, _line in written.so_far()} == {"main"}
        older.close()
        newer.close()

    def test_a_sender_the_osr2_was_taken_from_stays_silent_until_it_wants_it_afresh(
            self, listening):
        sender = _a_sender(listening, "portrait")
        sender.want(True)
        _keep_sending(sender, lambda: listening.holder == "portrait")

        listening.kick("The park")
        _keep_sending(sender, lambda: False, within_s=0.5)
        silent = listening.holder is None

        sender.want(False)
        sender.want(True)

        assert silent
        assert _keep_sending(sender, lambda: listening.holder == "portrait")
        sender.close()

    def test_a_sender_whose_broker_went_away_connects_again_a_moment_later(self):
        clock = Clock()
        first = Osr2Slot(port=0, logger=logging.getLogger(_LOGGER),
                         start_thread=start_daemon_thread)
        first.start()
        port = first.address[1]
        sender = Osr2Sender("genau", port=port, clock=clock)
        sender.want(True)
        _keep_sending(sender, lambda: first.holder == "genau")
        first.close()
        again = Osr2Slot(port=port, logger=logging.getLogger(_LOGGER),
                         start_thread=start_daemon_thread)
        again.start()
        try:
            def a_while_later():
                clock.now += Osr2Sender.DIAL_AGAIN_AFTER_S / 4
                return again.holder == "genau"

            assert _keep_sending(sender, a_while_later)
        finally:
            sender.close()
            again.close()

    def test_a_sender_reaches_a_broker_that_starts_after_it_did(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        clock = Clock()
        sender = Osr2Sender("main", port=port, clock=clock)
        sender.want(True)
        _keep_sending(sender, lambda: False, within_s=0.3)
        listening = Osr2Slot(port=port, logger=logging.getLogger(_LOGGER),
                             start_thread=start_daemon_thread)
        listening.start()
        try:
            def a_while_later():
                clock.now += Osr2Sender.DIAL_AGAIN_AFTER_S
                return listening.holder == "main"

            assert _keep_sending(sender, a_while_later)
        finally:
            sender.close()
            listening.close()

    def test_a_closed_sender_never_reaches_the_osr2_again(self, listening, heard):
        sender = _a_sender(listening, "portrait")
        sender.want(True)
        _keep_sending(sender, lambda: listening.holder == "portrait")

        sender.close()
        _the_log_says(heard, "let go")
        sender.want(False)
        sender.want(True)
        _keep_sending(sender, lambda: False, within_s=0.5)

        assert listening.holder is None
