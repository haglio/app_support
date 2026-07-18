# app_support — Project-Specific Instructions

Shared rules are in the global `~/.claude/CLAUDE.md`. This file contains only
app_support-specific overrides.

**Keep this file short.** No redundancy with the global CLAUDE.md. One bullet
per rule. If editing this file, remove or consolidate — never just append.

## Running tests

This repo has no venv of its own. Use any consumer's — all have this package
installed editable:

```bash
"C:/path/to/suite-root/projects/fun_time/.venv/Scripts/python.exe" -m pytest tests/
```

## Installing

Always `--config-settings editable_mode=compat`; the README says why, and
`tests/test_install.py` goes red if a venv is ever reinstalled without it.

## What belongs here

- **Nothing that knows a domain.** No video, no devices, no app names in a
  module's reason for existing. If explaining a module requires naming an app,
  it belongs to that app. Playback sharing is `../player_core`; Qt widgets are
  `../shared_ui`.
- **Standard library only.** This installs into every app's venv, so a
  dependency here is a dependency everywhere.
- **Only what a second repo needs.** One caller means it stays with its caller.

## Changing this repo changes five apps

A change lands in every consumer the moment it is saved — they install this
editable, so there is no version to bump and no buffer against a mistake. Run
the consumers' suites, not just this one.
