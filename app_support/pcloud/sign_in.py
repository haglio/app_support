from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from app_support.pcloud.api import PCloudRefused

SHORTEST_RECOVERY_CODE = 16
# pCloud's answers, as Warm Gun's sign-in learned them: 1022 wants an emailed code, 2012, 2074 and
# 2092 refuse a code, 2064 ends a second-factor challenge, and 2360 sends the email all the same.
_CODE_WANTED = 1022
_BAD_CODES = frozenset({2012, 2074, 2092})
_CHALLENGE_EXPIRED = 2064
_EMAIL_SENT_ANYWAY = 2360


@dataclass(frozen=True)
class WithPassword:
    pass


@dataclass(frozen=True)
class WithEmailedCode:
    code: str


@dataclass(frozen=True)
class WithSecondFactor:
    token: str
    code: str
    recovery: bool


@dataclass(frozen=True)
class Say:
    words: str


@dataclass(frozen=True)
class EmailACode:
    pass


@dataclass(frozen=True)
class SignedIn:
    auth: str


class SignInSteps:
    def __init__(self) -> None:
        self.wants_code = False
        self.challenge_token: str | None = None
        self.can_send_code_to_other_apps = False

    def attempt(self, code: str) -> WithPassword | WithEmailedCode | WithSecondFactor:
        code = code.strip()
        if not code:
            return WithPassword()
        if self.challenge_token is not None:
            return WithSecondFactor(self.challenge_token, code, recovery=len(code) >= SHORTEST_RECOVERY_CODE)
        return WithEmailedCode(code)

    def refused(self, refusal: PCloudRefused, attempt) -> Say | EmailACode:
        if refusal.token is not None:
            self.challenge_token, self.can_send_code_to_other_apps, self.wants_code = (
                refusal.token, bool(refusal.has_devices), True)
            return Say("pCloud wants a second factor. Enter a code from your authenticator app, or use a send button below.")
        if refusal.code == _CODE_WANTED and attempt == WithPassword():
            self.wants_code = True
            return EmailACode()
        if refusal.code == _CODE_WANTED or refusal.code in _BAD_CODES:
            self.wants_code = True
            return Say("pCloud refused that verification code. To have it email a new one, empty the code box and log in again.")
        if refusal.code == _CHALLENGE_EXPIRED:
            self.challenge_token, self.wants_code = None, False
            return Say("That code session expired — log in with the password again.")
        return Say(str(refusal))


def stops_the_sign_in(code_check: PCloudRefused) -> bool:
    return code_check.code in _BAD_CODES


def sent_the_email_despite(answer: PCloudRefused) -> bool:
    return answer.code == _EMAIL_SENT_ANYWAY


def sign_in(pcloud, steps: SignInSteps, email: str, password: str, code: str) -> SignedIn | Say:
    attempt = steps.attempt(code)
    try:
        if isinstance(attempt, WithSecondFactor):
            return SignedIn(pcloud.tfa_login(attempt.token, attempt.code, recovery=attempt.recovery))
        if isinstance(attempt, WithEmailedCode):
            _check_the_code(pcloud, email, attempt.code)
            return SignedIn(pcloud.login(email, password, code=attempt.code))
        return SignedIn(pcloud.login(email, password))
    except PCloudRefused as refusal:
        said = steps.refused(refusal, attempt)
    return _emailed_a_code(pcloud, email) if isinstance(said, EmailACode) else said


def _check_the_code(pcloud, email: str, code: str) -> None:
    try:
        pcloud.check_emailed_login_code(email, code)
    except PCloudRefused as check:
        if stops_the_sign_in(check):
            raise


def _emailed_a_code(pcloud, email: str) -> Say:
    emailed = Say(f"pCloud emailed a verification code to {email}. Enter it below.")
    try:
        pcloud.email_login_code(email)
    except PCloudRefused as answer:
        return emailed if sent_the_email_despite(answer) else Say(str(answer))
    return emailed


def save_login(login_file: Path, *, api_host: str, auth: str) -> None:
    login_file.parent.mkdir(parents=True, exist_ok=True)
    partial = login_file.with_name(login_file.name + ".partial")
    partial.write_text(json.dumps({"api_host": api_host, "auth": auth}), encoding="utf-8")
    os.replace(partial, login_file)
