"""Command-line odds and ends more than one app in this family needs.

An app that takes a ``--config`` path has to read it *before* building its
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
