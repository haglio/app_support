from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote, urlencode

_A_CALLS_PATIENCE_S = 60
# pCloud's longest login, two years; the device it lists the login under; and the web client's
# number, which is what its sign-in steps answer to, as Warm Gun found.
_A_LOGINS_LIFE_S = 63_072_000
_DEVICE, _DEVICE_ID, _WEB_CLIENT = "Haglio", "haglio-pc", "4"


@dataclass(frozen=True)
class CloudFile:
    fileid: int
    size: int
    hash: int
    duration_s: float | None = None


@dataclass(frozen=True)
class FileLink:
    url: str
    expires: float


class PCloudRefused(Exception):
    def __init__(self, method: str, code: int, message: str, *, token: str | None = None,
                 has_devices: bool | None = None) -> None:
        super().__init__(f"pCloud refused {method}: {message} ({code})")
        self.code, self.token, self.has_devices = code, token, has_devices

    @property
    def needs_signing_in(self) -> bool:
        # pCloud's 1000 (no login given) and 2000 (log in failed) both mean the login is no good.
        return self.code in (1000, 2000)


def _file_of(metadata: dict) -> CloudFile:
    # pCloud reads a video's running time itself and quotes it, as "5.03".
    duration = metadata.get("duration")
    return CloudFile(fileid=metadata["fileid"], size=metadata["size"], hash=metadata["hash"],
                     duration_s=None if duration is None else float(duration))


def _fetched(url: str | urllib.request.Request) -> bytes:
    with urllib.request.urlopen(url, timeout=_A_CALLS_PATIENCE_S) as answer:
        return answer.read()


def _posted(url: str, body: bytes) -> bytes:
    return _fetched(urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}))


def read_span(url: str, start: int, stop: int) -> bytes:
    return _fetched(urllib.request.Request(url, headers={"Range": f"bytes={start}-{stop - 1}"}))


class PCloud:
    def __init__(self, host: str, *, auth: str, get: Callable[[str], bytes] = _fetched,
                 post: Callable[[str, bytes], bytes] = _posted) -> None:
        self._origin = host if "://" in host else f"https://{host}"
        self._auth, self._get, self._post = auth, get, post

    def login(self, username: str, password: str, code: str | None = None) -> str:
        form = {"getauth": "1", "username": username, "password": password, "authexpire": str(_A_LOGINS_LIFE_S),
                "device": _DEVICE, "deviceid": _DEVICE_ID, "os": _WEB_CLIENT}
        if code:
            form |= {"emailtfacode": code, "code": code, "trusted": "1", "trustdevice": "1"}
        return self._signing_in("login", form)["auth"]

    def tfa_login(self, token: str, code: str, *, recovery: bool) -> str:
        form = {"getauth": "1", "token": token, "code": code, "trustdevice": "1",
                "authexpire": str(_A_LOGINS_LIFE_S), "device": _DEVICE}
        return self._signing_in("tfa_loginwithrecoverycode" if recovery else "tfa_login", form)["auth"]

    def email_login_code(self, email: str) -> None:
        self._call("user/sendemailtfamail", signed_in=False, email=email, language="en", os=_WEB_CLIENT)

    def check_emailed_login_code(self, email: str, code: str) -> None:
        self._call("user/checkemailtfacode", signed_in=False, email=email, code=code)

    def send_second_factor_code(self, token: str, *, by_sms: bool) -> None:
        self._call("tfa_sendcodeviasms" if by_sms else "tfa_sendcodeviasysnotification", signed_in=False, token=token)

    def list_folder(self, path: str) -> dict[str, CloudFile]:
        contents = self._call("listfolder", path=path)["metadata"]["contents"]
        return {item["name"]: _file_of(item) for item in contents if not item["isfolder"]}

    def file_link(self, fileid: int) -> FileLink:
        answer = self._call("getfilelink", fileid=str(fileid))
        scheme = self._origin.partition("://")[0]
        # pCloud lists its nearest host first, and hands the path back unescaped.
        return FileLink(url=f"{scheme}://{answer['hosts'][0]}{quote(answer['path'])}", expires=float(answer["expires"]))

    def _call(self, method: str, *, signed_in: bool = True, **query: str) -> dict:
        login = {"auth": self._auth} if signed_in else {}
        asked = urlencode({**query, "timeformat": "timestamp", **login}, quote_via=quote, safe="")
        return _checked(method, self._get(f"{self._origin}/{method}?{asked}"))

    def _signing_in(self, method: str, form: dict[str, str]) -> dict:
        body = urlencode({**form, "timeformat": "timestamp"}, quote_via=quote, safe="").encode("utf-8")
        return _checked(method, self._post(f"{self._origin}/{method}", body))


def _checked(method: str, answered: bytes) -> dict:
    answer = json.loads(answered)
    if answer["result"]:
        raise PCloudRefused(method, answer["result"], answer.get("error", ""), token=answer.get("token"),
                            has_devices=answer.get("hasdevices"))
    return answer
