from __future__ import annotations

import json
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from urllib.parse import parse_qs, unquote, urlparse

from app_support.pcloud.spans import asked_span
from app_support.threading_utils import start_daemon_thread

A_MADE_UP_LOGIN = "made-up-login"


class FakePCloud:
    def __init__(self, files: dict[str, bytes], *, auth: str = A_MADE_UP_LOGIN,
                 durations: dict[str, float] | None = None) -> None:
        self.auth = auth
        self._files = dict(files)
        self._durations = dict(durations or {})
        self._paths_by_id = dict(enumerate(sorted(files), start=1))
        self._ids_by_path = {path: fileid for fileid, path in self._paths_by_id.items()}
        self.downloads: list[tuple[str, int, int]] = []
        self.calls: list[str] = []
        self.links_expire = 4_102_444_800
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        self.host = f"127.0.0.1:{self._server.server_port}"
        self.origin = f"http://{self.host}"

    def put(self, path: str, content: bytes) -> None:
        fileid = max(self._paths_by_id, default=0) + 1
        self._files[path] = content
        self._paths_by_id[fileid] = path
        self._ids_by_path[path] = fileid

    def __enter__(self) -> FakePCloud:
        start_daemon_thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, name="fake-pcloud")
        return self

    def __exit__(self, *_exc) -> None:
        self._server.shutdown()
        self._server.server_close()

    def answer(self, method: str, query: dict[str, str]) -> dict:
        self.calls.append(method)
        if query.get("auth") != self.auth:
            return {"result": 2000, "error": "Log in failed."}
        if method == "listfolder":
            return self._listing_of(query["path"].rstrip("/"))
        if method == "getfilelink":
            path = self._paths_by_id[int(query["fileid"])]
            return {"result": 0, "hosts": [self.host], "expires": self.links_expire,
                    "path": f"/dl/{self._ids_by_path[path]}/{PurePosixPath(path).name}"}
        return {"result": 2234, "error": f"The fake knows no {method}."}

    def content_of(self, fileid: int) -> tuple[str, bytes]:
        path = self._paths_by_id[fileid]
        return path, self._files[path]

    def _listing_of(self, folder: str) -> dict:
        inside = [path for path in self._files if str(PurePosixPath(path).parent) == (folder or "/")]
        if not inside:
            return {"result": 2005, "error": "Directory does not exist."}
        return {"result": 0, "metadata": {"isfolder": True, "name": PurePosixPath(folder).name,
                                          "contents": [self._file_metadata(path) for path in inside]}}

    def _file_metadata(self, path: str) -> dict:
        content = self._files[path]
        metadata = {"fileid": self._ids_by_path[path], "size": len(content), "hash": zlib.crc32(content),
                    "name": PurePosixPath(path).name, "isfolder": False}
        if path in self._durations:
            metadata["duration"] = str(self._durations[path])
        return metadata


def _handler_for(cloud: FakePCloud) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            asked = urlparse(self.path)
            if asked.path.startswith("/dl/"):
                self._download(int(unquote(asked.path).split("/")[2]))
            else:
                query = {name: values[0] for name, values in parse_qs(asked.query).items()}
                self._send(200, json.dumps(cloud.answer(asked.path.strip("/"), query)).encode("utf-8"))

        def _download(self, fileid: int) -> None:
            path, content = cloud.content_of(fileid)
            start, stop = asked_span(self.headers.get("Range"), len(content))
            cloud.downloads.append((path, start, stop))
            self._send(206, content[start:stop], {"Content-Range": f"bytes {start}-{stop - 1}/{len(content)}"})

        def _send(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
            self.send_response(status)
            for name, value in {**(headers or {}), "Content-Length": str(len(body))}.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:
            pass

    return Handler
