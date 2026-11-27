from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from app_support.pcloud.api import PCloudRefused
from app_support.pcloud.fetching import CHUNK_BYTES, Entry, Fetcher, NotInPCloud
from app_support.pcloud.spans import asked_span
from app_support.threading_utils import start_daemon_thread

logger = logging.getLogger(__name__)

READ_AHEAD_CHUNKS = 8
FILES_READ_AHEAD_AT_ONCE = 8
_A_LOCAL_COPY_IS_SENT_THIS_MUCH_AT_A_TIME = 1024 * 1024
_MEGABYTE = 1024 * 1024


class LoopbackServer:
    def __init__(self, fetcher: Fetcher, *, chunk_bytes: int = CHUNK_BYTES,
                 local_copy_of: Callable[[str], Path | None] = lambda _cloud_path: None,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._fetcher, self._chunk_bytes, self._local_copy_of, self._now = fetcher, chunk_bytes, local_copy_of, now
        self._read_ahead: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        self._server.daemon_threads = True

    def __enter__(self) -> LoopbackServer:
        start_daemon_thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, name="pcloud-loopback")
        return self

    def __exit__(self, *_exc) -> None:
        self._server.shutdown()
        self._server.server_close()

    def url_for(self, cloud_path: str) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/{quote(cloud_path.lstrip('/'))}"

    def answer(self, handler: BaseHTTPRequestHandler, cloud_path: str) -> None:
        began = self._now()
        try:
            entry = self._fetcher.entry(cloud_path)
        except NotInPCloud:
            self._answer_from_this_computer(handler, self._local_copy_of(cloud_path))
            return
        except PCloudRefused as refused:
            handler.send_error(502, str(refused))
            return
        start, stop = _begun(handler, entry.size)
        sent = {True: 0, False: 0}
        first_byte_after_s = None
        for index in range(start // self._chunk_bytes, (stop - 1) // self._chunk_bytes + 1):
            begins = index * self._chunk_bytes
            self._plan_what_follows(entry, index)
            held = self._fetcher.holds(entry, index)
            try:
                data = self._fetcher.chunk(entry, index)
            except OSError as failed:
                logger.warning("Could not fetch %s for its player: %s", entry.path, failed)
                return
            piece = data[max(start, begins) - begins:min(stop, begins + len(data)) - begins]
            try:
                handler.wfile.write(piece)
            except OSError:
                return
            if first_byte_after_s is None:
                first_byte_after_s = self._now() - began
            sent[held] += len(piece)
        logger.info("pCloud gave %s bytes %d-%d: %.1f MB from the cache, %.1f MB fetched, the first byte after %d ms",
                    entry.path.rsplit("/", 1)[-1], start, stop - 1, sent[True] / _MEGABYTE, sent[False] / _MEGABYTE,
                    round((first_byte_after_s or 0.0) * 1000))

    @staticmethod
    def _answer_from_this_computer(handler: BaseHTTPRequestHandler, local: Path | None) -> None:
        if local is None or not local.is_file():
            handler.send_error(404, "pCloud has no such file")
            return
        start, stop = _begun(handler, local.stat().st_size)
        with local.open("rb") as file:
            file.seek(start)
            while start < stop:
                piece = file.read(min(_A_LOCAL_COPY_IS_SENT_THIS_MUCH_AT_A_TIME, stop - start))
                try:
                    handler.wfile.write(piece)
                except OSError:
                    return
                start += len(piece)

    def _plan_what_follows(self, entry: Entry, index: int) -> None:
        last = (entry.size - 1) // self._chunk_bytes
        owner = f"reading {entry.key}"
        self._fetcher.plan(owner, [(entry, following) for following in range(index + 1, min(last, index + READ_AHEAD_CHUNKS) + 1)],
                           being_read=True)
        with self._lock:
            self._read_ahead[owner] = None
            self._read_ahead.move_to_end(owner)
            dropped = [self._read_ahead.popitem(last=False)[0]
                       for _ in range(len(self._read_ahead) - FILES_READ_AHEAD_AT_ONCE)]
        for stale in dropped:
            self._fetcher.plan(stale, [])


def _begun(handler: BaseHTTPRequestHandler, size: int) -> tuple[int, int]:
    asked = handler.headers.get("Range")
    start, stop = asked_span(asked, size)
    handler.send_response(206 if asked else 200)
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Content-Length", str(stop - start))
    if asked:
        handler.send_header("Content-Range", f"bytes {start}-{stop - 1}/{size}")
    handler.end_headers()
    return start, stop


def _handler_for(server: LoopbackServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            server.answer(self, "/" + unquote(urlparse(self.path).path.lstrip("/")))

        def log_message(self, *_args) -> None:
            pass

    return Handler
