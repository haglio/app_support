from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from app_support import import_sweep

PYPROJECT = """\
[project]
name = "toy-app"
version = "0.1.0"

[tool.setuptools.packages.find]
include = ["toy_app*"]
"""


def a_checkout(root: Path, modules: dict[str, str], pyproject: str = PYPROJECT) -> Path:
    (root / "pyproject.toml").parent.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    for name, source in modules.items():
        path = root.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return root


def test_every_module_of_the_declared_packages_is_imported(tmp_path):
    checkout = a_checkout(tmp_path / "toy_app_checkout", {
        "toy_app/__init__.py": "",
        "toy_app/alpha.py": "ALPHA = 1\n",
        "toy_app/inner/__init__.py": "",
        "toy_app/inner/beta.py": "from toy_app.alpha import ALPHA\n",
    })

    swept = import_sweep.sweep(checkout, python=sys.executable)

    assert swept.imported == ["toy_app", "toy_app.alpha", "toy_app.inner", "toy_app.inner.beta"]
    assert swept.failures == {}


def test_a_module_that_raises_as_it_imports_is_named_with_what_it_raised(tmp_path):
    checkout = a_checkout(tmp_path / "toy_app_checkout", {
        "toy_app/__init__.py": "",
        "toy_app/buttons.py": 'HOLDS = {"held": 1, "free": 2}\n',
        "toy_app/dispatch.py": 'from toy_app.buttons import HOLDS\nRETRACT = HOLDS["retracted"]\n',
    })

    swept = import_sweep.sweep(checkout, python=sys.executable)

    assert swept.imported == ["toy_app", "toy_app.buttons"]
    assert list(swept.failures) == ["toy_app.dispatch"]
    assert "KeyError: 'retracted'" in swept.failures["toy_app.dispatch"]


def test_a_package_s_main_module_is_left_alone_since_importing_it_runs_the_app(tmp_path):
    checkout = a_checkout(tmp_path / "toy_app_checkout", {
        "toy_app/__init__.py": "",
        "toy_app/__main__.py": 'raise SystemExit("the app ran")\n',
    })

    swept = import_sweep.sweep(checkout, python=sys.executable)

    assert (swept.imported, swept.failures) == (["toy_app"], {})


def test_only_the_packages_the_pyproject_ships_are_swept(tmp_path):
    checkout = a_checkout(tmp_path / "toy_app_checkout", {
        "toy_app/__init__.py": "",
        "toy_app_vr/__init__.py": "",
        "tests/__init__.py": "",
        "tests/test_toy.py": 'raise AssertionError("a test module was imported")\n',
        "tools/__init__.py": 'raise AssertionError("a tool was imported")\n',
    }, pyproject=PYPROJECT.replace('["toy_app*"]', '["toy_app", "toy_app_vr*"]'))

    swept = import_sweep.sweep(checkout, python=sys.executable)

    assert (swept.imported, swept.failures) == (["toy_app", "toy_app_vr"], {})


@pytest.mark.parametrize("pyproject", [
    '[project]\nname = "toy-app"\n',
    PYPROJECT.replace('["toy_app*"]', '["toy_game*"]'),
], ids=["no packages declared", "no package matches"])
def test_a_checkout_with_nothing_to_import_is_refused_rather_than_passed(tmp_path, pyproject):
    checkout = a_checkout(tmp_path / "toy_app_checkout", {"toy_app/__init__.py": ""}, pyproject=pyproject)

    with pytest.raises(import_sweep.NothingToSweep, match="toy_app_checkout"):
        import_sweep.sweep(checkout, python=sys.executable)


def test_a_module_that_ends_the_interpreter_is_named_and_the_modules_after_it_are_still_imported(tmp_path):
    checkout = a_checkout(tmp_path / "toy_app_checkout", {
        "toy_app/__init__.py": "",
        "toy_app/alpha.py": "",
        "toy_app/crash.py": "import os\nos._exit(3)\n",
        "toy_app/omega.py": "",
    })

    swept = import_sweep.sweep(checkout, python=sys.executable)

    assert swept.imported == ["toy_app", "toy_app.alpha", "toy_app.omega"]
    assert list(swept.failures) == ["toy_app.crash"]
    assert "exit code 3" in swept.failures["toy_app.crash"]


def test_a_module_that_never_finishes_importing_is_named_and_the_modules_after_it_are_still_imported(tmp_path):
    checkout = a_checkout(tmp_path / "toy_app_checkout", {
        "toy_app/__init__.py": "",
        "toy_app/stuck.py": "import time\ntime.sleep(60)\n",
        "toy_app/zulu.py": "",
    })

    swept = import_sweep.sweep(checkout, python=sys.executable, each_within_s=5)

    assert swept.imported == ["toy_app", "toy_app.zulu"]
    assert "did not finish importing within 5 s" in swept.failures["toy_app.stuck"]


def test_the_checkout_swept_is_imported_ahead_of_any_other_copy_on_the_interpreter_s_path(tmp_path, monkeypatch):
    elsewhere = a_checkout(tmp_path / "an_installed_copy", {
        "toy_app/__init__.py": 'raise ImportError("the installed copy was imported, not the checkout")\n',
    })
    monkeypatch.setenv("PYTHONPATH", str(elsewhere))
    monkeypatch.setenv("PYTHONSAFEPATH", "1")
    checkout = a_checkout(tmp_path / "toy_app_checkout", {"toy_app/__init__.py": ""})

    swept = import_sweep.sweep(checkout, python=sys.executable)

    assert (swept.imported, swept.failures) == (["toy_app"], {})


def test_the_checkout_is_imported_with_the_environment_it_is_handed(tmp_path):
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "shared_thing.py").write_text("FIXED = True\n", encoding="utf-8")
    checkout = a_checkout(tmp_path / "toy_app_checkout", {"toy_app/__init__.py": "from shared_thing import FIXED\n"})

    swept = import_sweep.sweep(checkout, python=sys.executable,
                               env={**os.environ, "PYTHONPATH": str(tmp_path / "shared")})

    assert (swept.imported, swept.failures) == (["toy_app"], {})


def test_the_command_passes_a_checkout_whose_every_module_imports_and_says_how_many(tmp_path, capsys):
    checkout = a_checkout(tmp_path / "toy_app_checkout", {"toy_app/__init__.py": "", "toy_app/alpha.py": ""})

    assert import_sweep.main(["--python", sys.executable, str(checkout)]) == 0

    assert "imported all 2 modules" in capsys.readouterr().err


def test_the_command_fails_a_checkout_with_a_module_that_does_not_import_and_shows_why(tmp_path, capsys):
    checkout = a_checkout(tmp_path / "toy_app_checkout", {
        "toy_app/__init__.py": "",
        "toy_app/dispatch.py": 'RETRACT = {"held": 1}["retracted"]\n',
    })

    assert import_sweep.main(["--python", sys.executable, str(checkout)]) == 1

    said = capsys.readouterr().err
    assert "toy_app.dispatch" in said
    assert "KeyError: 'retracted'" in said
    assert "1 of 2 modules did not import" in said


def test_the_command_fails_a_checkout_it_finds_nothing_to_import_in(tmp_path, capsys):
    checkout = a_checkout(tmp_path / "toy_app_checkout", {"toy_app/__init__.py": ""},
                          pyproject='[project]\nname = "toy-app"\n')

    assert import_sweep.main(["--python", sys.executable, str(checkout)]) == 1

    assert "no package matches" in capsys.readouterr().err
