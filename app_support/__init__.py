"""The scaffolding every desktop app in this project family stands on.

Five separate applications — Fun Time, Genau, Nau, Clipper and the OSR2 broker —
each launch as a windowed Python process on Windows, each write a rotating log,
each install the same exception hooks, each start daemon threads, and each shell
out without flashing a console window. They had all grown their own byte-identical
copy of that code.

Nothing here knows anything about video, devices, or any application's domain.
That is the line: if a module would have to name an app to explain itself, it
belongs to that app. Playback-specific sharing lives in ``player_core``; shared
Qt widgets live in ``shared_ui``.
"""
