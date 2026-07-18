"""Command-line odds and ends every app in this family needs.

Each app takes a ``--config`` path, and each has to read it *before* building its
real parser: the config decides defaults the parser then declares. A second
throwaway parser is the cheap way to look at one flag without committing to the
whole argument set, and without an unknown flag aborting the run.
"""
from __future__ import annotations

import argparse


def preparse_config_path(argv: list[str] | None) -> str | None:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--config")
    known, _ = ap.parse_known_args(argv)
    return known.config
