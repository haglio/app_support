from __future__ import annotations

import argparse


def preparse_config_path(argv: list[str] | None) -> str | None:
    a_throwaway_parser_the_config_decides_the_real_ones_defaults = argparse.ArgumentParser(add_help=False)
    a_throwaway_parser_the_config_decides_the_real_ones_defaults.add_argument("--config")
    known, _flags_only_the_real_parser_will_know = \
        a_throwaway_parser_the_config_decides_the_real_ones_defaults.parse_known_args(argv)
    return known.config
