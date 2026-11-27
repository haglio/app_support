from __future__ import annotations

import json

from app_support.pcloud.api import PCloudRefused
from app_support.pcloud.sign_in import (
    EmailACode,
    Say,
    SignedIn,
    SignInSteps,
    WithEmailedCode,
    WithPassword,
    WithSecondFactor,
    save_login,
    sent_the_email_despite,
    sign_in,
    stops_the_sign_in,
)


def _refused(code: int, *, token: str | None = None, has_devices: bool | None = None) -> PCloudRefused:
    return PCloudRefused("login", code, "made-up refusal", token=token, has_devices=has_devices)


def test_the_password_signs_in_until_a_challenge_hands_the_code_a_token_to_go_with():
    steps = SignInSteps()
    first = steps.attempt("")

    said = steps.refused(_refused(2297, token="made-up-challenge", has_devices=True), first)

    assert (first, said, steps.attempt(" 123456 "), steps.attempt("a" * 16), steps.can_send_code_to_other_apps) == (
        WithPassword(),
        Say("pCloud wants a second factor. Enter a code from your authenticator app, or use a send button below."),
        WithSecondFactor(token="made-up-challenge", code="123456", recovery=False),
        WithSecondFactor(token="made-up-challenge", code="a" * 16, recovery=True),
        True,
    )


def test_a_password_asked_for_a_code_has_pcloud_email_one_and_the_box_waits_for_it():
    steps = SignInSteps()

    assert (steps.refused(_refused(1022), WithPassword()), steps.wants_code, steps.attempt("654321")) == (
        EmailACode(), True, WithEmailedCode("654321"))


def test_a_code_still_asked_for_is_one_pcloud_refused_and_an_empty_box_emails_a_fresh_one():
    steps = SignInSteps()

    assert [steps.refused(_refused(code), WithEmailedCode("654321")) for code in (1022, 2012, 2074, 2092)] == [
        Say("pCloud refused that verification code. To have it email a new one, empty the code box and log in again.")
    ] * 4


def test_only_a_bad_code_from_the_code_check_stops_the_sign_in():
    assert [stops_the_sign_in(_refused(code)) for code in (2012, 2074, 2092, 1022, 2000)] == [
        True, True, True, False, False]


def test_pclouds_email_request_can_answer_2360_and_still_have_sent_the_email():
    assert [sent_the_email_despite(_refused(code)) for code in (2360, 2000)] == [True, False]


def test_an_expired_challenge_starts_over_and_any_other_refusal_is_said_as_pcloud_said_it():
    steps = SignInSteps()
    steps.refused(_refused(2297, token="made-up-challenge"), WithPassword())

    expired = steps.refused(_refused(2064), WithSecondFactor("made-up-challenge", "123456", recovery=False))

    assert (expired, steps.attempt("123456"), steps.refused(_refused(2000), WithPassword())) == (
        Say("That code session expired — log in with the password again."),
        WithEmailedCode("123456"),
        Say("pCloud refused login: made-up refusal (2000)"),
    )


class _PCloud:
    def __init__(self, *refusals: PCloudRefused | None) -> None:
        self.asked: list[tuple] = []
        self._refusals = list(refusals)

    def _answer(self, *asked):
        self.asked.append(asked)
        refusal = self._refusals.pop(0) if self._refusals else None
        if refusal is not None:
            raise refusal
        return "made-up-login"

    def login(self, username, password, code=None):
        return self._answer("login", username, password, code)

    def tfa_login(self, token, code, *, recovery):
        return self._answer("tfa_login", token, code, recovery)

    def email_login_code(self, email):
        self._answer("email a code", email)

    def check_emailed_login_code(self, email, code):
        self._answer("check the code", email, code)


_EMAIL, _PASSWORD = "jane@example.test", "made up secret"


def test_a_password_pcloud_takes_signs_in_with_the_login_it_hands_back():
    pcloud = _PCloud()

    assert (sign_in(pcloud, SignInSteps(), _EMAIL, _PASSWORD, ""), pcloud.asked) == (
        SignedIn("made-up-login"), [("login", _EMAIL, _PASSWORD, None)])


def test_a_password_pcloud_wants_a_code_for_has_one_emailed_and_says_where_even_when_pcloud_answers_2360():
    for answer in (None, _refused(2360)):
        pcloud = _PCloud(_refused(1022), answer)

        assert (sign_in(pcloud, SignInSteps(), _EMAIL, _PASSWORD, ""), pcloud.asked[-1]) == (
            Say("pCloud emailed a verification code to jane@example.test. Enter it below."), ("email a code", _EMAIL))


def test_an_emailed_code_is_checked_and_then_signs_in_with_the_password_and_unless_the_check_calls_it_bad():
    taken, refused = _PCloud(), _PCloud(_refused(2074))

    assert [sign_in(taken, SignInSteps(), _EMAIL, _PASSWORD, "654321"), taken.asked,
            sign_in(refused, SignInSteps(), _EMAIL, _PASSWORD, "654321"), refused.asked] == [
        SignedIn("made-up-login"), [("check the code", _EMAIL, "654321"), ("login", _EMAIL, _PASSWORD, "654321")],
        Say("pCloud refused that verification code. To have it email a new one, empty the code box and log in again."),
        [("check the code", _EMAIL, "654321")]]


def test_a_code_given_after_a_second_factor_challenge_signs_in_with_the_challenges_token():
    steps, pcloud = SignInSteps(), _PCloud(_refused(2297, token="made-up-challenge"))
    sign_in(pcloud, steps, _EMAIL, _PASSWORD, "")

    assert (sign_in(pcloud, steps, _EMAIL, _PASSWORD, "123456"), pcloud.asked[-1]) == (
        SignedIn("made-up-login"), ("tfa_login", "made-up-challenge", "123456", False))


def test_a_login_is_kept_where_every_app_on_the_computer_reads_it(tmp_path):
    login_file = tmp_path / ".haglio" / "pcloud_login.json"

    save_login(login_file, api_host="api.example.test", auth="made-up-login")

    assert json.loads(login_file.read_text(encoding="utf-8")) == {"api_host": "api.example.test", "auth": "made-up-login"}


def test_an_email_pcloud_will_not_send_says_pclouds_own_reason():
    pcloud = _PCloud(_refused(1022), _refused(2000))

    assert sign_in(pcloud, SignInSteps(), _EMAIL, _PASSWORD, "") == Say("pCloud refused login: made-up refusal (2000)")
