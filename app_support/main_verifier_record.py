from __future__ import annotations

import contextlib
import json
from collections.abc import Sequence
from pathlib import Path

INCIDENTS_NAME = "main_verifier_incidents.jsonl"


def read_incidents(state: Path) -> list[dict]:
    try:
        lines = (state / INCIDENTS_NAME).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    incidents = []
    for line in lines:
        with contextlib.suppress(ValueError):
            incidents.append(json.loads(line))
    return incidents


def shipped_again(incidents: Sequence[dict]) -> set[int]:
    return {incident.get("pull_request") for incident in incidents if incident.get("shipped_again_by")}
