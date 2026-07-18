from __future__ import annotations

from app_support.cli import preparse_config_path


class TestPreparseConfigPath:
    def test_returns_none_without_config_arg(self):
        assert preparse_config_path([]) is None

    def test_extracts_config_arg_without_consuming_others(self):
        assert preparse_config_path(["--foo", "bar", "--config", "demo.json"]) == "demo.json"

    def test_unknown_flags_do_not_abort_the_preparse(self):
        # The real parser has not been built yet, so every other flag is unknown
        # here by definition; erroring on them would make this useless.
        assert preparse_config_path(["--width", "800", "--config", "c.json"]) == "c.json"
