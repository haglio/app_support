import sys

import pytest

from app_support import claude_sessions
from app_support.claude_sessions import CommandFailed, NewSession

CWD = "C:/made/up/place"
SESSION = NewSession("title", "brief", CWD)


class FakeClaude:
    def __init__(self, **answers):
        self.asked = []
        self.answers = answers

    def __call__(self, command, cwd=None):
        self.asked.append((list(command), cwd))
        answer = self.answers.get(command[1], "")
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_a_session_starts_in_the_background_in_auto_under_its_title_and_its_short_id_comes_back():
    claude = FakeClaude(**{"--bg": "backgrounded \xb7 812181fb \xb7 A made-up title"})

    short_id = claude_sessions.start_in_background("claude", NewSession("A made-up title", "the brief", CWD), shell=claude)

    assert short_id == "812181fb"
    assert claude.asked == [(["claude", "auth", "status"], None),
                            (["claude", "--bg", "--name", "A made-up title", "--permission-mode", "auto", "the brief"],
                             CWD)]


def test_no_session_starts_while_the_command_line_is_not_signed_in():
    claude = FakeClaude(auth=CommandFailed("no"))

    with pytest.raises(CommandFailed, match="not signed in"):
        claude_sessions.start_in_background("claude", SESSION, shell=claude)

    assert [command for command, _cwd in claude.asked if "--bg" in command] == []


def test_what_a_session_needs_made_first_is_made_only_once_the_command_line_is_signed_in():
    made = []
    claude = FakeClaude(**{"--bg": "backgrounded · 812181fb"})

    claude_sessions.start_in_background("claude", SESSION, shell=claude,
                                        once_signed_in=lambda: made.append(len(claude.asked)))
    with pytest.raises(CommandFailed):
        claude_sessions.start_in_background("claude", SESSION, shell=FakeClaude(auth=CommandFailed("no")),
                                            once_signed_in=lambda: made.append("too soon"))

    assert made == [1]


def test_a_start_the_command_line_does_not_confirm_is_a_failure():
    claude = FakeClaude(**{"--bg": "something else entirely"})

    with pytest.raises(CommandFailed, match="something else entirely"):
        claude_sessions.start_in_background("claude", SESSION, shell=claude)


def test_background_sessions_are_read_off_the_command_line():
    claude = FakeClaude(agents='[{"id": "812181fb", "state": "done"}]')

    assert claude_sessions.background_sessions("claude", shell=claude) == [{"id": "812181fb", "state": "done"}]
    assert claude.asked == [(["claude", "agents", "--json", "--all"], None)]


def test_an_answer_that_is_no_list_of_sessions_is_a_failure():
    with pytest.raises(CommandFailed, match="did not answer"):
        claude_sessions.background_sessions("claude", shell=FakeClaude(agents="not json"))


def test_a_session_opens_in_claude_desktop_by_being_stopped_then_resumed_there():
    ran = []

    claude_sessions.open_in_claude_desktop("claude", "812181fb", "the-whole-id", CWD,
                                           run=lambda command, **kwargs: ran.append((command, kwargs["cwd"])))

    assert ran == [(["claude", "stop", "812181fb"], CWD), (["claude", "--desktop", "--resume", "the-whole-id"], CWD)]


def test_opening_in_claude_desktop_leaves_the_command_line_s_output_alone():
    asked = []

    claude_sessions.open_in_claude_desktop("claude", "812181fb", "the-whole-id", CWD,
                                           run=lambda command, **kwargs: asked.append(kwargs))

    assert "capture_output" not in asked[1]
    assert "stdout" not in asked[1]


def test_the_newest_copy_the_claude_app_keeps_is_the_command_line_used(tmp_path):
    kept = tmp_path / "Packages" / "Claude_x" / "LocalCache" / "Roaming" / "Claude" / "claude-code"
    for version in ("2.1.9", "2.1.293"):
        (kept / version / "abc").mkdir(parents=True)
        (kept / version / "abc" / "claude.exe").touch()

    assert claude_sessions.claude_command(str(tmp_path)) == str(kept / "2.1.293" / "abc" / "claude.exe")


def test_with_no_copy_kept_by_the_app_the_one_on_the_path_is_used(tmp_path):
    assert claude_sessions.claude_command(str(tmp_path), which=lambda _name: "C:/made/up/claude.exe") == (
        "C:/made/up/claude.exe")


def test_a_command_that_fails_says_what_it_printed(tmp_path):
    with pytest.raises(CommandFailed, match="boom"):
        claude_sessions.run_command([sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
                                    cwd=tmp_path)


def test_a_command_that_cannot_start_is_a_failure():
    with pytest.raises(CommandFailed, match="could not start"):
        claude_sessions.run_command(["a-program-nothing-installed"])


def test_a_command_s_output_comes_back(tmp_path):
    assert claude_sessions.run_command([sys.executable, "-c", "print('hi')"], cwd=tmp_path).strip() == "hi"
