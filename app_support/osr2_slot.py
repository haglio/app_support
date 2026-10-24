"""The one way to the OSR2: the broker's slot, which one sender holds at a time --
whoever connects takes it from whoever had it, and a hold takes it from anyone --
and a sender's side of it, which holds the slot only while it wants the device and
never makes the loop that sends wait.

A sender connects to :data:`app_support.ports.OSR2_SLOT`, says its name on the
first line, then sends T-Code a line at a time; when another sender or a hold takes
the OSR2, the broker says so before it stops listening to the line."""
from __future__ import annotations

import contextlib
import select
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import ports

__all__ = ["Osr2Sender", "Osr2Slot"]

_TAKEN = b"taken\n"

Writer = Callable[[str, str], None]


def _hello(sender: str) -> bytes:
    return f"{sender.lower()}\n".encode("ascii")


def _read_hello(line: bytes) -> str:
    return line.decode("ascii", errors="replace").strip().casefold()


@dataclass(frozen=True, eq=False)
class _Sender:
    name: str
    connection: socket.socket

    def taken_from(self) -> None:
        with contextlib.suppress(OSError):
            self.connection.sendall(_TAKEN)
            self.connection.shutdown(socket.SHUT_WR)

    def hang_up(self) -> None:
        with contextlib.suppress(OSError):
            self.connection.shutdown(socket.SHUT_RDWR)
        self.connection.close()


class Osr2Slot:
    HELLO_WITHIN_S = 1.0
    ACCEPT_AGAIN_AFTER_S = 1.0

    def __init__(self, *, port: int, logger, start_thread):
        self._port = port
        self._logger = logger
        self._start_thread = start_thread
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._listener: socket.socket | None = None
        self._holder: _Sender | None = None
        self._writer: Writer | None = None

    def start(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._listener.bind(("127.0.0.1", self._port))
            self._listener.listen()
        except OSError:
            self._logger.exception("The OSR2's slot could not listen on 127.0.0.1:%s, "
                                   "so no sender can connect to it", self._port)
            return
        self._logger.info("OSR2 slot: %s:%s", *self.address)
        self._start_thread(target=self._accept, args=(self._listener,), name="broker-osr2-slot")

    @property
    def address(self) -> tuple[str, int]:
        return self._listener.getsockname()

    @property
    def holder(self) -> str | None:
        with self._lock:
            return None if self._holder is None else self._holder.name

    def close(self) -> None:
        self._closed.set()
        self._swap_holder(None, taken=False)
        if self._listener is not None:
            self._listener.close()

    def kick(self, taker: str) -> None:
        previous = self._swap_holder(None, taken=True)
        if previous is not None:
            self._logger.info("%s took the OSR2 from %s", taker, previous.name)

    def _accept(self, listener: socket.socket) -> None:
        while not self._closed.is_set():
            try:
                connection, _address = listener.accept()
            except OSError as exc:
                if not self._closed.is_set():
                    self._logger.warning("The OSR2's slot could not take a connection: %s", exc)
                    self._closed.wait(self.ACCEPT_AGAIN_AFTER_S)
                continue
            self._start_thread(target=self.serve, args=(connection,), name="broker-osr2-sender")

    def write_through(self, writer: Writer | None) -> None:
        with self._lock:
            self._writer = writer

    def serve(self, connection) -> None:
        with connection:
            name, received = self._hello(connection)
            if not name:
                return
            sender = _Sender(name, connection)
            self._take(sender)
            try:
                self._relay(sender, received)
            finally:
                self._let_go(sender)

    def _hello(self, connection) -> tuple[str, bytes]:
        deadline = time.monotonic() + self.HELLO_WITHIN_S
        received = b""
        while b"\n" not in received:
            left = deadline - time.monotonic()
            if left <= 0:
                return "", b""
            connection.settimeout(left)
            try:
                data = connection.recv(256)
            except OSError:
                return "", b""
            if not data:
                return "", b""
            received += data
        first, _, rest = received.partition(b"\n")
        return _read_hello(first), rest

    def _take(self, sender: _Sender) -> None:
        previous = self._swap_holder(sender, taken=True)
        if previous is None:
            self._logger.info("The OSR2 is %s's", sender.name)
        else:
            self._logger.info("%s took the OSR2 from %s", sender.name, previous.name)

    def _swap_holder(self, holder: _Sender | None, *, taken: bool) -> _Sender | None:
        with self._lock:
            previous, self._holder = self._holder, holder
        if previous is not None:
            if taken:
                previous.taken_from()
            else:
                previous.hang_up()
        return previous

    def _relay(self, sender: _Sender, received: bytes) -> None:
        sender.connection.settimeout(None)
        while True:
            *lines, received = received.split(b"\n")
            for raw in lines:
                line = raw.decode("ascii", errors="replace").strip()
                if line and not self._hand_on_if_held(sender, line):
                    self._hear_out(sender)
                    return
            try:
                data = sender.connection.recv(4096)
            except OSError:
                return
            if not data:
                return
            received += data

    @staticmethod
    def _hear_out(sender: _Sender) -> None:
        """Read what a sender the OSR2 was taken from goes on sending until it hangs
        up, so its line is never reset with the word that it was taken unread."""
        with contextlib.suppress(OSError):
            while sender.connection.recv(4096):
                pass

    def _hand_on_if_held(self, sender: _Sender, line: str) -> bool:
        with self._lock:
            if self._holder is not sender:
                return False
            writer = self._writer
        if writer is not None:
            writer(sender.name, line)
        return True

    def _let_go(self, sender: _Sender) -> None:
        with self._lock:
            if self._holder is not sender:
                return
            self._holder = None
        self._logger.info("%s let go of the OSR2", sender.name)


class Osr2Sender:
    DIAL_AGAIN_AFTER_S = 1.0

    def __init__(self, sender: str, *, port: int | None = None,
                 host: str = "127.0.0.1", clock: Callable[[], float] = time.monotonic) -> None:
        self._sender = sender
        self._address = (host, port or ports.OSR2_SLOT)
        self._clock = clock
        self._wanted = False
        self._taken = False
        self._connection: socket.socket | None = None
        self._said_hello = False
        self._dial_again_at = float("-inf")
        self._closed = False
        self._lock = threading.Lock()

    def want(self, wanted: bool) -> None:
        with self._lock:
            if wanted == self._wanted:
                return
            self._wanted, self._taken = wanted, False
            if not wanted:
                self._hang_up()

    def send(self, command: str) -> None:
        with self._lock:
            if self._wanted and not (self._taken or self._closed):
                self._send(command)

    def _send(self, command: str) -> None:
        if self._connection is None:
            self._dial()
        elif not self._said_hello:
            self._greet()
        elif not self._the_broker_hung_up():
            self._write(f"{command}\n".encode("ascii"))

    def _dial(self) -> None:
        if self._clock() < self._dial_again_at:
            return
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connection.setblocking(False)
        connection.connect_ex(self._address)
        self._connection = connection

    def _greet(self) -> None:
        _readable, writable, failed = select.select([], [self._connection], [self._connection], 0)
        if failed:
            self._dial_later()
        elif writable:
            self._said_hello = self._write(_hello(self._sender))

    def _the_broker_hung_up(self) -> bool:
        readable, _writable, _failed = select.select([self._connection], [], [], 0)
        if not readable:
            return False
        try:
            said = self._connection.recv(64)
        except OSError:
            said = b""
        if _TAKEN in said:
            self._taken = True
            self._hang_up()
        else:
            self._dial_later()
        return True

    def _write(self, data: bytes) -> bool:
        try:
            self._connection.send(data)
        except OSError:
            self._dial_later()
            return False
        return True

    def _dial_later(self) -> None:
        self._hang_up()
        self._dial_again_at = self._clock() + self.DIAL_AGAIN_AFTER_S

    def _hang_up(self) -> None:
        connection, self._connection, self._said_hello = self._connection, None, False
        if connection is not None:
            connection.close()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._hang_up()
