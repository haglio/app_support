# app_support

The scaffolding every desktop app in this project family stands on.

Five applications launch as windowed Python processes on Windows — Fun Time,
Genau, Nau, Clipper and the OSR2 broker — and each one had grown its own
byte-identical copy of the same four things:

- **`logging_utils`** — a rotating file logger, `sys`/`threading` exception hooks
  that survive an unhandled crash, and a faulthandler for the native ones.
- **`threading_utils`** — `start_daemon_thread`, and `wait_until` for
  synchronising on the event itself rather than on a fixed nap.
- **`cli`** — `preparse_config_path`, the throwaway parser that reads `--config`
  before the real parser exists.
- **`subprocess_utils`** — `hidden_subprocess_kwargs`, so shelling out to ffprobe
  or PowerShell never flashes a console window over the video.

Two more things every repo in the family needs, and used to keep its own copy of:

- **`sanitize`** — the pre-publication content guard, plus the pytest plugin
  that enforces a clean tracked tree. See below.
- **`launch_smoke`** — reads everything a launcher's entry point imports off its
  AST so a test can replay it in a fresh interpreter. A windowed launch has no
  console, so an import that fails inside one leaves the icon doing nothing and
  the suite entirely green.

Standard library only, on purpose: this is installed into every app's venv, so a
dependency here becomes a dependency everywhere.

## What does not belong here

Nothing that knows about video, devices, or any application's domain. If a module
would have to name an app to explain itself, it belongs to that app.

The family has three shared repos, and the line between them is what a module
knows about:

| Repo | Holds |
| --- | --- |
| `app_support` | process/logging/CLI scaffolding — knows nothing |
| `player_core` | the libmpv wrapper, playlist format, player file protocol |
| `shared_ui` | shared Qt widgets and design tokens |

## Install

Each consuming project installs this editable into its own venv, from a local
path — this package is never published, so it must not appear in any project's
`[project.dependencies]`:

```bash
".venv/Scripts/python.exe" -m pip install -e ../app_support --config-settings editable_mode=compat
```

**`editable_mode=compat` is required, not cosmetic.** This repo's directory is
named `app_support`, the same as the package inside it, and the directory holding
all these repos is itself on `sys.path` in some venvs (via `shared_ui.pth`).
Setuptools' *default* editable install resolves the top-level name through a
meta-path finder that `PathFinder` never reaches, so the repo root wins as an
implicit namespace package: submodules still import, but `__init__.py` never
runs. `compat` mode puts the repo root on `sys.path` instead, where a real
package beats a namespace portion. `tests/test_install.py` fails loudly if this
is ever reinstalled the other way.

## The content guard

`app_support.sanitize` refuses to let a blocklisted term reach a public commit.
Two ways in, and a repo can take either:

```bash
# 1. the git hooks, which catch a term while the fix is still free
python tools/githooks/install.py

# 2. the suite, which catches it afterwards -- one line in pyproject.toml
#    [tool.pytest.ini_options]
#    addopts = "-p app_support.sanitize.pytest_plugin"
```

**The hooks fail loudly.** While the guard was a file in each repo it ran off any
interpreter, so "cannot run" meant "no python at all". Now it is an installed
package and "cannot run" means "not installed in the interpreter this hook
found" — a checkout that has silently stopped being guarded. So there is no
`exit 0` in either hook: if the import fails, the commit fails.

**Each needs this package reachable from a different interpreter, and that is
the whole of what adopting them costs.** The hooks use the first `.venv` they
find or else a bare `python` off `PATH`; the plugin uses whatever runs the
suite, and a `-p` it cannot import is a hard pytest failure with no
tests run, not a soft one. So the check worth making before a repo takes any of
them is `<that interpreter> -c "import app_support.sanitize"` — a repo with no
venv, or one whose CI never installs this package, needs that settled first.

**Nothing this package reads is committed.** Every list lives in git-ignored
`sanitize/*.local.txt` files, because the lists describe the machine and a
committed copy of one would be the catalogue the guard exists to keep out:

| File | Holds |
| --- | --- |
| `blocklist.local.txt` | the terms to refuse (`blocklist.example.txt` documents the format) |

A checkout with no blocklist enforces nothing and commits normally — that is what
a public clone and a fresh CI checkout both look like.

## Tests

```bash
".venv/Scripts/python.exe" -m pytest tests/
```

There is no venv in this repo — run the suite with any consumer's, all of which
have this package installed.
