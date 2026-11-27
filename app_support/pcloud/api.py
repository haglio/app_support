from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote, urlencode

_A_CALLS_PATIENCE_S = 60


@dataclass(frozen=True)
class CloudFile:
    fileid: int
    size: int
    hash: int


@dataclass(frozen=True)
class FileLink:
    url: str
    expires: float


class PCloudRefused(Exception):
    def __init__(self, method: str, code: int, message: str) -> None:
        super().__init__(f"pCloud refused {method}: {message} ({code})")
        self.code = code

    @property
    def needs_signing_in(self) -> bool:
        # pCloud's 1000 (no login given) and 2000 (log in failed) both mean the login is no good.
        return self.code in (1000, 2000)


def _file_of(metadata: dict) -> CloudFile:
    return CloudFile(fileid=metadata["fileid"], size=metadata["size"], hash=metadata["hash"])


def _fetched(url: str | urllib.request.Request) -> bytes:
    with urllib.request.urlopen(url, timeout=_A_CALLS_PATIENCE_S) as answer:
        return answer.read()


def read_span(url: str, start: int, stop: int) -> bytes:
    return _fetched(urllib.request.Request(url, headers={"Range": f"bytes={start}-{stop - 1}"}))


class PCloud:
    def __init__(self, host: str, *, auth: str, get: Callable[[str], bytes] = _fetched) -> None:
        self._origin = host if "://" in host else f"https://{host}"
        self._auth, self._get = auth, get

    def list_folder(self, path: str) -> dict[str, CloudFile]:
        contents = self._call("listfolder", path=path)["metadata"]["contents"]
        return {item["name"]: _file_of(item) for item in contents if not item["isfolder"]}

    def file_link(self, fileid: int) -> FileLink:
        answer = self._call("getfilelink", fileid=str(fileid))
        scheme = self._origin.partition("://")[0]
        # pCloud lists its nearest host first, and hands the path back unescaped.
        return FileLink(url=f"{scheme}://{answer['hosts'][0]}{quote(answer['path'])}", expires=float(answer["expires"]))

    def _call(self, method: str, **query: str) -> dict:
        asked = urlencode({**query, "timeformat": "timestamp", "auth": self._auth}, quote_via=quote, safe="")
        answer = json.loads(self._get(f"{self._origin}/{method}?{asked}"))
        if answer["result"]:
            raise PCloudRefused(method, answer["result"], answer.get("error", ""))
        return answer
