# app_support

The scaffolding every desktop app in this project family stands on.

Five applications launch as windowed Python processes on Windows — Fun Time,
Genau, Nau, Clipper and the OSR2 broker — and each one had grown its own
byte-identical copy of the same four things:

- **`logging_utils`** — a rotating file logger, `sys`/`threading` exception hooks
  that survive an unhandled crash, and a faulthandler for the native ones.
- **`threading_utils`** — `start_daemon_thread`.
- **`cli`** — `preparse_config_path`, the throwaway parser that reads `--config`
  before the real parser exists.
- **`subprocess_utils`** — `hidden_subprocess_kwargs`, so shelling out to ffprobe
  or PowerShell never flashes a console window over the video.

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

## Tests

```bash
".venv/Scripts/python.exe" -m pytest tests/
```

There is no venv in this repo — run the suite with any consumer's, all of which
have this package installed.
