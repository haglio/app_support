"""A run of pytest the way a repo of the family starts one, with this checkout's app_support."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_SUPPORT = Path(__file__).resolve().parents[1]


def run_pytest_in(started_in: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", *args], cwd=started_in,
                          env={**os.environ, "PYTHONPATH": str(APP_SUPPORT)},
                          capture_output=True, text=True)
