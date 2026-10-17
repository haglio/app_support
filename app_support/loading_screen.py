"""The loading screen a launcher shows from the click until the app's own is up.

An app's launcher can have a wait before the app's own code runs -- an update of
the app, or of an app it hosts -- and the app's loading screen cannot come up
from a venv that is being installed.  So the launcher shows the pictures the
app's own loading screen left at its last start, from this package's own
interpreter, with each update it waits on as a step; the app's loading screen
then takes over from it where it stands.  This module is the folder they meet
in and the program the launcher runs.

Standard library only.
"""
from __future__ import annotations

import ctypes
import dataclasses
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from ctypes import wintypes
from pathlib import Path
from typing import TYPE_CHECKING

from app_support import win32

if TYPE_CHECKING:
    from app_support.production_update import UpdateProgress

FOLDER = "HAGLIO_LOADING_SCREEN"
LINES = "HAGLIO_LOADING_SCREEN_LINES"
OPENING = "opening.png"
FULL = "full.png"
PICTURES = "pictures.json"
SHOWN = "shown.json"
TAKEN = "taken"
STARTED = "started"
ENDED = "ended"
CANCELED = "canceled"
UPDATED = "updated"
SAID_AT_EACH_LAUNCH = (SHOWN, TAKEN, STARTED, ENDED, CANCELED, UPDATED)
# Longer than any app takes from its start to its own loading screen, so an app
# that never puts one up is not covered for long.
TAKING_OVER_WITHIN_S = 30.0
# Rewritten every moment the launcher's loading screen is up, so a file older
# than this was left by one that is gone.
STANDING_FOR_S = 2.0
# How much of what is left of the bar an update fills, leaving the rest for the
# app's own start.
UPDATE_SHARE = 0.6
POLL_MS = 100
_NEAREST = 2

Box = tuple[int, int, int, int]


# --- Where the launcher and the app meet ----------------------------------------


@dataclasses.dataclass(frozen=True)
class Shown:
    left: int
    top: int
    fraction: float


@dataclasses.dataclass(frozen=True)
class Pictures:
    opening: Path
    full: Path
    bar: Box
    covers_every_monitor: bool
    shown_for: Mapping[str, Path]

    def updating(self, line: str) -> Path | None:
        return self.shown_for.get(line)


@dataclasses.dataclass(frozen=True)
class MeetingPlace:
    folder: Path
    lines: tuple[str, ...]

    def leave_pictures(self, *, opening: bytes, full: bytes, updating: Sequence[bytes], bar: Box,
                       covers_every_monitor: bool) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        _replace_whole(self.folder / OPENING, opening)
        _replace_whole(self.folder / FULL, full)
        for index, picture in enumerate(updating):
            _replace_whole(self.folder / _updating(index), picture)
        _replace_whole(self.folder / PICTURES, json.dumps(
            {"bar": list(bar), "covers_every_monitor": covers_every_monitor,
             "lines": list(self.lines[:len(updating)])}).encode("utf-8"))

    def pictures(self) -> Pictures | None:
        try:
            document = json.loads((self.folder / PICTURES).read_text(encoding="utf-8"))
            bar = tuple(int(edge) for edge in document["bar"])
            lines = [str(line) for line in document["lines"]]
            covers_every_monitor = bool(document["covers_every_monitor"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return Pictures(self.folder / OPENING, self.folder / FULL, bar, covers_every_monitor,
                        {line: self.folder / _updating(index) for index, line in enumerate(lines)})

    def stand(self, shown: Shown) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        _replace_whole(self.folder / SHOWN, json.dumps(dataclasses.asdict(shown)).encode("utf-8"))

    def standing(self) -> Shown | None:
        path = self.folder / SHOWN
        try:
            if time.time() - path.stat().st_mtime > STANDING_FOR_S:
                return None
            document = json.loads(path.read_text(encoding="utf-8"))
            return Shown(int(document["left"]), int(document["top"]), float(document["fraction"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def step_aside(self) -> None:
        (self.folder / SHOWN).unlink(missing_ok=True)

    def say_taken(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / TAKEN).touch()

    @property
    def taken(self) -> bool:
        return (self.folder / TAKEN).exists()


def meeting_place(environment: Mapping[str, str]) -> MeetingPlace | None:
    if not environment.get(FOLDER):
        return None
    return MeetingPlace(Path(environment[FOLDER]), tuple(json.loads(environment.get(LINES) or "[]")))


def handed_over(environment: MutableMapping[str, str]) -> dict[str, str]:
    return {name: environment.pop(name) for name in (FOLDER, LINES) if name in environment}


def _updating(index: int) -> str:
    return f"updating-{index}.png"


def _replace_whole(path: Path, data: bytes) -> None:
    writing = path.with_name(f"{path.name}.{os.getpid()}.writing")
    writing.write_bytes(data)
    os.replace(writing, path)


# --- What it shows ------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Frame:
    picture: Path
    fraction: float


class Showing:
    def __init__(self, place: MeetingPlace, pictures: Pictures, checkouts: Sequence[Path], *,
                 progress_of: Callable[[Path], UpdateProgress | None], clock: Callable[[], float],
                 launcher_running: Callable[[], bool]):
        self._place = place
        self._pictures = pictures
        self._checkouts = tuple(checkouts)
        self._progress_of = progress_of
        self._clock = clock
        self._launcher_running = launcher_running
        self._fraction = 0.0
        self._update: tuple[int, float] | None = None

    def tick(self) -> Frame:
        for index, checkout in enumerate(self._checkouts):
            if progress := self._progress_of(checkout):
                return Frame(self._updating(index), self._moved_on(index, progress))
        self._update = None
        return Frame(self._pictures.opening, self._fraction)

    def over(self) -> bool:
        if self._place.taken or (self._place.folder / ENDED).exists():
            return True
        try:
            started = (self._place.folder / STARTED).stat().st_mtime
        except OSError:
            return not self._launcher_running()
        return self._clock() - started > TAKING_OVER_WITHIN_S

    def cancel(self) -> bool:
        if (self._place.folder / STARTED).exists():
            return False
        (self._place.folder / CANCELED).touch()
        return True

    def _updating(self, index: int) -> Path:
        line = self._place.lines[index] if index < len(self._place.lines) else None
        return (line is not None and self._pictures.updating(line)) or self._pictures.opening

    def _moved_on(self, index: int, progress: UpdateProgress) -> float:
        if self._update is None or self._update[0] != index:
            self._update = (index, self._fraction)
        began_at = self._update[1]
        reaching = began_at + (1 - began_at) * UPDATE_SHARE * progress.fraction(now=self._clock())
        self._fraction = max(self._fraction, reaching)
        return self._fraction


# --- Where it stands --------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Screens:
    virtual: Box
    primary: tuple[int, int]
    pointer_work_area: Box


@dataclasses.dataclass(frozen=True)
class Placement:
    window: Box
    panel: tuple[int, int]

    @property
    def panel_on_screen(self) -> tuple[int, int]:
        return self.window[0] + self.panel[0], self.window[1] + self.panel[1]


def over_every_monitor(size: tuple[int, int], screens: Screens, *,
                       panel_at: tuple[int, int] | None = None) -> Placement:
    x, y, _width, _height = screens.virtual
    if panel_at is None:
        panel_at = (screens.primary[0] // 2 - size[0] // 2, screens.primary[1] // 2 - size[1] // 2)
    return Placement(screens.virtual, (panel_at[0] - x, panel_at[1] - y))


def where_the_pointer_is(size: tuple[int, int], screens: Screens) -> Placement:
    x, y, width, height = screens.pointer_work_area
    return Placement((x + (width - size[0]) // 2, y + (height - size[1]) // 2, *size), (0, 0))


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


def _user32():  # pragma: no cover -- Windows itself
    user32 = ctypes.WinDLL("user32")
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
    return user32


def screens(*, user32: Callable[[], object] = _user32) -> Screens | None:
    try:
        windows = user32()
        windows.SetProcessDPIAware()
        metric = windows.GetSystemMetrics
        pointer = wintypes.POINT()
        windows.GetCursorPos(ctypes.byref(pointer))
        info = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
        windows.GetMonitorInfoW(windows.MonitorFromPoint(pointer, _NEAREST), ctypes.byref(info))
    except (AttributeError, OSError):
        return None
    work = info.rcWork
    return Screens(virtual=(metric(76), metric(77), metric(78), metric(79)), primary=(metric(0), metric(1)),
                   pointer_work_area=(work.left, work.top, work.right - work.left, work.bottom - work.top))


# --- The window ---------------------------------------------------------------------


class _Window:  # pragma: no cover -- a window, run on a desktop of its own
    def __init__(self, place: MeetingPlace, pictures: Pictures, showing: Showing, screens: Screens | None):
        import tkinter  # noqa: PLC0415

        self._place, self._pictures, self._showing = place, pictures, showing
        self._root = tkinter.Tk()
        if screens is None:
            size = (self._root.winfo_screenwidth(), self._root.winfo_screenheight())
            screens = Screens(virtual=(0, 0, *size), primary=size, pointer_work_area=(0, 0, *size))
        self._root.withdraw()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._images: dict[Path, object] = {}
        opening, self._full = self._image(pictures.opening), self._image(pictures.full)
        size = (opening.width(), opening.height())
        self._shown = tkinter.PhotoImage(master=self._root, width=size[0], height=size[1])
        ground = "#{:02x}{:02x}{:02x}".format(*opening.get(0, 0))
        placement = (over_every_monitor(size, screens) if pictures.covers_every_monitor
                     else where_the_pointer_is(size, screens))
        self._panel_on_screen = placement.panel_on_screen
        x, y, width, height = placement.window
        self._root.geometry(f"{width}x{height}+{x}+{y}")
        self._root.configure(bg=ground)
        label = tkinter.Label(self._root, image=self._shown, borderwidth=0, highlightthickness=0, bg=ground)
        label.place(x=placement.panel[0], y=placement.panel[1])
        self._root.bind("<Escape>", self._escape)
        self._last: Frame | None = None

    def run(self) -> None:
        self._draw(self._showing.tick())
        self._root.deiconify()
        self._root.update()
        self._root.focus_force()
        self._root.after(POLL_MS, self._poll)
        self._root.mainloop()

    def _image(self, path: Path):
        import tkinter  # noqa: PLC0415

        if path not in self._images:
            self._images[path] = tkinter.PhotoImage(master=self._root, file=str(path))
        return self._images[path]

    def _poll(self) -> None:
        try:
            if self._showing.over():
                self._go()
                return
            self._draw(self._showing.tick())
        except OSError:
            pass
        self._root.after(POLL_MS, self._poll)

    def _draw(self, frame: Frame) -> None:
        if frame != self._last:
            self._shown.tk.call(self._shown, "copy", self._image(frame.picture))
            x, y, width, height = self._pictures.bar
            if filled := round(width * max(0.0, min(1.0, frame.fraction))):
                self._shown.tk.call(self._shown, "copy", self._full, "-from", x, y, x + filled, y + height,
                                    "-to", x, y)
            self._last = frame
        self._place.stand(Shown(*self._panel_on_screen, frame.fraction))

    def _escape(self, _event: object = None) -> None:
        if self._showing.cancel():
            self._go()

    def _go(self) -> None:
        self._place.step_aside()
        self._root.destroy()


def _the_launcher_running() -> Callable[[], bool]:  # pragma: no cover -- the process that started this one
    launcher = os.getppid()
    started = win32.process_started(launcher)
    return lambda: started is not None and win32.process_started(launcher) == started


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover -- a window, run on a desktop of its own
    from app_support.production_update import progress_of  # noqa: PLC0415

    place = meeting_place(os.environ)
    pictures = place.pictures() if place else None
    if pictures is None:
        return 0
    checkouts = [Path(each) for each in (sys.argv[1:] if argv is None else argv)]
    showing = Showing(place, pictures, checkouts, progress_of=progress_of, clock=time.time,
                      launcher_running=_the_launcher_running())
    _Window(place, pictures, showing, screens()).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
