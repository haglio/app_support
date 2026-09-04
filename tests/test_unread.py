"""The scans of what is written and never read, `app_support.unread`: the blind
spots vulture has, ported from the genau and fun_time gates that found them."""
from __future__ import annotations

from pathlib import Path

import pytest

from app_support import unread


def _tree(tmp_path, files: dict[str, str]) -> Path:
    for name, source in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return tmp_path


def test_a_module_constant_nothing_reads_is_reported(tmp_path):
    root = _tree(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "READ = 1\nUNREAD = 2\n_ALSO_UNREAD: int = 3\n",
        "pkg/b.py": "from pkg.a import READ\n\nprint(READ)\n",
    })
    assert unread.module_constants(root, [root / "pkg"]) == [
        "pkg/a.py:2: UNREAD", "pkg/a.py:3: _ALSO_UNREAD"]
    with pytest.raises(AssertionError, match="UNREAD"):
        unread.assert_no_module_constant_goes_unread(root, [root / "pkg"])


def test_a_constructor_parameter_stored_and_never_read_is_reported(tmp_path):
    root = _tree(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": (
            "class Thing:\n"
            "    def __init__(self, used, stored, read_outside):\n"
            "        self.used = used\n"
            "        self.stored = stored\n"
            "        self.read_outside = read_outside\n"
            "\n"
            "    def go(self):\n"
            "        return self.used\n"
        ),
        "pkg/b.py": "def peek(thing):\n    return thing.read_outside\n",
    })
    assert unread.stored_parameters(root, [root / "pkg"]) == ["pkg/a.py:4: Thing.stored"]
    with pytest.raises(AssertionError, match=r"Thing\.stored"):
        unread.assert_no_constructor_parameter_is_stored_and_never_read(root, [root / "pkg"])


def test_a_test_helper_nothing_calls_is_reported(tmp_path):
    root = _tree(tmp_path, {
        "tests/__init__.py": "",
        "tests/test_a.py": (
            "import pytest\n\n\n"
            "def _called():\n    return 1\n\n\n"
            "def _never_called():\n    return 2\n\n\n"
            "def _imported_elsewhere():\n    return 3\n\n\n"
            "@pytest.fixture\n"
            "def a_fixture():\n    return 4\n\n\n"
            "def pytest_configure(config):\n    pass\n\n\n"
            "def test_it():\n    assert _called() == 1\n"
        ),
        "tests/test_b.py": "from tests.test_a import _imported_elsewhere\n\n\ndef test_b():\n    assert _imported_elsewhere() == 3\n",
    })
    assert unread.test_helpers(root, root / "tests") == ["tests/test_a.py:8: _never_called"]
    with pytest.raises(AssertionError, match="_never_called"):
        unread.assert_no_test_helper_is_written_and_never_called(root, root / "tests")


def test_an_argparse_option_nothing_reads_is_reported(tmp_path):
    root = _tree(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/cli.py": (
            "import argparse\n\n\n"
            "def parse():\n"
            "    p = argparse.ArgumentParser()\n"
            "    p.add_argument('--read-me')\n"
            "    p.add_argument('--never-read')\n"
            "    p.add_argument('-x', dest='explicit')\n"
            "    p.add_argument('--read-by-getattr', type=float, default=1.0)\n"
            "    return p.parse_args()\n"
        ),
        "pkg/app.py": (
            "def run(args):\n"
            "    return args.read_me, args.explicit, getattr(args, 'read_by_getattr', 1.0)\n"
        ),
    })
    assert unread.argparse_options(root, [root / "pkg"]) == ["pkg/cli.py:7: never_read"]
    with pytest.raises(AssertionError, match="never_read"):
        unread.assert_every_argparse_option_is_read(root, [root / "pkg"])


def test_a_dataclass_field_nothing_reads_is_reported(tmp_path):
    root = _tree(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/records.py": (
            "from dataclasses import dataclass\n\n\n"
            "@dataclass\n"
            "class Record:\n"
            "    read: int\n"
            "    read_by_getattr: int\n"
            "    unread: int = 0\n"
        ),
        "pkg/use.py": "def go(r):\n    return r.read, getattr(r, 'read_by_getattr', 0)\n",
    })
    assert unread.dataclass_fields(root, [root / "pkg"]) == ["pkg/records.py:8: Record.unread"]
    with pytest.raises(AssertionError, match=r"Record\.unread"):
        unread.assert_no_dataclass_field_goes_unread(root, [root / "pkg"])


def test_a_name_the_repo_allows_is_left_out_of_the_report(tmp_path):
    """A field read only by `dataclasses.asdict`, a constant read by a sibling
    repo: the repo names them, with the reason beside each, and the scan holds
    everything else."""
    root = _tree(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "SERIALIZED = 1\nUNREAD = 2\n",
    })
    unread.assert_no_module_constant_goes_unread(root, [root / "pkg"], allowing=("SERIALIZED", "UNREAD"))
    with pytest.raises(AssertionError, match="UNREAD"):
        unread.assert_no_module_constant_goes_unread(root, [root / "pkg"], allowing=("SERIALIZED",))
