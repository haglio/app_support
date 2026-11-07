from __future__ import annotations

import argparse


def preparse_config_path(argv: list[str] | None) -> str | None:
    config_only = argparse.ArgumentParser(add_help=False)
    config_only.add_argument("--config")
    known, _ = config_only.parse_known_args(argv)
    return known.config
