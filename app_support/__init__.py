"""The scaffolding every desktop app in this project family stands on: what every
repo had grown its own byte-identical copy of, held once.  README.md lists the
modules.

Nothing here knows anything about video, devices, or any application's domain.
That is the line: if a module would have to name an app to explain itself, it
belongs to that app. Playback-specific sharing lives in ``player_core``; shared
Qt widgets live in ``shared_ui``.
"""
