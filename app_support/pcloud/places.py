from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from app_support.mirrored_tree import relative_under


class CloudPlaces:
    def __init__(self, folders: Mapping[Path | str, str]) -> None:
        self._folders = [(Path(local), cloud.rstrip("/")) for local, cloud in folders.items()]

    def cloud_path_of(self, path: Path) -> str | None:
        for local, cloud in self._folders:
            relative = relative_under(path, local, ask_the_disk=False)
            if relative is not None:
                spelled = Path(os.path.abspath(path)).parts
                return "/".join([cloud, *spelled[len(spelled) - len(relative.parts):]])
        return None

    def local_path_of(self, cloud_path: str) -> Path | None:
        for local, cloud in sorted(self._folders, key=lambda folder: len(folder[1]), reverse=True):
            if cloud_path.startswith(cloud + "/"):
                return local.joinpath(*cloud_path[len(cloud) + 1:].split("/"))
        return None
