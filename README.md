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
- **`dead_code`** — the family's vulture gate in one shape, so eleven repos stop
  keeping six. See below.
- **`launch_smoke`** — reads everything a launcher's entry point imports off its
  AST so a test can replay it in a fresh interpreter. A windowed launch has no
  console, so an import that fails inside one leaves the icon doing nothing and
  the suite entirely green.
- **`process_identity`** — the copy of its interpreter an app starts each of its
  processes through, named and described for the task list; `name_this_process`
  is the call at the top of every `main()`. **`process_identity_check`** runs an
  app's own naming against a throwaway venv and reads back what it made, so no
  suite has to grep its entry point for the call.
- **`overlay`** — the content overlay every app keeps its private values in:
  which file answers, what a partial local overlay is short of, and the three
  answers a repo can give for a missing key (backfill, empty, refuse).
  **`config_reader`** — the JSON config loader's helpers, each refusal naming the
  dotted key and the file. **`siblings`** — where the other checkouts are, asked
  one way: the walk that finds a sibling from a clone and a worktree alike, the
  sys.path rule that never shadows the app's own packages, and the overlay's
  project roots. **`dependencies`** — the gate that every third-party import a
  package makes is a dependency its pyproject declares.
- **`file_channel`** — the files one process steers another through and the
  files it publishes back: a command queue appended to and claimed whole, a flag
  read as one character with a caller-named default, a wall-clock stamp and its
  age, a `key=value` record, and the whole-or-nothing publish under all of them.
  **`state_files`** spells the names of the files two repos meet at, once, with
  who writes each, who reads it and what it holds; its tests run each writer
  against its reader.
- **`win32`** — what a windowed process says about itself to Windows: its
  taskbar identity, the same identity stamped onto (and read back off) a
  shortcut through COM, the named mutex that answers whether it may run, and
  the error popup for a process with nowhere else to say it. Every call raises
  on refusal and none decides what that means; the caller keeps its try/except.
- **`peer_watch`** — two apps that must both be up all the time watching each
  other, so neither stays dead until the next sign-in, plus the stand-down marker
  that keeps a revival from arguing with a quit the user meant. The marker's path
  is spelled there once because its writer and its reader are different
  applications with no import between them.

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

**Nothing this package reads is committed.** There is one blocklist for every
checkout, at `.sanitize/blocklist.txt` in the directory the checkouts sit in —
outside every repository, because the list describes the machine and a committed
copy of it would be the catalogue the guard exists to keep out. The leading dot
marks it as not one of the checkouts beside it. One term per line; blank lines
and `#` comments are skipped.

A checkout with no blocklist beside it enforces nothing and commits normally —
that is what a public clone and a fresh CI checkout both look like.

## The dead-code gate

`app_support.dead_code` runs vulture over the directories a repo names and fails
the suite on the report:

```python
# tests/test_dead_code.py
from pathlib import Path

from app_support.dead_code import assert_no_dead_code

ROOT = Path(__file__).resolve().parent.parent


def test_no_dead_code():
    assert_no_dead_code(ROOT / "the_package", whitelist=ROOT / "vulture_whitelist.py")
```

Add `vulture` to the repo's `[dev]` extra — it is the *scanning* repo's dev
dependency, never this package's, which installs into every app's venv.

**Name the production directories; never scan `.` behind an `--exclude` list.**
vulture matches those patterns against absolute paths, and an agent's checkout
lives at `<repo>/.claude/worktrees/<name>` — so `--exclude .claude` matches the
root of the tree being scanned and excludes every file in it. Three repos here
carried that no-op and say so in the docstrings of the gates they fixed.

**Keep the whitelist outside the trees it applies to.** vulture reads it by
unioning the names it uses with the names the scanned tree uses, so a whitelist
kept *inside* a scanned directory is read as part of that tree — every name in
it counts as used, the gate reports nothing whatever the tree holds, and the
liveness check calls every entry stale. The scan refuses that arrangement rather
than running it.

**The whitelist may not outlive what it suppresses.** `assert_whitelist_is_live`
re-runs the scan without the whitelist and fails on any name in it that no
longer appears. The file records the exceptions a repo decided on, so an entry
whose subject was deleted is not merely untidy — it is a standing exemption for
whatever name matches it next. One repo here reached 31 dead entries out of 45,
23 of them naming symbols the family no longer contains.

**Silence is not a pass unless something was read.** vulture reports nothing for
a clean tree, and also for a directory holding no Python, for input it could not
parse, and for not being installed at all. The scan tells them apart — it checks
that each target has Python under it before starting, and treats every exit code
but "clean" and "here is the report" as a scan that did not happen. A gate that
conflates them goes green the day its target is renamed and stays green.

**The rest of what a dead-code gate asks.** Two repos had grown checks the
scan cannot make, and they are published beside it so every repo asks the same
questions: `assert_every_package_is_scanned` (a package added beside the named
ones gets no gate otherwise); `assert_nothing_is_imported_or_assigned_and_left_unread`
and `assert_no_function_takes_an_argument_it_never_reads`, which run ruff's F401/
F811/F841 and ARG rules per file with the repo's own config set aside, since
vulture resolves names across the whole tree and misses an import that is dead
here and alive next door; and `app_support.unread`, the AST scans for what is
written and never read -- a module constant, a constructor parameter stored on
`self`, a dataclass field, an `argparse` option, a helper left in a test file.
Each is a floor: a name that collides with a live one elsewhere is not reported.

## The lint gate

`app_support.lint` holds the family's ruff config -- line length 100, double
quotes, the audit's select with `E501`, `BLE001` and `S110` ignored -- and the
check that runs it. A repo commits the `ruff.toml` that `render_config` writes
and asks for both halves:

```python
# tests/test_lint.py
from pathlib import Path

from app_support.lint import assert_config_is_the_familys, assert_lint_is_clean

ROOT = Path(__file__).resolve().parent.parent


def test_the_ruff_config_is_the_familys():
    assert_config_is_the_familys(ROOT / "ruff.toml")


def test_ruff_finds_nothing():
    assert_lint_is_clean(ROOT, ROOT / "the_package", ROOT / "tests")
```

Add `ruff==0.16.6` -- `lint.RUFF_VERSION`, the one version the gate accepts --
to the repo's `[dev]` extra; another version finds other things and is refused
rather than trusted.

**One config, eleven copies that cannot differ.** The first test renders the
family's config around the repo's own ratchet -- the rules the config found
there on the day it was adopted, listed at the end of `ignore` -- and refuses a
file that differs anywhere else. Work a ratchet off by deleting its code from
the list and fixing what ruff then reports; change the family's numbers here.
A `# noqa` for a ratcheted rule, or for a rule another gate runs with a select
of its own (`ARG`, `N`, `S`), is dormant rather than unused: the config lists
those as `external`, and RUF100 leaves the marker for the gate that reads it.

**Silence is not a pass unless something was read.** The second test names the
trees ruff scans -- the root's own files are always in, `.` never is, since a
gate checks out sibling repos beside or inside this one -- refuses a tree it
scanned nothing under, and treats a missing ruff, another version, or a refused
configuration as a scan that did not happen.

## Tests

```bash
".venv/Scripts/python.exe" -m pytest tests/
```

There is no venv in this repo — run the suite with any consumer's, all of which
have this package installed.
