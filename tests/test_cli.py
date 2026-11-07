from __future__ import annotations

from app_support.cli import preparse_config_path


class TestPreparseConfigPath:
    def test_a_command_line_with_no_config_flag_names_no_config(self):
        assert preparse_config_path([]) is None

    def test_reads_the_config_flag_first_since_the_config_decides_the_real_parsers_defaults(self):
        assert preparse_config_path(["--foo", "bar", "--config", "demo.json"]) == "demo.json"

    def test_unknown_flags_do_not_abort_the_preparse_since_the_real_parser_does_not_exist_yet(self):
        assert preparse_config_path(["--width", "800", "--config", "c.json"]) == "c.json"
