from __future__ import annotations

import ctypes
from ctypes import wintypes

from app_support.win32_loader import load_dll

THE_NAMESPACE_EVERY_LOGIN_SESSION_SHARES = "Global\\"

_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_WAIT_FAILED = 0xFFFFFFFF
_A_WAIT_FOR_EVER_LOOKS_UP_FOR_CTRL_C_EVERY_MS = 500

_kernel32 = load_dll("kernel32", use_last_error=True)

_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]

_kernel32.WaitForMultipleObjects.restype = wintypes.DWORD
_kernel32.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL,
                                             wintypes.DWORD]

_kernel32.ReleaseMutex.restype = wintypes.BOOL
_kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]

_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _first_ready(handles: list[int], timeout: float | None) -> int | None:
    array = (wintypes.HANDLE * len(handles))(*handles)
    while True:
        ms = _A_WAIT_FOR_EVER_LOOKS_UP_FOR_CTRL_C_EVERY_MS if timeout is None else max(0, int(timeout * 1000))
        result = _kernel32.WaitForMultipleObjects(len(handles), array, False, ms)
        if result == _WAIT_FAILED:
            raise ctypes.WinError(ctypes.get_last_error())
        for first in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
            if first <= result < first + len(handles):
                return result - first
        if timeout is not None:
            return None


class SingleInstanceLock:
    def __init__(self, name: str) -> None:
        self._name = name
        self._handle: int | None = None
        self._held = False

    @property
    def handle(self) -> int:
        if self._handle is None:
            handle = _kernel32.CreateMutexW(None, False, self._name)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            self._handle = handle
        return self._handle

    def acquire(self, timeout: float | None = None) -> bool:
        return first_taken([self], timeout=timeout) is self

    def taken_by_waiting(self) -> SingleInstanceLock:
        self._held = True
        return self

    def release(self) -> None:
        if self._held and self._handle is not None:
            _kernel32.ReleaseMutex(self._handle)
            self._held = False

    def close(self) -> None:
        self.release()
        if self._handle is not None:
            _kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> SingleInstanceLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def first_taken(locks: list[SingleInstanceLock], *, timeout: float | None) -> SingleInstanceLock | None:
    ready = _first_ready([lock.handle for lock in locks], timeout)
    return None if ready is None else locks[ready].taken_by_waiting()


def held_elsewhere(lock: SingleInstanceLock) -> bool:
    if lock.acquire(timeout=0):
        lock.release()
        return False
    return True


_kernel32.CreateSemaphoreW.restype = wintypes.HANDLE
_kernel32.CreateSemaphoreW.argtypes = [wintypes.LPVOID, wintypes.LONG, wintypes.LONG, wintypes.LPCWSTR]

_kernel32.ReleaseSemaphore.restype = wintypes.BOOL
_kernel32.ReleaseSemaphore.argtypes = [wintypes.HANDLE, wintypes.LONG, ctypes.POINTER(wintypes.LONG)]

_MOST_NUMBERS = 2 ** (8 * ctypes.sizeof(wintypes.LONG) - 1) - 1


class Lane:
    def __init__(self, name: str) -> None:
        self.front = SingleInstanceLock(name)
        self._name = name
        self._numbers = _Numbers(f"{name}_numbers")
        self._number = 0
        self._place: SingleInstanceLock | None = None

    def join(self) -> None:
        with SingleInstanceLock(f"{self._name}_joining"):
            self._number = self._numbers.take()
            self._place = self._place_of(self._number)
            self._place.acquire()

    def runs_ahead(self) -> int:
        earlier = [self._place_of(number) for number in range(self._number)]
        try:
            return sum(held_elsewhere(place) for place in earlier)
        finally:
            for place in earlier:
                place.close()

    def wait_for_the_front(self) -> None:
        for earlier in range(self._number):
            with self._place_of(earlier):
                pass
        self.front.acquire()

    def leave(self) -> None:
        self.front.close()
        if self._place is not None:
            self._place.close()
        self._numbers.close()

    def _place_of(self, number: int) -> SingleInstanceLock:
        return SingleInstanceLock(f"{self._name}_{number}")


class _Numbers:
    def __init__(self, name: str) -> None:
        self._name = name
        self._handle: int | None = None

    def take(self) -> int:
        if self._handle is None:
            handle = _kernel32.CreateSemaphoreW(None, 0, _MOST_NUMBERS, self._name)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            self._handle = handle
        count_before = wintypes.LONG()
        if not _kernel32.ReleaseSemaphore(self._handle, 1, ctypes.byref(count_before)):
            raise ctypes.WinError(ctypes.get_last_error())
        return count_before.value

    def close(self) -> None:
        if self._handle is not None:
            _kernel32.CloseHandle(self._handle)
            self._handle = None

