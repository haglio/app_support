"""The loading screen a launcher shows from the click until the app's own is up."""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

import pytest
from eventually import eventually

from app_support import loading_screen, production_update, win32


class TestWhereTheLauncherAndTheAppMeet:
    def test_the_app_finds_the_place_in_the_environment_its_launcher_started_it_with(self, tmp_path):
        environment = {loading_screen.FOLDER: str(tmp_path / "screen"),
                       loading_screen.LINES: '["Updating Example...", "Updating Hosted..."]'}

        place = loading_screen.meeting_place(environment)

        assert place.folder == tmp_path / "screen"
        assert place.lines == ("Updating Example...", "Updating Hosted...")

    def test_an_app_started_without_a_launcher_that_shows_one_has_nowhere_to_meet_it(self):
        assert loading_screen.meeting_place({}) is None

    def test_the_app_hands_the_place_to_its_loading_screen_alone(self, tmp_path):
        environment = {loading_screen.FOLDER: str(tmp_path / "screen"), loading_screen.LINES: "[]", "PATH": "x"}

        handed = loading_screen.handed_over(environment)

        assert handed == {loading_screen.FOLDER: str(tmp_path / "screen"), loading_screen.LINES: "[]"}
        assert environment == {"PATH": "x"}


def a_place(tmp_path: Path, *lines: str) -> loading_screen.MeetingPlace:
    return loading_screen.MeetingPlace(tmp_path / "screen", lines or ("Updating Example...",))


class TestThePicturesTheAppLeaves:
    def test_the_next_click_finds_the_pictures_the_app_left(self, tmp_path):
        place = a_place(tmp_path)

        place.leave_pictures(opening=b"opening", full=b"full", updating=[b"updating"], bar=(24, 220, 360, 18),
                             covers_every_monitor=True)
        pictures = place.pictures()

        assert pictures.opening.read_bytes() == b"opening"
        assert pictures.full.read_bytes() == b"full"
        assert pictures.updating("Updating Example...").read_bytes() == b"updating"
        assert pictures.bar == (24, 220, 360, 18)
        assert pictures.covers_every_monitor

    def test_a_launch_before_the_app_ever_left_pictures_has_none(self, tmp_path):
        assert a_place(tmp_path).pictures() is None

    def test_a_line_the_launcher_has_changed_since_has_no_picture_yet(self, tmp_path):
        a_place(tmp_path, "Updating Example...").leave_pictures(
            opening=b"opening", full=b"full", updating=[b"updating"], bar=(0, 0, 1, 1), covers_every_monitor=False)

        pictures = a_place(tmp_path, "Bringing Example up to date...").pictures()

        assert pictures.updating("Bringing Example up to date...") is None


class TestWhereTheAppSaysItsWindowComesUp:
    def test_the_next_click_finds_what_the_app_said(self, tmp_path):
        said = loading_screen.AppWindow(size=(1954, 600), kept_on=(2560, 3, 1440, 3440))

        a_place(tmp_path).say_where_the_app_comes_up(said)

        assert a_place(tmp_path).where_the_app_comes_up() == said

    def test_an_app_that_keeps_its_window_nowhere_says_how_big_it_is_alone(self, tmp_path):
        said = loading_screen.AppWindow(size=(1954, 600))

        a_place(tmp_path).say_where_the_app_comes_up(said)

        assert a_place(tmp_path).where_the_app_comes_up() == said

    def test_a_launch_before_the_app_ever_said_has_nothing(self, tmp_path):
        assert a_place(tmp_path).where_the_app_comes_up() is None

    def test_a_window_moved_to_another_monitor_is_what_the_next_click_finds(self, tmp_path):
        place = a_place(tmp_path)
        place.say_where_the_app_comes_up(loading_screen.AppWindow(kept_on=(0, 0, 2560, 1440)))

        place.say_where_the_app_comes_up(loading_screen.AppWindow(kept_on=(2560, 3, 1440, 3440)))

        assert place.where_the_app_comes_up() == loading_screen.AppWindow(kept_on=(2560, 3, 1440, 3440))

    def test_saying_it_again_unchanged_writes_nothing(self, tmp_path):
        said = loading_screen.AppWindow(kept_on=(2560, 3, 1440, 3440))
        place = a_place(tmp_path)
        place.say_where_the_app_comes_up(said)
        os.utime(place.folder / loading_screen.APP_WINDOW, ns=(10**18, 10**18))

        place.say_where_the_app_comes_up(said)

        assert (place.folder / loading_screen.APP_WINDOW).stat().st_mtime_ns == 10**18

    @pytest.mark.parametrize("written", [
        "{", '{"kept_on": null}', '{"size": 7, "kept_on": null}', '{"size": [1954], "kept_on": null}',
        '{"size": null, "kept_on": [2560, 3, 1440]}'])
    def test_what_cannot_be_read_back_is_nothing_said(self, tmp_path, written):
        place = a_place(tmp_path)
        place.folder.mkdir(parents=True)
        (place.folder / loading_screen.APP_WINDOW).write_text(written, encoding="utf-8")

        assert place.where_the_app_comes_up() is None


class TestHandingOverToTheAppsOwn:
    def test_the_app_finds_where_the_launchers_loading_screen_stands_and_how_far_it_got(self, tmp_path):
        place = a_place(tmp_path)

        place.stand(loading_screen.Shown(left=100, top=200, fraction=0.4))

        assert place.standing() == loading_screen.Shown(left=100, top=200, fraction=0.4)

    def test_a_loading_screen_that_stopped_saying_where_it_stands_is_gone(self, tmp_path):
        place = a_place(tmp_path)
        place.stand(loading_screen.Shown(left=100, top=200, fraction=0.4))
        long_ago = time.time() - 10 * loading_screen.STANDING_FOR_S
        os.utime(place.folder / loading_screen.SHOWN, (long_ago, long_ago))

        assert place.standing() is None

    def test_a_loading_screen_that_stepped_aside_has_nothing_to_hand_over(self, tmp_path):
        place = a_place(tmp_path)
        place.stand(loading_screen.Shown(left=100, top=200, fraction=0.4))

        place.step_aside()

        assert place.standing() is None

    def test_the_launchers_loading_screen_learns_when_the_app_has_taken_over(self, tmp_path):
        place = a_place(tmp_path)
        place.stand(loading_screen.Shown(left=100, top=200, fraction=0.0))
        before = place.taken

        place.say_taken()

        assert (before, place.taken) == (False, True)


class Clock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def updating(step: int = 0, *, since: float = 1000.0) -> production_update.UpdateProgress:
    return production_update.UpdateProgress(steps=(("installing its libraries", 30.0), ("moving its code", 2.0)),
                                            step=step, since=since, pid=1, started=1)


class Launch:
    """A launcher's loading screen over two checkouts, the app's and one it hosts,
    with the pictures the app left at its last start."""

    def __init__(self, tmp_path: Path):
        self.place = a_place(tmp_path, "Updating Example...", "Updating Hosted...")
        self.place.leave_pictures(opening=b"opening", full=b"full", updating=[b"example", b"hosted"],
                                  bar=(24, 220, 360, 18), covers_every_monitor=False)
        self.checkouts = (tmp_path / "example", tmp_path / "hosted")
        self.under_way: dict[Path, production_update.UpdateProgress] = {}
        self.clock = Clock()
        self.launcher_running = True
        self.showing = loading_screen.Showing(
            self.place, self.place.pictures(), self.checkouts, progress_of=self.under_way.get, clock=self.clock,
            launcher_running=lambda: self.launcher_running)

    def picture(self) -> bytes:
        return self.showing.tick().picture.read_bytes()


@pytest.fixture
def launch(tmp_path):
    return Launch(tmp_path)


class TestWhatTheLaunchersLoadingScreenShows:
    def test_it_opens_on_the_picture_the_app_opens_on_with_the_bar_empty(self, launch):
        frame = launch.showing.tick()

        assert (frame.picture.read_bytes(), frame.fraction) == (b"opening", 0.0)

    def test_an_update_it_waits_for_shows_that_checkouts_line_and_moves_the_bar(self, launch):
        launch.under_way[launch.checkouts[1]] = updating()
        launch.clock.now += 10
        first = launch.showing.tick()
        launch.clock.now += 10
        later = launch.showing.tick()

        assert first.picture.read_bytes() == b"hosted"
        assert 0.0 < first.fraction < later.fraction < 1.0

    def test_the_bar_stays_where_the_update_left_it_once_it_is_done(self, launch):
        launch.under_way[launch.checkouts[0]] = updating()
        launch.clock.now += 20
        during = launch.showing.tick()
        launch.under_way.clear()
        after = launch.showing.tick()

        assert after.picture.read_bytes() == b"opening"
        assert after.fraction == during.fraction

    def test_a_second_update_carries_the_bar_on_from_where_the_first_left_it(self, launch):
        launch.under_way[launch.checkouts[0]] = updating()
        launch.clock.now += 20
        first = launch.showing.tick()
        launch.under_way.clear()
        launch.under_way[launch.checkouts[1]] = updating(since=launch.clock.now)
        second = launch.showing.tick()
        launch.clock.now += 20
        later = launch.showing.tick()

        assert first.fraction == second.fraction < later.fraction < 1.0

    def test_an_update_whose_line_has_no_picture_yet_moves_the_bar_under_the_opening_one(self, tmp_path):
        place = a_place(tmp_path, "Updating Example...")
        place.leave_pictures(opening=b"opening", full=b"full", updating=[], bar=(0, 0, 1, 1),
                             covers_every_monitor=False)
        under_way = {tmp_path / "example": updating()}
        clock = Clock(1010.0)
        showing = loading_screen.Showing(place, place.pictures(), (tmp_path / "example",),
                                         progress_of=under_way.get, clock=clock, launcher_running=lambda: True)

        frame = showing.tick()

        assert frame.picture.read_bytes() == b"opening"
        assert frame.fraction > 0.0


class TestWhenTheLaunchersLoadingScreenGoes:
    @staticmethod
    def the_launcher_says(launch: Launch, flag: str) -> None:
        (launch.place.folder / flag).touch()
        os.utime(launch.place.folder / flag, (launch.clock.now, launch.clock.now))

    def test_it_stays_while_the_launcher_waits(self, launch):
        assert not launch.showing.over()

    def test_it_goes_once_the_app_has_taken_over(self, launch):
        launch.place.say_taken()

        assert launch.showing.over()

    def test_it_goes_when_the_launcher_ends_without_the_app(self, launch):
        self.the_launcher_says(launch, loading_screen.ENDED)

        assert launch.showing.over()

    def test_it_goes_when_the_launcher_is_gone_before_starting_the_app(self, launch):
        launch.launcher_running = False

        assert launch.showing.over()

    def test_it_waits_for_the_app_the_launcher_started_after_the_launcher_has_gone(self, launch):
        self.the_launcher_says(launch, loading_screen.STARTED)
        launch.launcher_running = False

        assert not launch.showing.over()

    def test_it_goes_when_the_app_the_launcher_started_never_takes_over(self, launch):
        self.the_launcher_says(launch, loading_screen.STARTED)
        launch.clock.now += loading_screen.TAKING_OVER_WITHIN_S + 1

        assert launch.showing.over()

    def test_esc_while_the_launcher_waits_tells_it_to_start_nothing(self, launch):
        assert launch.showing.cancel()
        assert (launch.place.folder / loading_screen.CANCELED).exists()

    def test_esc_once_the_app_is_starting_leaves_it_to_the_apps_own_loading_screen(self, launch):
        self.the_launcher_says(launch, loading_screen.STARTED)

        assert not launch.showing.cancel()
        assert not (launch.place.folder / loading_screen.CANCELED).exists()


class TestWhatTheLaunchersLoadingScreenStandsOver:
    def test_every_window_while_the_launcher_waits(self, launch):
        assert launch.showing.stands_over_every_window

    def test_not_the_apps_own_windows_once_the_launcher_has_started_the_app(self, launch):
        TestWhenTheLaunchersLoadingScreenGoes.the_launcher_says(launch, loading_screen.STARTED)

        assert not launch.showing.stands_over_every_window


class _FakeUser32:
    """user32 as far as measuring the screens reaches into it."""

    def __init__(self):
        self.asked: list[str] = []
        self.metrics = {0: 2560, 1: 1440, 76: -1440, 77: 0, 78: 4000, 79: 3440}
        self.monitors = {7: ((-1440, 0, 0, 3440), (-1440, 0, 0, 3410), 0),
                         1: ((0, 0, 2560, 1440), (0, 0, 2560, 1410), 1)}

    def SetProcessDPIAware(self):  # noqa: N802 - Win32's name
        self.asked.append("pixels")

    def GetSystemMetrics(self, index):  # noqa: N802 - Win32's name
        self.asked.append("metric")
        return self.metrics[index]

    def GetCursorPos(self, point):  # noqa: N802 - Win32's name
        point._obj.x, point._obj.y = -100, 50
        return 1

    def MonitorFromPoint(self, point, flags):  # noqa: N802 - Win32's name
        return 7 if point.x < 0 else 1

    def EnumDisplayMonitors(self, _context, _clip, each, data):  # noqa: N802 - Win32's name
        for monitor in self.monitors:
            each(monitor, None, None, data)
        return 1

    def GetMonitorInfoW(self, monitor, info):  # noqa: N802 - Win32's name
        area, work, flags = self.monitors[monitor]
        for rect, edges in ((info._obj.rcMonitor, area), (info._obj.rcWork, work)):
            rect.left, rect.top, rect.right, rect.bottom = edges
        info._obj.dwFlags = flags
        return 1


class TestMeasuringTheScreens:
    def test_the_whole_desktop_every_monitor_and_the_one_he_clicked_on_are_read(self):
        assert loading_screen.screens(user32=_FakeUser32) == loading_screen.Screens(
            virtual=(-1440, 0, 4000, 3440), primary=(2560, 1440), pointer_work_area=(-1440, 0, 1440, 3410),
            monitors=(loading_screen.Monitor(area=(-1440, 0, 1440, 3440), work_area=(-1440, 0, 1440, 3410),
                                             main=False),
                      loading_screen.Monitor(area=(0, 0, 2560, 1440), work_area=(0, 0, 2560, 1410), main=True)))

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows' own monitors")
    def test_windows_names_every_monitor_with_the_main_one_at_the_corner_of_the_desktop(self):
        measured = loading_screen.screens()

        assert [monitor.area[:2] for monitor in measured.monitors if monitor.main] == [(0, 0)]
        assert measured.pointer_work_area in [monitor.work_area for monitor in measured.monitors]

    def test_it_imports_where_ctypes_has_no_windows_half(self):
        stripped = ("import ctypes, ctypes.wintypes\n"
                    "for name in ('windll', 'oledll', 'WinDLL', 'OleDLL', 'WINFUNCTYPE', 'HRESULT'):\n"
                    "    if hasattr(ctypes, name):\n"
                    "        delattr(ctypes, name)\n"
                    "import app_support.loading_screen\n")
        environment = {**os.environ, "PYTHONPATH": str(Path(loading_screen.__file__).parents[1])}

        imported = subprocess.run([sys._base_executable, "-c", stripped], env=environment, capture_output=True, text=True,
                                  timeout=60)

        assert imported.returncode == 0, imported.stderr

    def test_pixels_are_asked_for_before_anything_is_measured(self):
        # Unaware, Windows answers with scaled numbers, and a cover comes up
        # short of the real desktop on a display that is not at 100%.
        user32 = _FakeUser32()

        loading_screen.screens(user32=lambda: user32)

        assert user32.asked[0] == "pixels"

    def test_screens_that_cannot_be_measured_are_no_answer(self):
        def nothing_to_ask():
            raise AttributeError("no windll")

        assert loading_screen.screens(user32=nothing_to_ask) is None


class TestWhereTheLoadingScreenStands:
    PORTRAIT = loading_screen.Monitor(area=(-1440, 0, 1440, 3440), work_area=(-1440, 0, 1440, 3410), main=False)
    MAIN = loading_screen.Monitor(area=(0, 0, 2560, 1440), work_area=(0, 0, 2560, 1410), main=True)
    SCREENS = loading_screen.Screens(virtual=(-1440, 0, 4000, 3440), primary=(2560, 1440),
                                     pointer_work_area=PORTRAIT.work_area, monitors=(PORTRAIT, MAIN))

    @staticmethod
    def centered_on(monitor: loading_screen.Monitor, size: tuple[int, int] = (408, 271)) -> tuple[int, int]:
        x, y, width, height = monitor.work_area
        return x + (width - size[0]) // 2, y + (height - size[1]) // 2

    def test_one_over_every_monitor_centers_its_panel_on_the_main_monitor(self):
        placement = loading_screen.over_every_monitor((408, 271), self.SCREENS)

        assert placement.window == (-1440, 0, 4000, 3440)
        assert placement.panel_on_screen == (2560 // 2 - 204, 1440 // 2 - 135)

    def test_one_for_an_app_that_said_nothing_comes_up_on_the_monitor_he_clicked_on(self):
        placement = loading_screen.on_the_apps_monitor((408, 271), self.SCREENS, None)

        assert placement.window == (*self.centered_on(self.PORTRAIT), 408, 271)
        assert placement.panel_on_screen == placement.window[:2]

    def test_one_for_an_app_that_keeps_its_window_on_another_monitor_comes_up_there(self):
        app = loading_screen.AppWindow(kept_on=self.MAIN.area)

        placement = loading_screen.on_the_apps_monitor((408, 271), self.SCREENS, app)

        assert placement.panel_on_screen == self.centered_on(self.MAIN)

    def test_one_for_an_app_that_kept_its_window_on_a_monitor_since_unplugged_comes_up_where_he_clicked(self):
        app = loading_screen.AppWindow(kept_on=(4000, 0, 1920, 1080))

        placement = loading_screen.on_the_apps_monitor((408, 271), self.SCREENS, app)

        assert placement.panel_on_screen == self.centered_on(self.PORTRAIT)

    @pytest.mark.parametrize("size", [(1954, 600), (1280, 600), (1000, 3031)])
    def test_one_for_an_app_whose_window_is_too_big_for_the_monitor_he_clicked_on_comes_up_on_the_main_one(
            self, size):
        placement = loading_screen.on_the_apps_monitor((408, 271), self.SCREENS, loading_screen.AppWindow(size=size))

        assert placement.panel_on_screen == self.centered_on(self.MAIN)

    def test_one_for_an_app_whose_window_fits_the_monitor_he_clicked_on_comes_up_there(self):
        app = loading_screen.AppWindow(size=(1279, 3030))

        placement = loading_screen.on_the_apps_monitor((408, 271), self.SCREENS, app)

        assert placement.panel_on_screen == self.centered_on(self.PORTRAIT)

    def test_the_apps_own_panel_taking_over_stays_where_the_launchers_stood(self):
        placement = loading_screen.on_the_apps_monitor(
            (408, 271), self.SCREENS, loading_screen.AppWindow(size=(1954, 600)), panel_at=(-1300, 900))

        assert placement.panel_on_screen == (-1300, 900)

    def test_the_apps_own_panel_leaves_a_launchers_that_stood_off_the_monitor_the_app_keeps_its_window_on(self):
        placement = loading_screen.on_the_apps_monitor(
            (408, 271), self.SCREENS, loading_screen.AppWindow(kept_on=self.MAIN.area), panel_at=(-1300, 900))

        assert placement.panel_on_screen == self.centered_on(self.MAIN)

    def test_the_apps_own_panel_stays_where_the_launchers_stood_on_the_monitor_the_app_keeps_its_window_on(self):
        placement = loading_screen.on_the_apps_monitor(
            (408, 271), self.SCREENS, loading_screen.AppWindow(kept_on=self.MAIN.area), panel_at=(1000, 500))

        assert placement.panel_on_screen == (1000, 500)

    def test_a_panel_handed_over_stays_where_it_stood(self):
        placement = loading_screen.over_every_monitor((408, 271), self.SCREENS, panel_at=(100, 200))

        assert placement.panel_on_screen == (100, 200)
        assert placement.panel == (100 + 1440, 200)


def a_png(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\0" + bytes(color) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


@pytest.mark.skipif(sys.platform != "win32", reason="a window on a desktop of its own")
class TestTheLoadingScreenItself:
    @staticmethod
    def a_place_with_pictures(tmp_path: Path) -> loading_screen.MeetingPlace:
        place = a_place(tmp_path, "Updating Example...")
        place.leave_pictures(opening=a_png(40, 20, (26, 26, 46)), full=a_png(40, 20, (233, 69, 96)),
                             updating=[a_png(40, 20, (26, 26, 46))], bar=(4, 12, 32, 4), covers_every_monitor=False)
        return place

    @staticmethod
    def start(place: loading_screen.MeetingPlace, checkout: Path, desktop) -> int:
        (checkout / ".git").mkdir(parents=True)
        environment = {**os.environ, loading_screen.FOLDER: str(place.folder),
                       loading_screen.LINES: json.dumps(place.lines),
                       "PYTHONPATH": str(Path(loading_screen.__file__).parents[1])}
        return desktop.start([sys.executable, "-m", "app_support.loading_screen", str(checkout)],
                             environment=environment)

    def test_it_comes_up_moves_its_bar_for_an_update_and_goes_once_the_app_takes_over(
            self, tmp_path, desktop_of_its_own):
        place = self.a_place_with_pictures(tmp_path)
        checkout = tmp_path / "example"

        pid = self.start(place, checkout, desktop_of_its_own)
        came_up = eventually(lambda: place.standing() is not None)
        (checkout / ".git" / production_update.PROGRESS).write_text(json.dumps(
            {"steps": [["installing its libraries", 2.0]], "step": 0, "since": time.time(), "pid": os.getpid(),
             "started": win32.process_started(os.getpid())}), encoding="utf-8")
        moved = eventually(lambda: (place.standing() or loading_screen.Shown(0, 0, 0.0)).fraction > 0)
        place.say_taken()

        assert (came_up, moved) == (True, True)
        assert desktop_of_its_own.ended_within(pid, 10)
        assert place.standing() is None

    def test_a_message_the_app_puts_up_before_its_own_loading_screen_comes_up_over_it(
            self, tmp_path, desktop_of_its_own):
        place = self.a_place_with_pictures(tmp_path)

        pid = self.start(place, tmp_path / "example", desktop_of_its_own)
        came_up = eventually(lambda: desktop_of_its_own.shows_a_window_over_every_other() is not None)
        over_every_window_while_waiting = desktop_of_its_own.shows_a_window_over_every_other()
        (place.folder / loading_screen.STARTED).touch()
        made_way = eventually(lambda: desktop_of_its_own.shows_a_window_over_every_other() is False)
        place.say_taken()

        assert (came_up, over_every_window_while_waiting, made_way) == (True, True, True)
        assert desktop_of_its_own.ended_within(pid, 10)

    def test_it_comes_up_on_the_monitor_the_app_keeps_its_window_on(self, tmp_path, desktop_of_its_own):
        place = self.a_place_with_pictures(tmp_path)
        monitors = loading_screen.screens().monitors
        kept = next((monitor for monitor in monitors if not monitor.main), monitors[0])
        place.say_where_the_app_comes_up(loading_screen.AppWindow(kept_on=kept.area))

        pid = self.start(place, tmp_path / "example", desktop_of_its_own)
        came_up = eventually(lambda: place.standing() is not None)
        stood = place.standing()
        place.say_taken()

        x, y, width, height = kept.work_area
        assert came_up
        assert (stood.left, stood.top) == (x + (width - 40) // 2, y + (height - 20) // 2)
        assert desktop_of_its_own.ended_within(pid, 10)


class TestEachLaunchStartsAfresh:
    def test_the_launcher_clears_everything_the_last_launch_said_but_the_pictures(self):
        assert set(loading_screen.SAID_AT_EACH_LAUNCH) == {
            loading_screen.SHOWN, loading_screen.TAKEN, loading_screen.STARTED, loading_screen.ENDED,
            loading_screen.CANCELED, loading_screen.UPDATED}
