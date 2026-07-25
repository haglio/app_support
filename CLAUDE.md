# app_support — Project-Specific Instructions

Shared rules are in the global `~/.claude/CLAUDE.md`. This file contains only
app_support-specific overrides.

**Keep this file short.** No redundancy with the global CLAUDE.md. One bullet
per rule. If editing this file, remove or consolidate — never just append.

## Running tests

This repo has no venv of its own. Use any consumer's — all have this package
installed editable:

```bash
"C:/path/to/fun_time/.venv/Scripts/python.exe" -m pytest tests/
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

## Test fixtures must be fabricated, never copied from the real library

Every fixture value that stands in for library data — a video title, a filename,
a performer or studio name, prompt text — must be **invented**. Never paste a
real one out of the media library to make a test feel realistic.

This is not a style note. It is the single thing that has actually leaked private
data into these repos: an agent writing a test reached for a real filename or
performer name because it was handy, and it rode into a public commit. Nothing in
the app's *design* pulls library text into source — the library lives outside
every repo, read at runtime through the git-ignored overlays — so this habit is
the only remaining path for a real name to get committed, and the only thing
stopping it is you following this rule.

Do not lean on the sanitize guard to catch it. `tools/sanitize_guard.py` fails
the suite when a **known** blocked term appears in the tracked tree, but a brand-
new performer name it has never seen passes every check and lands. The guard is a
backstop for names already known; it cannot see the next one.

So fabricate fully. Use `Jane Doe`, `Example Studio`, `scene one`, the
`alpha`/`beta`/`gamma` act placeholders the committed `content.example.json`
already uses. The near miss that still counts: taking a real filename and
changing a character or two — it is still that clip, still that performer. Make
it up from scratch, don't lightly edit a real one.
