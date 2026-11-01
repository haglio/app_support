# app_support — Project-Specific Instructions

Shared rules are in the global `~/.claude/CLAUDE.md`. This file contains only
app_support-specific overrides.

**Keep this file short.** No redundancy with the global CLAUDE.md. One bullet
per rule. If editing this file, remove or consolidate — never just append.

## Running tests

Run the suite in any consumer's venv and point `PYTHONPATH` at the checkout
under test. The production checkout's own `.venv` runs the production updater
and holds nothing else, so never run a suite or install anything into it:

```bash
PYTHONPATH="<checkout>" "C:/path/to/fun_time/.venv/Scripts/python.exe" -m pytest "<checkout>/tests"
```

Without it a worktree's suite imports `app_support` from the **primary**
checkout, because that is where every consumer's editable install points — so
it goes green about code the branch never ran, and only a module the primary
lacks entirely fails loudly. `tests/conftest.py` refuses such a run.

## Installing

Always `--config-settings editable_mode=compat`; the README says why, and
`tests/test_install.py` goes red if a venv is ever reinstalled without it.

## What belongs here

- **Nothing that knows a domain, with one exception that was decided.** No
  video, no devices, no app names in a module's reason for existing. If
  explaining a module requires naming an app, it belongs to that app. Playback
  sharing is `../funestra`; Qt widgets are `../shared_ui`. The exception is
  an on-disk format several apps agree on and none owns — the funscript
  document, the rule pairing a tree of records with the tree it mirrors, the
  state-file names — which the owner put here rather than in a library only
  some of them install (audit Q11). A format, not behavior: what the bytes are,
  never what an app does with them.
- **Standard library only.** This installs into every app's venv, so a
  dependency here is a dependency everywhere.
- **Only what a second repo needs.** One caller means it stays with its caller.

## Changing this repo changes every app

A change reaches a consumer when that consumer takes the release it makes:
each landing tags a version and opens, in every repo pinning this one behind
it, a pull request taking the newest release (`app_support.newest_pins`),
which ships once that repo's checks pass. The gate runs broker's, Fun Time's
and Origenerator's suites against the change first, and refuses one that takes
out a module or a name another repo's main uses, or an open pull request's own
changes use (`app_support.taken_out`): keep it until that work has moved off
it, then take it out. A use a pull request only has from the older main it was
cut from holds nothing up, since its next rebase takes main's.

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

Do not lean on the sanitize guard to catch it. `app_support.sanitize` fails
the suite when a **known** blocked term appears in the tracked tree, but a brand-
new performer name it has never seen passes every check and lands. The guard is a
backstop for names already known; it cannot see the next one.

So fabricate fully. Use `Jane Doe`, `Example Studio`, `scene one`, the
`alpha`/`beta`/`gamma` act placeholders the committed `content.example.json`
already uses. The near miss that still counts: taking a real filename and
changing a character or two — it is still that clip, still that performer. Make
it up from scratch, don't lightly edit a real one.

## Landing — GitHub merge queue, not local ff-merge

This repo is public at `github.com/haglio/app_support` with a merge-queue ruleset on
`main`, so the global "ff-merge into the primary checkout under
`.git/agent-merge.lock`" flow does NOT apply here:

- **Land through a pull request.** From your worktree: commit, `git fetch origin
  && git rebase origin/main`, `git push -u origin <branch>`, then
  `gh pr create --fill`. Auto-merge arms itself; the queue rebases your PR onto
  `main`, runs the required check, and merges it when green. Don't ff-merge into
  the primary checkout, don't push `main` directly, and never force-push `main`.
- **The `.git/agent-merge.lock` is retired here** — the GitHub queue serializes.
- **The production updater moves the primary checkout; never pull it yourself.**
  `main` advances only on origin (via the queue), and the production updater
  (`app_support.production_update`, run every two minutes by the "Production
  updater" scheduled task this repo declares) brings this checkout and every
  checkout beside it up to what has shipped, never while one of his programs
  runs from it. Worktrees update with `git rebase origin/main`. What it did is
  in this checkout's `state/production_update.log`, and where each checkout
  stands in `state/production_update.json`.
- **A red required check** (`.github/workflows/merge-gate.yml`) can't land.

Everything else in the global CLAUDE.md — work in a worktree, green tests before
you push, clean handoff — still applies.
