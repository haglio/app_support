"""Each production checkout kept at what has shipped, never while something of his runs from it."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from production_machine import Machine, a_process, git, pins, spec

from app_support import launcher, processes, production_update, windows_settings
from app_support.production_update import Outcome

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Win32's file sharing and processes")
GENERIC_READ = 0x80000000
SHARED_FOR_READING_AND_WRITING = 0x3
OPEN_ALWAYS = 4


@pytest.fixture
def machine(tmp_path):
    return Machine(tmp_path)


class TestBringingOneCheckoutUp:
    def test_a_checkout_behind_origin_is_moved_up_to_it(self, machine):
        checkout = machine.checkout()
        before = machine.head(checkout)
        target = machine.ship(checkout, {"feature.txt": "new\n"})

        outcome = machine.bring_up(checkout)

        assert machine.head(checkout) == target
        assert outcome.said == f"moved from {before[:8]} to {target[:8]}"
        assert [step for step in machine.ran if step[0] == "pip"] == []

    def test_a_shipped_change_that_moves_a_pin_installs_the_library_before_the_code(self, machine):
        # Moved first, the new code meets the old libraries until the install ends, and
        # an app started in between dies at startup (Genau, 2026-10-07).
        checkout = machine.checkout(files={"pyproject.toml": pins(app_support="0.1.375")})
        machine.install(checkout, "app_support", "0.1.375")
        machine.ship(checkout, {"pyproject.toml": pins(app_support="0.1.376")})

        machine.bring_up(checkout)

        assert machine.ran == [
            ("pip", "install", spec("app_support", "0.1.376")),
            ("merge",),
            ("pip", "install", "-e", str(checkout), "--config-settings", "editable_mode=compat"),
        ]
        assert machine.head(checkout) == machine.origin_head(checkout)

    def test_a_checkout_moved_without_its_libraries_gets_them(self, machine):
        checkout = machine.checkout(files={"pyproject.toml": pins(shared_ui="0.1.200")})
        machine.install(checkout, "shared_ui", "0.1.199")

        outcome = machine.bring_up(checkout)

        assert machine.ran == [
            ("pip", "install", spec("shared_ui", "0.1.200")),
            ("pip", "install", "-e", str(checkout), "--config-settings", "editable_mode=compat"),
        ]
        assert "shared-ui v0.1.200" in outcome.said

    def test_a_library_newer_than_its_pin_is_put_back_to_the_pin_that_shipped(self, machine):
        # A taken-back change once left its newer funestra under older code that the
        # newer copy no longer answered, and production Fun Time would not start.
        checkout = machine.checkout(files={"pyproject.toml": pins(funestra="0.1.498")})
        machine.install(checkout, "funestra", "0.1.507")

        outcome = machine.bring_up(checkout)

        assert machine.ran == [
            ("pip", "install", spec("funestra", "0.1.498")),
            ("pip", "install", "-e", str(checkout), "--config-settings", "editable_mode=compat"),
        ]
        assert "funestra v0.1.498" in outcome.said

    def test_a_shipped_change_to_what_the_checkout_installs_reinstalls_it(self, machine):
        checkout = machine.checkout()
        machine.ship(checkout, {"pyproject.toml": pins() + '\n[project.scripts]\nexample = "example:main"\n'})

        machine.bring_up(checkout)

        assert machine.ran == [
            ("merge",),
            ("pip", "install", "-e", str(checkout), "--config-settings", "editable_mode=compat"),
        ]

    def test_a_checkout_with_no_venv_is_only_moved(self, machine):
        checkout = machine.checkout(venv=False)
        machine.ship(checkout, {"pyproject.toml": pins(app_support="0.1.376")})

        machine.bring_up(checkout)

        assert machine.ran == [("merge",)]

    def test_nothing_changes_while_something_of_his_runs_out_of_its_venv(self, machine):
        checkout = machine.checkout(files={"pyproject.toml": pins(app_support="0.1.375")})
        machine.install(checkout, "app_support", "0.1.375")
        machine.ship(checkout, {"pyproject.toml": pins(app_support="0.1.376")})
        before = machine.head(checkout)
        asked = []

        outcome = machine.bring_up(checkout, in_use=lambda venvs: asked.append(venvs) or [
            a_process("Example-Example.exe")])

        assert machine.ran == []
        assert machine.head(checkout) == before
        assert outcome.said == "waiting for Example-Example.exe to close"
        assert [checkout / ".venv"] == asked[0]

    def test_an_update_waiting_for_his_programs_leaves_word_in_the_checkout(self, machine):
        checkout = machine.checkout()
        machine.ship(checkout, {"feature.txt": "new\n"})

        machine.bring_up(checkout, in_use=lambda venvs: [a_process("Example-Example.exe")])

        assert production_update.waits_for_programs_to_close(checkout)

    def test_the_word_goes_once_the_update_is_made(self, machine):
        checkout = machine.checkout()
        machine.ship(checkout, {"feature.txt": "new\n"})
        machine.bring_up(checkout, in_use=lambda venvs: [a_process("Example-Example.exe")])

        machine.bring_up(checkout)

        assert machine.head(checkout) == machine.origin_head(checkout)
        assert not production_update.waits_for_programs_to_close(checkout)

    def test_the_word_goes_once_there_is_nothing_left_to_update(self, machine):
        checkout = machine.checkout()
        machine.ship(checkout, {"feature.txt": "new\n"})
        machine.bring_up(checkout, in_use=lambda venvs: [a_process("Example-Example.exe")])
        git("merge", "-q", "--ff-only", "origin/main", cwd=checkout)

        outcome = machine.bring_up(checkout, in_use=lambda venvs: [a_process("Example-Example.exe")])

        assert outcome.said.startswith("up to date")
        assert not production_update.waits_for_programs_to_close(checkout)

    def test_a_checkout_another_app_runs_programs_out_of_waits_for_that_app_too(self, machine):
        hosted = machine.checkout("hosted")
        host = machine.checkout("host", files={
            "pyproject.toml": pins() + '\n[tool.haglio.production]\nalso-runs = ["hosted"]\n'})
        machine.ship(hosted, {"feature.txt": "new\n"})
        asked = []

        machine.bring_up(hosted, in_use=lambda venvs: asked.append(venvs) or [])

        assert asked == [[hosted / ".venv", host / ".venv"]]

    def test_a_checkout_with_changes_nobody_committed_is_left_where_it_is(self, machine):
        checkout = machine.checkout()
        machine.ship(checkout, {"feature.txt": "new\n"})
        (checkout / "pyproject.toml").write_text(pins() + "# an edit\n", encoding="utf-8")
        before = machine.head(checkout)

        outcome = machine.bring_up(checkout)

        assert machine.head(checkout) == before
        assert outcome.said == "has uncommitted changes; left where it is"

    def test_a_checkout_off_its_branch_is_left_where_it_is(self, machine):
        checkout = machine.checkout()
        machine.ship(checkout, {"feature.txt": "new\n"})
        git("checkout", "-q", "--detach", cwd=checkout)

        outcome = machine.bring_up(checkout)

        assert outcome.said == "is on no branch, not main; left where it is"
        assert machine.ran == []

    def test_a_checkout_that_went_its_own_way_is_left_where_it_is(self, machine):
        checkout = machine.checkout()
        machine.ship(checkout, {"feature.txt": "new\n"})
        (checkout / "local.txt").write_text("local\n", encoding="utf-8")
        git("add", "-A", cwd=checkout)
        git("commit", "-q", "-m", "local only", cwd=checkout)
        before = machine.head(checkout)

        outcome = machine.bring_up(checkout)

        assert machine.head(checkout) == before
        assert outcome.said.startswith("has commits origin/main does not")

    def test_a_failed_install_leaves_the_code_where_it_was_and_says_so(self, machine):
        checkout = machine.checkout(files={"pyproject.toml": pins(app_support="0.1.375")})
        machine.install(checkout, "app_support", "0.1.375")
        target = machine.ship(checkout, {"pyproject.toml": pins(app_support="0.1.376")})
        before = machine.head(checkout)

        def no_network(arguments, **kwargs):
            if "pip" in arguments:
                raise production_update.StepFailed("pip install said: could not reach github.com")
            return machine.run(arguments, **kwargs)

        outcome = production_update.bring_up(checkout, workspace=machine.workspace, run=no_network,
                                             in_use=lambda venvs: [], wait_s=5.0)

        assert machine.head(checkout) == before
        assert outcome.failed
        assert outcome.target == target
        assert "could not reach github.com" in outcome.said

    def test_a_target_that_failed_a_moment_ago_is_not_tried_again_yet(self, machine):
        checkout = machine.checkout()
        target = machine.ship(checkout, {"feature.txt": "new\n"})
        failed = Outcome("failed: pip install said: no", at=1000.0, failed=True, target=target)

        outcome = machine.bring_up(checkout, previous=failed,
                                   now=lambda: 1000.0 + production_update.RETRY_FAILED_AFTER_S - 1)

        assert outcome == failed
        assert machine.ran == []

    def test_code_that_ran_ahead_of_its_libraries_gets_them_even_right_after_a_failure(self, machine):
        # Production Origenerator's code was moved past its libraries by another hand, and its
        # launch, ten minutes after a failed install, left them missing and the app dead (2026-10-17).
        checkout = machine.checkout(files={"pyproject.toml": pins(app_support="0.1.376")})
        machine.install(checkout, "app_support", "0.1.375")
        failed = Outcome("failed: pip install said: no", at=1000.0, failed=True, target=machine.head(checkout))

        machine.bring_up(checkout, previous=failed, now=lambda: 1001.0)

        assert ("pip", "install", spec("app_support", "0.1.376")) in machine.ran

    def test_a_target_that_failed_long_enough_ago_is_tried_again(self, machine):
        checkout = machine.checkout()
        target = machine.ship(checkout, {"feature.txt": "new\n"})
        failed = Outcome("failed: pip install said: no", at=1000.0, failed=True, target=target)

        machine.bring_up(checkout, previous=failed,
                         now=lambda: 1000.0 + production_update.RETRY_FAILED_AFTER_S + 1)

        assert machine.head(checkout) == target


class TestSayingHowFarAnUpdateHasGot:
    @staticmethod
    def watched(machine, checkout, seen):
        def run(arguments, **kwargs):
            if "pip" in arguments or arguments[1:2] == ["merge"]:
                seen.append(production_update.progress_of(checkout))
            return machine.run(arguments, **kwargs)
        return run

    def test_each_step_of_an_update_is_written_in_the_checkout_while_it_runs(self, machine):
        checkout = machine.checkout(files={"pyproject.toml": pins(app_support="0.1.375")})
        machine.install(checkout, "app_support", "0.1.375")
        machine.ship(checkout, {"pyproject.toml": pins(app_support="0.1.376")})
        seen = []

        production_update.bring_up(checkout, workspace=machine.workspace, run=self.watched(machine, checkout, seen),
                                   in_use=lambda venvs: [], wait_s=5.0)

        assert [progress.step for progress in seen] == [0, 1, 2]
        assert {len(progress.steps) for progress in seen} == {3}
        assert production_update.progress_of(checkout) is None

    @staticmethod
    def under_way(step: int, since: float = 1000.0) -> production_update.UpdateProgress:
        return production_update.UpdateProgress(steps=(("installing its libraries", 10.0), ("moving its code", 30.0)),
                                                step=step, since=since, pid=1, started=1)

    def test_an_update_has_got_as_far_as_the_steps_it_has_finished(self):
        assert self.under_way(0).fraction(now=1000.0) == 0.0
        assert self.under_way(1).fraction(now=1000.0) == 0.25

    def test_the_step_under_way_moves_on_with_time_and_never_past_its_end(self):
        progress = self.under_way(0)
        moments = [progress.fraction(now=1000.0 + seconds) for seconds in (1, 5, 10, 100, 10_000)]

        assert moments == sorted(set(moments))
        assert moments[-1] <= 0.25

    @windows_only
    def test_word_left_by_an_update_that_ended_mid_way_is_no_update(self, tmp_path):
        ended = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True,
                               text=True, check=True)
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / production_update.PROGRESS).write_text(json.dumps(
            {"steps": [["moving its code", 2.0]], "step": 0, "since": time.time(),
             "pid": int(ended.stdout), "started": 1}), encoding="utf-8")

        assert production_update.progress_of(tmp_path) is None


class TestACheckoutThatMovesOnlyToWhatPassed:
    DECLARED = pins() + '\n[tool.haglio.production]\ncommit-file = "state/passed.txt"\n'

    def test_it_moves_to_the_commit_its_file_names_and_not_past_it(self, machine):
        checkout = machine.checkout(files={"pyproject.toml": self.DECLARED})
        passed = machine.ship(checkout, {"one.txt": "1\n"})
        machine.ship(checkout, {"two.txt": "2\n"})
        (checkout / "state").mkdir()
        (checkout / "state" / "passed.txt").write_text(passed + "\n", encoding="utf-8")
        git("fetch", "-q", "origin", cwd=checkout)

        machine.bring_up(checkout)

        assert machine.head(checkout) == passed

    def test_it_stays_where_it_is_until_the_file_names_a_commit(self, machine):
        checkout = machine.checkout(files={"pyproject.toml": self.DECLARED})
        before = machine.head(checkout)
        machine.ship(checkout, {"one.txt": "1\n"})

        outcome = machine.bring_up(checkout)

        assert machine.head(checkout) == before
        assert outcome.said == "nothing has passed yet: state/passed.txt names no commit"

    def test_a_checkout_left_where_it_is_waits_for_no_program(self, machine):
        checkout = machine.checkout(files={"pyproject.toml": self.DECLARED})
        passed = machine.ship(checkout, {"one.txt": "1\n"})
        (checkout / "state").mkdir()
        (checkout / "state" / "passed.txt").write_text(passed + "\n", encoding="utf-8")
        machine.bring_up(checkout, in_use=lambda venvs: [a_process("Example-Example.exe")])
        (checkout / "state" / "passed.txt").write_text("", encoding="utf-8")

        machine.bring_up(checkout, in_use=lambda venvs: [a_process("Example-Example.exe")])

        assert not production_update.waits_for_programs_to_close(checkout)

    def test_a_commit_file_that_has_shipped_holds_a_checkout_that_does_not_declare_it_yet(self, machine):
        checkout = machine.checkout()
        before = machine.head(checkout)
        machine.ship(checkout, {"pyproject.toml": self.DECLARED})

        outcome = machine.bring_up(checkout)

        assert machine.head(checkout) == before
        assert outcome.said == "nothing has passed yet: state/passed.txt names no commit"

    def test_it_never_moves_back_to_an_older_passed_commit(self, machine):
        checkout = machine.checkout(files={"pyproject.toml": self.DECLARED})
        older = machine.head(checkout)
        machine.ship(checkout, {"one.txt": "1\n"})
        git("merge", "-q", "--ff-only", "origin/main", cwd=checkout)
        (checkout / "state").mkdir()
        (checkout / "state" / "passed.txt").write_text(older, encoding="utf-8")

        outcome = machine.bring_up(checkout)

        assert machine.head(checkout) == machine.origin_head(checkout)
        assert outcome.said.startswith("up to date")


class TestAHotfix:
    def test_a_checkout_moves_to_the_hotfix_asked_for(self, machine):
        checkout = machine.checkout()
        hotfix = machine.hotfix(checkout, {"fix.txt": "fixed\n"})

        machine.bring_up(checkout)

        assert machine.head(checkout) == hotfix

    def test_a_hotfix_the_checkout_runs_is_asked_for_no_longer(self, machine):
        checkout = machine.checkout()
        machine.hotfix(checkout, {"fix.txt": "fixed\n"})
        machine.bring_up(checkout)

        machine.bring_up(checkout)

        assert machine.hotfix_asked_for(checkout) is None

    def test_a_hotfix_made_on_a_commit_the_checkout_has_moved_past_is_left_out(self, machine):
        checkout = machine.checkout()
        machine.hotfix(checkout, {"fix.txt": "fixed\n"})
        shipped = machine.ship(checkout, {"feature.txt": "new\n"})
        git("merge", "-q", "--ff-only", shipped, cwd=checkout)

        outcome = machine.bring_up(checkout)

        assert machine.head(checkout) == shipped
        assert machine.hotfix_asked_for(checkout) is None
        assert outcome.said.startswith("up to date")

    def test_a_checkout_runs_its_hotfix_until_the_same_fix_ships_the_usual_way(self, machine):
        checkout = machine.checkout()
        hotfix = machine.hotfix(checkout, {"fix.txt": "fixed\n"})
        machine.bring_up(checkout)
        machine.ship(checkout, {"feature.txt": "new\n"})

        outcome = machine.bring_up(checkout)

        assert machine.head(checkout) == hotfix
        assert outcome.said == 'kept at its hotfix "the hotfix" until that fix ships the usual way'
        assert not outcome.failed

    def test_a_checkout_leaves_its_hotfix_for_what_shipped_once_that_fix_has_shipped(self, machine):
        checkout = machine.checkout()
        hotfix = machine.hotfix(checkout, {"fix.txt": "fixed\n"},
                                stands_for=(("someone@example.com", 1_700_000_100),))
        machine.bring_up(checkout)
        shipped = machine.ship(checkout, {"fix.txt": "fixed\n"}, authored=1_700_000_100)

        outcome = machine.bring_up(checkout)

        assert machine.head(checkout) == shipped
        assert outcome.said == f"moved from {hotfix[:8]} to {shipped[:8]}"

    def test_a_fix_taken_back_out_after_it_shipped_leaves_the_checkout_on_its_hotfix(self, machine):
        checkout = machine.checkout()
        hotfix = machine.hotfix(checkout, {"fix.txt": "fixed\n"},
                                stands_for=(("someone@example.com", 1_700_000_100),))
        machine.bring_up(checkout)
        shipped = machine.ship(checkout, {"fix.txt": "fixed\n"}, authored=1_700_000_100)
        machine.take_back(checkout, shipped)

        machine.bring_up(checkout)

        assert machine.head(checkout) == hotfix

    def test_a_fix_taken_back_out_and_shipped_again_lets_the_checkout_leave_its_hotfix(self, machine):
        checkout = machine.checkout()
        machine.hotfix(checkout, {"fix.txt": "fixed\n"}, stands_for=(("someone@example.com", 1_700_000_100),))
        machine.bring_up(checkout)
        shipped = machine.ship(checkout, {"fix.txt": "fixed\n"}, authored=1_700_000_100)
        again = machine.take_back(checkout, machine.take_back(checkout, shipped))

        machine.bring_up(checkout)

        assert machine.head(checkout) == again

    def test_a_hotfix_still_unshipped_a_day_after_it_was_made_is_a_failure(self, machine):
        checkout = machine.checkout()
        hotfix = machine.hotfix(checkout, {"fix.txt": "fixed\n"})
        machine.bring_up(checkout)
        made = int(git("log", "-1", "--format=%ct", hotfix, cwd=checkout))

        outcome = machine.bring_up(checkout, now=lambda: made + production_update.HOTFIX_SHIPS_WITHIN_S + 1)

        assert machine.head(checkout) == hotfix
        assert outcome.failed
        assert outcome.said == 'failed: kept at its hotfix "the hotfix" for a day, and that fix has not shipped the usual way'

    def test_a_checkout_that_moves_only_to_what_passed_leaves_its_hotfix_once_what_passed_has_the_fix(self, machine):
        checkout = machine.checkout(files={"pyproject.toml": TestACheckoutThatMovesOnlyToWhatPassed.DECLARED})
        (checkout / "state").mkdir()
        (checkout / "state" / "passed.txt").write_text(machine.head(checkout), encoding="utf-8")
        hotfix = machine.hotfix(checkout, {"fix.txt": "fixed\n"}, stands_for=(("someone@example.com", 1_700_000_100),))
        machine.bring_up(checkout)
        machine.ship(checkout, {"fix.txt": "fixed\n"}, authored=1_700_000_100)
        untested = machine.ship(checkout, {"feature.txt": "new\n"})

        machine.bring_up(checkout)
        stayed = machine.head(checkout)
        (checkout / "state" / "passed.txt").write_text(untested, encoding="utf-8")
        machine.bring_up(checkout)

        assert stayed == hotfix
        assert machine.head(checkout) == untested


class TestWhereACheckoutIsHeaded:
    def test_a_checkout_behind_what_shipped_is_headed_for_it(self, machine):
        checkout = machine.checkout()
        shipped = machine.ship(checkout, {"feature.txt": "new\n"})

        assert production_update.heading_for(checkout, run=machine.run) == shipped

    def test_a_checkout_kept_at_its_hotfix_is_headed_nowhere_else(self, machine):
        checkout = machine.checkout()
        hotfix = machine.hotfix(checkout, {"fix.txt": "fixed\n"})
        machine.bring_up(checkout)
        machine.ship(checkout, {"feature.txt": "new\n"})

        assert production_update.heading_for(checkout, run=machine.run) == hotfix

    def test_a_checkout_asked_for_a_hotfix_is_headed_for_it(self, machine):
        checkout = machine.checkout()
        hotfix = machine.hotfix(checkout, {"fix.txt": "fixed\n"})

        assert production_update.heading_for(checkout, run=machine.run) == hotfix


class TestTheDeclaration:
    def test_a_checkout_that_declares_nothing_says_nothing(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(pins(), encoding="utf-8")

        assert production_update.declared(tmp_path) is None

    def test_an_empty_table_follows_origin_and_runs_nothing_else(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(pins() + "\n[tool.haglio.production]\n", encoding="utf-8")

        assert production_update.declared(tmp_path) == production_update.Declaration()

    def test_a_misspelled_key_is_refused_rather_than_ignored(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            pins() + '\n[tool.haglio.production]\nalso-run = ["hosted"]\n', encoding="utf-8")

        with pytest.raises(production_update.ProductionSpecError, match="also-run"):
            production_update.declared(tmp_path)

    @pytest.mark.parametrize("named", ["C:/elsewhere/passed.txt", "../passed.txt", ""])
    def test_a_commit_file_outside_the_checkout_is_refused(self, tmp_path, named):
        (tmp_path / "pyproject.toml").write_text(
            pins() + f'\n[tool.haglio.production]\ncommit-file = "{named}"\n', encoding="utf-8")

        with pytest.raises(production_update.ProductionSpecError, match="commit-file"):
            production_update.declared(tmp_path)

    @pytest.mark.parametrize("named", ['"hosted"', '["../hosted"]', '[""]'])
    def test_what_it_also_runs_has_to_be_checkouts_beside_it(self, tmp_path, named):
        (tmp_path / "pyproject.toml").write_text(
            pins() + f"\n[tool.haglio.production]\nalso-runs = {named}\n", encoding="utf-8")

        with pytest.raises(production_update.ProductionSpecError, match="also-runs"):
            production_update.declared(tmp_path)

    def test_a_folder_with_no_pyproject_declares_nothing(self, tmp_path):
        assert production_update.declared(tmp_path) is None


class TestTheLibraries:
    def test_a_library_missing_older_or_newer_than_its_pin_is_off_it(self, tmp_path):
        venv = tmp_path / ".venv"
        (venv / "Lib" / "site-packages" / "shared_ui-0.1.199.dist-info").mkdir(parents=True)
        (venv / "Lib" / "site-packages" / "app_support-0.1.210.dist-info").mkdir()
        (venv / "Lib" / "site-packages" / "funestra-0.1.509.dist-info").mkdir()

        off = production_update.libraries_off_their_pins(
            pins(shared_ui="0.1.200", app_support="0.1.201", voice_core="0.1.45", funestra="0.1.509"),
            production_update.installed_versions(venv))

        assert [pin.spec for pin in off] == [spec("shared_ui", "0.1.200"), spec("app_support", "0.1.201"),
                                             spec("voice_core", "0.1.45")]

    def test_a_venv_that_is_not_there_holds_nothing(self, tmp_path):
        assert production_update.installed_versions(tmp_path / ".venv") == {}

    def test_a_library_whose_checkout_here_holds_its_pinned_tag_is_installed_from_that_checkout(self, machine):
        # GitHub dropped every clone for an hour on 2026-10-17 while each library's checkout beside
        # production Origenerator already held the tag its code pinned.
        library = machine.checkout("example_library", venv=False)
        git("tag", "v0.1.376", cwd=library)
        checkout = machine.checkout(files={"pyproject.toml": pins(example_library="0.1.376")})
        installs = []

        def run(arguments, *, env=None, **kwargs):
            if "pip" in arguments:
                installs.append(env or {})
            return machine.run(arguments, **kwargs)

        production_update.bring_up(checkout, workspace=machine.workspace, run=run, in_use=lambda venvs: [],
                                   wait_s=5.0)

        clone = machine.base / "cloned"
        subprocess.run(["git", "clone", "-q", "https://github.com/haglio/example_library", str(clone)],
                       env={**os.environ, **installs[0], "GIT_TERMINAL_PROMPT": "0"}, check=True)
        assert git("rev-parse", "v0.1.376^{commit}", cwd=clone) == git("rev-parse", "HEAD", cwd=library)


@windows_only
class TestTheTurn:
    def test_a_session_that_finds_another_mid_update_waits_and_then_finds_it_done(self, machine):
        checkout = machine.checkout()
        machine.ship(checkout, {"feature.txt": "new\n"})
        holding = threading.Event()

        def the_other_update():
            with production_update.the_turn(checkout, wait_s=5):
                holding.set()
                time.sleep(0.5)
                git("merge", "-q", "--ff-only", "origin/main", cwd=checkout)

        other = threading.Thread(target=the_other_update)
        other.start()
        holding.wait(5)

        outcome = machine.bring_up(checkout)
        other.join()

        assert outcome.said.startswith("up to date")
        assert machine.ran == []

    def test_a_turn_left_by_a_process_that_died_mid_update_is_taken_over(self, machine):
        checkout = machine.checkout()
        machine.ship(checkout, {"feature.txt": "new\n"})
        takes_the_turn_and_dies = (
            "import os, sys; from pathlib import Path; from app_support import production_update; "
            "production_update.the_turn(Path(sys.argv[1]), wait_s=5).__enter__(); os._exit(0)")
        subprocess.run([sys.executable, "-c", takes_the_turn_and_dies, str(checkout)], check=True,
                       env={**os.environ, "PYTHONPATH": str(Path(production_update.__file__).parents[1])})

        machine.bring_up(checkout, wait_s=1)

        assert machine.head(checkout) == machine.origin_head(checkout)

    def test_a_turn_held_past_the_wait_is_reported_and_never_broken(self, machine):
        checkout = machine.checkout()
        machine.ship(checkout, {"feature.txt": "new\n"})
        before = machine.head(checkout)

        with production_update.the_turn(checkout, wait_s=5):
            outcome = machine.bring_up(checkout, wait_s=0.3)

        assert machine.head(checkout) == before
        assert outcome.said.startswith("busy:")

    def test_a_launch_in_progress_keeps_an_update_out_until_it_lets_go(self, machine, held_open):
        checkout = machine.checkout()
        machine.ship(checkout, {"feature.txt": "new\n"})
        gate = checkout / ".git" / production_update.TURN

        with held_open(gate, access=GENERIC_READ, share=SHARED_FOR_READING_AND_WRITING,
                       disposition=OPEN_ALWAYS) as let_go:
            held = machine.bring_up(checkout, wait_s=0.3)
            let_go()
            free = machine.bring_up(checkout, wait_s=0.3)

        assert held.said.startswith("busy:")
        assert "moved" in free.said


class TestKeepingTheWorkspaceUp:
    def test_every_checkout_is_fetched_brought_up_and_said_once(self, machine):
        app = machine.checkout("app")
        library = machine.checkout("library", venv=False)
        state = machine.base / "state"
        for checkout in (app, library):
            clone = machine.base / f"pusher-{checkout.name}"
            git("clone", "-q", str(machine.base / "origins" / f"{checkout.name}.git"), str(clone), cwd=machine.base)
            machine._identify(clone)
            (clone / "new.txt").write_text("new\n", encoding="utf-8")
            git("add", "-A", cwd=clone)
            git("commit", "-q", "-m", "shipped", cwd=clone)
            git("push", "-q", "origin", "main", cwd=clone)

        outcomes = production_update.keep_up(machine.workspace, state, run=machine.run,
                                             in_use=lambda venvs: [], now=lambda: 5000.0)

        assert sorted(outcomes) == ["app", "library"]
        assert all("moved" in outcome.said for outcome in outcomes.values())
        status = json.loads((state / production_update.STATUS_NAME).read_text(encoding="utf-8"))
        assert status["pass_finished"] == 5000.0
        assert status["checkouts"]["app"]["said"] == outcomes["app"].said

    def test_a_pass_asks_github_once_and_fetches_only_the_checkout_whose_main_moved(self, machine):
        moved = machine.checkout("moved")
        machine.checkout("still")
        machine.ship(moved, {"new.txt": "new\n"}, fetched=False)

        production_update.keep_up(machine.workspace, machine.base / "state", run=machine.run,
                                  in_use=lambda venvs: [])

        assert [step for step in machine.ran if step[0] in ("github", "fetch")] == [("github",), ("fetch", "moved")]
        assert machine.head(moved) == machine.origin_head(moved)

    @pytest.mark.parametrize("unanswered", ["GitHub is out of reach", "its origin is not on GitHub"])
    def test_a_checkout_github_does_not_answer_for_is_fetched_once_its_last_fetch_is_old(self, machine, unanswered):
        app = machine.checkout("app")
        if unanswered == "GitHub is out of reach":
            machine.github_down = True
        else:
            git("remote", "set-url", "origin", str(machine.base / "origins" / "app.git"), cwd=app)
        git("fetch", "-q", "origin", cwd=app)
        fetched_at = (app / ".git" / "FETCH_HEAD").stat().st_mtime
        machine.ship(app, {"new.txt": "new\n"}, fetched=False)
        state = machine.base / "state"

        for seconds_later in (60, production_update.FETCH_UNASKED_AFTER_S):
            production_update.keep_up(machine.workspace, state, run=machine.run, in_use=lambda venvs: [],
                                      now=lambda seconds_later=seconds_later: fetched_at + seconds_later)

        assert [step for step in machine.ran if step[0] == "fetch"] == [("fetch", "app")]
        assert machine.head(app) == machine.origin_head(app)

    def test_github_going_out_of_reach_and_coming_back_is_each_said_once(self, machine, caplog):
        machine.checkout("app")

        with caplog.at_level("INFO", logger="production_update"):
            for down in (False, True, True, False, False):
                machine.github_down = down
                production_update.keep_up(machine.workspace, machine.base / "state", run=machine.run,
                                          in_use=lambda venvs: [])

        out_of_reach = ("GitHub: could not be asked what has shipped, so each checkout is fetched every 30 minutes "
                        "instead: gh api said: could not reach api.github.com")
        back = "GitHub: answers what has shipped again, so only a checkout whose main moved is fetched"
        assert [record.getMessage() for record in caplog.records if "GitHub" in record.getMessage()] == [
            out_of_reach, back]

    def test_a_pass_leaves_each_checkout_a_rule_that_keeps_the_claude_app_from_moving_its_main(self, machine):
        # Starting a session in a project, the Claude app fast-forwards the project's checked-out
        # main itself, libraries skipped, unless its preflight finds a rule in info/attributes:
        # production Origenerator met its new code without them and would not start (2026-10-17).
        app = machine.checkout("app")
        what_git_said_of_a_file = git("check-attr", "-a", "pyproject.toml", cwd=app)

        production_update.keep_up(machine.workspace, machine.base / "state", run=machine.run,
                                  in_use=lambda venvs: [])

        lines = (app / ".git" / "info" / "attributes").read_text(encoding="utf-8").splitlines()
        assert [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
        assert git("check-attr", "-a", "pyproject.toml", cwd=app) == what_git_said_of_a_file

    def test_that_rule_is_written_once_beside_whatever_the_file_already_held(self, machine):
        app = machine.checkout("app")
        attributes = app / ".git" / "info" / "attributes"
        attributes.write_text("*.example binary", encoding="utf-8")

        for _ in range(2):
            production_update.keep_up(machine.workspace, machine.base / "state", run=machine.run,
                                      in_use=lambda venvs: [])

        lines = attributes.read_text(encoding="utf-8").splitlines()
        assert lines.count(production_update.HANDS_OFF_RULE) == 1
        assert "*.example binary" in lines

    def test_a_checkout_whose_rule_cannot_be_written_is_said_and_the_pass_goes_on(self, machine, caplog):
        stuck = machine.checkout("stuck")
        (stuck / ".git" / "info" / "attributes").mkdir()
        other = machine.checkout("other")
        machine.ship(other, {"feature.txt": "new\n"})

        with caplog.at_level("WARNING", logger="production_update"):
            outcomes = production_update.keep_up(machine.workspace, machine.base / "state", run=machine.run,
                                                 in_use=lambda venvs: [])

        assert sorted(outcomes) == ["other", "stuck"]
        assert machine.head(other) == machine.origin_head(other)
        assert [record.getMessage() for record in caplog.records
                if record.getMessage().startswith("stuck: could not keep the Claude app off")]

    def test_a_folder_that_is_not_a_checkout_is_passed_over(self, machine):
        (machine.workspace / "notes").mkdir()
        machine.checkout("app")

        outcomes = production_update.keep_up(machine.workspace, machine.base / "state", run=machine.run,
                                             in_use=lambda venvs: [])

        assert list(outcomes) == ["app"]

    def test_a_wait_already_said_is_not_said_again(self, machine, caplog):
        app = machine.checkout("app")
        machine.ship(app, {"feature.txt": "new\n"})
        state = machine.base / "state"
        busy = [a_process("App-App.exe")]

        with caplog.at_level("INFO", logger="production_update"):
            for _ in range(2):
                production_update.keep_up(machine.workspace, state, run=machine.run, fetch=False,
                                          in_use=lambda venvs: busy)

        assert [record.getMessage() for record in caplog.records] == [
            "app: waiting for App-App.exe to close"]

    def test_before_a_launch_the_checkout_and_what_it_runs_are_brought_up_without_a_fetch(self, machine):
        hosted = machine.checkout("hosted")
        host = machine.checkout("host", files={
            "pyproject.toml": pins() + '\n[tool.haglio.production]\nalso-runs = ["hosted"]\n'})
        for checkout in (host, hosted):
            machine.ship(checkout, {"feature.txt": "new\n"})
        state = machine.base / "state"

        outcomes = production_update.before_launch(host, machine.workspace, state, run=machine.run,
                                                   in_use=lambda venvs: [])

        assert sorted(outcomes) == ["host", "hosted"]
        assert machine.head(host) == machine.origin_head(host)
        assert machine.head(hosted) == machine.origin_head(hosted)
        assert not [step for step in machine.ran if step[0] in ("fetch", "github")]


class TestFindingWhatRunsFromAVenv:
    @pytest.fixture
    def started(self):
        children = []

        def start(*arguments: str, env: dict[str, str] | None = None) -> subprocess.Popen:
            child = subprocess.Popen([sys._base_executable, "-c", "import time; time.sleep(120)", *arguments],
                                     env=env)
            children.append(child)
            return child

        yield start
        for child in children:
            child.kill()
            child.wait()

    @staticmethod
    def _found(venvs, *, whose=lambda process, among: processes.HIS) -> set[int]:
        deadline = time.monotonic() + 10
        while True:
            found = {process.pid for process in production_update.running_from(venvs, whose=whose)}
            if found or time.monotonic() > deadline:
                return found
            time.sleep(0.05)

    def test_a_program_naming_a_file_in_the_venv_runs_from_it(self, started, tmp_path):
        venv = tmp_path / "app" / ".venv"
        child = started(str(venv / "Scripts" / "python.exe"))

        assert child.pid in self._found([venv])

    def test_a_venv_whose_name_starts_the_same_is_another_venv(self, started, tmp_path):
        started(str(tmp_path / "app" / ".venv2" / "Scripts" / "python.exe"))
        started(str(tmp_path / "app-two" / ".venv" / "Scripts" / "python.exe"))

        assert production_update.running_from([tmp_path / "app" / ".venv"],
                                              whose=lambda process, among: processes.HIS) == []

    def test_the_machines_upkeep_never_holds_an_update_back(self, started, tmp_path):
        venv = tmp_path / "app" / ".venv"
        upkeep = started(str(venv / "Scripts" / "python.exe"),
                         env={**os.environ, production_update.UPKEEP_MARK: "1"})
        time.sleep(0.5)

        assert upkeep.pid not in {process.pid for process in production_update.running_from(
            [venv], whose=lambda process, among: processes.HIS)}

    def test_an_agents_program_never_holds_an_update_back(self, started, tmp_path):
        venv = tmp_path / "app" / ".venv"
        agents = started(str(venv / "Scripts" / "python.exe"), env={**os.environ, processes.SESSION_MARK: "1"})
        time.sleep(0.5)

        assert agents.pid not in {process.pid for process in production_update.running_from([venv])}


class TestAFailedStep:
    def test_says_the_line_that_names_why_beside_the_last_one(self):
        # pip ends a failed clone with three lines of its own; the record of 2026-10-17's
        # failures kept only those, and the dropped connection that caused them went unsaid.
        printed = ("Cloning https://github.com/haglio/example_library\n"
                   "  error: RPC failed; curl 56 Recv failure: Connection was reset\n"
                   "  fatal: early EOF\n"
                   "  error: subprocess-exited-with-error\n"
                   "  note: This error originates from a subprocess, and is likely not a problem with pip.\n"
                   "ERROR: Failed to build 'example-library' when git clone\n")

        with pytest.raises(production_update.StepFailed) as failed:
            production_update.run([sys.executable, "-c", f"import sys; sys.stderr.write({printed!r}); sys.exit(1)"])

        assert "error: RPC failed; curl 56 Recv failure: Connection was reset" in str(failed.value)
        assert "Failed to build 'example-library'" in str(failed.value)


class TestTheCommandLine:
    def test_a_pass_brings_every_checkout_up_and_writes_down_what_it_did(self, machine):
        app = machine.checkout("app")
        machine.ship(app, {"feature.txt": "new\n"})
        state = machine.base / "state"

        code = production_update.main(["--workspace", str(machine.workspace), "--state", str(state)],
                                      run=machine.run, in_use=lambda venvs: [])

        assert code == 0
        assert machine.head(app) == machine.origin_head(app)
        assert "app: moved" in (state / production_update.LOG_NAME).read_text(encoding="utf-8")

    @windows_only
    def test_a_pass_already_under_way_is_left_to_finish_alone(self, machine, held_open):
        app = machine.checkout("app")
        machine.ship(app, {"feature.txt": "new\n"})
        state = machine.base / "state"
        state.mkdir()

        with held_open(state / production_update.ONE_PASS, access=0xC0000000, share=0,
                       disposition=OPEN_ALWAYS):
            code = production_update.main(["--workspace", str(machine.workspace), "--state", str(state)],
                                          run=machine.run, in_use=lambda venvs: [])

        assert code == 0
        assert machine.ran == []
        assert machine.head(app) != machine.origin_head(app)

    @pytest.mark.parametrize("which", ["keep_up", "before_launch"], ids=["a pass", "an update before a launch"])
    def test_an_update_that_ends_on_an_error_says_what_it_was_in_its_log(self, machine, monkeypatch, which):
        def ends_on_an_error(*args, **kwargs):
            raise ValueError("the record of the last pass could not be read")

        monkeypatch.setattr(production_update, which, ends_on_an_error)
        state = machine.base / "state"
        asked = (["--before-launch", str(machine.checkout("app"))] if which == "before_launch"
                 else ["--workspace", str(machine.workspace)])

        code = production_update.main([*asked, "--state", str(state)], run=machine.run, in_use=lambda venvs: [])

        assert code == 1
        logged = (state / production_update.LOG_NAME).read_text(encoding="utf-8")
        assert "ValueError: the record of the last pass could not be read" in logged

    def test_before_a_launch_only_that_checkout_is_brought_up(self, machine):
        app = machine.checkout("app")
        other = machine.checkout("other")
        for checkout in (app, other):
            machine.ship(checkout, {"feature.txt": "new\n"})

        code = production_update.main(["--before-launch", str(app), "--state", str(machine.base / "state")],
                                      run=machine.run, in_use=lambda venvs: [])

        assert code == 0
        assert machine.head(app) == machine.origin_head(app)
        assert machine.head(other) != machine.origin_head(other)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class TestAnAppThatIsNeverClosed:
    @pytest.fixture
    def checkout(self, tmp_path):
        (tmp_path / ".git").mkdir()
        return tmp_path

    @pytest.fixture
    def clock(self):
        return Clock()

    @staticmethod
    def an_update_waits(checkout):
        (checkout / ".git" / production_update.WAITING).write_text(
            "waiting for App-App.exe to close\n", encoding="utf-8")

    @staticmethod
    def watching(checkout, clock, *, a_good_moment=True):
        started = []
        watch = production_update.UpdateWatch(
            checkout, a_good_moment=lambda: a_good_moment, start_again=lambda: started.append(True),
            logger=logging.getLogger("test.update_watch"), clock=clock)
        return watch, started

    def test_it_starts_again_for_a_waiting_update_at_a_good_moment(self, checkout, clock):
        watch, started = self.watching(checkout, clock)
        self.an_update_waits(checkout)
        clock.now += production_update.UP_BEFORE_AN_UPDATE_S

        watch.tick()

        assert started == [True]

    def test_a_waiting_update_waits_on_for_a_good_moment(self, checkout, clock):
        watch, started = self.watching(checkout, clock, a_good_moment=False)
        self.an_update_waits(checkout)
        clock.now += production_update.UP_BEFORE_AN_UPDATE_S

        watch.tick()

        assert started == []

    def test_an_app_no_update_waits_for_goes_on_as_it_is(self, checkout, clock):
        watch, started = self.watching(checkout, clock)
        clock.now += production_update.UP_BEFORE_AN_UPDATE_S

        watch.tick()

        assert started == []

    def test_an_app_just_started_stays_up_a_while_before_it_starts_again(self, checkout, clock):
        """A launch that could not make the update -- something else of his still
        ran from the venv -- leaves it waiting, so the new copy would start again at once."""
        watch, started = self.watching(checkout, clock)
        self.an_update_waits(checkout)
        clock.now += production_update.UP_BEFORE_AN_UPDATE_S - 1

        watch.tick()

        assert started == []

    def test_the_log_says_why_the_app_started_again(self, checkout, clock, caplog):
        watch, _started = self.watching(checkout, clock)
        self.an_update_waits(checkout)
        clock.now += production_update.UP_BEFORE_AN_UPDATE_S

        with caplog.at_level("INFO", logger="test.update_watch"):
            watch.tick()

        assert [record.getMessage() for record in caplog.records] == [
            f"An update of {checkout} is waiting for this app to close; starting it again to take the update"]


class TestStartingAnAppAgainThroughItsLauncher:
    @windows_only
    def test_the_launcher_runs_once_the_copy_it_waited_for_has_ended(self, tmp_path):
        ran = tmp_path / "launcher.ran"
        launcher = tmp_path / "launch_example.vbs"
        launcher.write_text(
            'CreateObject("Scripting.FileSystemObject").CreateTextFile("' + str(ran) + '", True).Close\n',
            encoding="ascii")
        ending = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])

        production_update.start_again_after(ending.pid, launcher)
        time.sleep(1)
        started_too_early = ran.exists()
        ending.wait()
        deadline = time.monotonic() + 30
        while not ran.exists() and time.monotonic() < deadline:
            time.sleep(0.1)

        assert not started_too_early
        assert ran.exists()

    def test_the_wait_runs_on_the_plain_interpreter_never_out_of_the_apps_venv(self, tmp_path):
        started = []

        production_update.start_again_after(1234, tmp_path / "launch_example.vbs",
                                            popen=lambda command, **kwargs: started.append(command))

        assert Path(started[0][0]) == Path(sys._base_executable).with_name("pythonw.exe")
        assert started[0][-2:] == ["1234", str(tmp_path / "launch_example.vbs")]


class TestThisCheckoutRunsTheUpdater:
    CHECKOUT = Path(__file__).resolve().parents[1]

    def test_its_launcher_is_what_its_spec_renders(self):
        launcher.assert_launchers_match_their_specs(self.CHECKOUT)

    def test_a_scheduled_task_starts_a_pass_marked_as_upkeep(self):
        (task,) = windows_settings.declared(self.CHECKOUT).scheduled_tasks
        (started,) = [found for found in launcher.launchers(self.CHECKOUT) if found.file == task.launcher]

        assert started.run == f"-m {production_update.__name__}"
        assert (production_update.UPKEEP_MARK, "1") in started.environment

    def test_every_launcher_finds_the_updater_where_this_checkouts_launcher_runs_it(self):
        (started,) = launcher.launchers(self.CHECKOUT)

        assert started.venv == "own"
        assert Path("app_support", ".venv", "Scripts", started.interpreter) == Path(production_update.UPDATER)
