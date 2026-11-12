from __future__ import annotations

import json
import re
from pathlib import PurePath

from app_support.comfy_file_refs import frame_name
from app_support.gallery_rows import VideoRows, file_entries, is_video_name
from app_support.video_action import STORED_ACTIONS_KEY
from app_support.video_kind import classify
from app_support.watch_weights import COUNT_FIELDS, WATCH_BLOCK, WEIGHT_KEY, weight_for

RECORD_COLUMNS = (
    "prompt_id", "source", "params_json", "output_files", "evolver_upscale",
    "positive_prompt", "negative_prompt", "seed",
    "recipe_category", "combined_labels", "starred",
    "watch_completions", "watch_skips", "watch_locks",
    "shape", "video_seconds", "genau_flipped",
)

_SETTINGS = ("model", "style", "resolution", "aspect_ratio", "quality", "creativity")
VIDEO, IMAGE = "video", "image"
PLACES = {
    VIDEO: {"prompt": "positive_prompt", "seed": "seed", **{name: name for name in _SETTINGS}},
    IMAGE: {"positive_prompt": "positive_prompt", "negative_prompt": "negative_prompt",
            "seed": "seed", **{name: name for name in _SETTINGS}},
}
INPUT_IMAGE_KEY = "input_image"
SOURCE_IMAGE = "source_image"
FRAME_OF_VIDEO = "frame_of_video"
GENAU_SECTION, FLIPPED = "genau", "flipped"
ORIENTATIONS = ("portrait", "landscape")

_OUTSIDE = "outside"
_MADE_ELSEWHERE = frozenset({_OUTSIDE, "starting_frame", "left_out"})
_ACTION_COLUMN, _ACTION_AS_READ = "recipe_category", "action"
WATCH_COLUMNS = tuple((field, f"watch_{field}") for field in COUNT_FIELDS)
MODEL_KEYS = ("unet_high", "unet", "checkpoint", "unet_low")
_MODEL_EXT_RE = re.compile(r"\.(safetensors|ckpt|pt|pth|gguf|sft|bin)$", re.IGNORECASE)


def model_label(params: dict) -> str:
    for key in MODEL_KEYS:
        if value := params.get(key):
            return _MODEL_EXT_RE.sub("", str(value).replace("\\", "/").rsplit("/", 1)[-1])
    return ""


def _made_here_block(row: dict, fields: tuple[tuple[str, str], ...]) -> dict:
    seed = row.get("seed")
    found = {**{key: row.get(column) for key, column in fields},
             "model": model_label(params_of(row)), "seed": str(seed) if seed is not None else None}
    return {key: value for key, value in found.items() if value}


def recorded_block(params: dict, made: str) -> dict:
    return {key: params[place] for key, place in PLACES[made].items()
            if params.get(place) not in (None, "")}


def params_of(row: dict) -> dict:
    try:
        params = json.loads(row.get("params_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return params if isinstance(params, dict) else {}


def orientation_of(row: dict, video: PurePath | None) -> str | None:
    if row.get("shape") in ORIENTATIONS:
        return row["shape"]
    folders = PurePath(video).parent.parts if video is not None else ()
    return next((folder for folder in reversed(folders) if folder in ORIENTATIONS), None)


def _made_here(row: dict) -> bool:
    return (row.get("source") or "generated") not in _MADE_ELSEWHERE


def _frame_names(row: dict) -> set[str]:
    return {frame_name(entry["filename"]) for entry in file_entries(row) if entry.get("filename")}


def _is_video(row: dict) -> bool:
    return any(is_video_name(entry.get("filename") or "") for entry in file_entries(row))


class GalleryReading:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = {row["prompt_id"]: row for row in rows}
        self._row_of = VideoRows(rows)
        self._images = {name: row for row in reversed(rows) if not _is_video(row)
                        for name in _frame_names(row)}
        self._videos_from_frame: dict[str, list[dict]] = {}
        for row in rows:
            if frame := frame_name(params_of(row).get(INPUT_IMAGE_KEY)):
                self._videos_from_frame.setdefault(frame, []).append(row)

    def row_of(self, video) -> dict | None:
        return self._rows.get(self._row_of(video))

    def start_image_of(self, row: dict) -> dict | None:
        return self._images.get(frame_name(params_of(row).get(INPUT_IMAGE_KEY)))

    def record_of(self, row: dict, *, where: PurePath | None = None, genau: bool = False,
                  seconds: float | None = None) -> dict:
        record = self._record_kept(row)
        start_image = self.start_image_of(row)
        if (frame_of := self._words_video_of_frame(row, start_image)) is not None:
            record[SOURCE_IMAGE] = {**record.get(SOURCE_IMAGE, {}), FRAME_OF_VIDEO: frame_of}
        counts = {field: int(row.get(column) or 0) for field, column in WATCH_COLUMNS}
        shown = record["video"]
        if orientation := orientation_of(row, PurePath(where) if where else self._kept_at(row)):
            shown["orientation"] = orientation
        shown["type"] = classify(genau=genau, excerpt=False, duration_seconds=(
            seconds if seconds is not None else row.get("video_seconds")))
        record.update({"favorite": bool(row.get("starred")),
                       WATCH_BLOCK: {**counts, WEIGHT_KEY: weight_for(counts)}})
        if row.get("genau_flipped"):
            record[GENAU_SECTION] = {FLIPPED: True}
        return record

    def _record_kept(self, row: dict) -> dict:
        shown = (_made_here_block(row, (("prompt", "positive_prompt"),)) if _made_here(row)
                 else recorded_block(params_of(row), VIDEO))
        if action := row.get(_ACTION_COLUMN, row.get(_ACTION_AS_READ)):
            shown["action"] = action
        if labels := json.loads(row.get("combined_labels") or "[]"):
            shown[STORED_ACTIONS_KEY] = labels
        record: dict = {"video": shown}
        start_image = self.start_image_of(row)
        if start_image is None:
            return record
        if start_image.get("source") == _OUTSIDE:
            record[SOURCE_IMAGE] = recorded_block(params_of(start_image), IMAGE)
        elif _made_here(row):
            record[SOURCE_IMAGE] = _made_here_block(start_image, (
                ("positive_prompt", "positive_prompt"), ("negative_prompt", "negative_prompt")))
        return record

    def _words_video_of_frame(self, video: dict, start_image: dict | None) -> dict | None:
        if start_image is None or not _made_here(video):
            return None
        for frame in _frame_names(start_image):
            for other in self._videos_from_frame.get(frame, ()):
                kept = self._record_kept(other)
                if other is not video and SOURCE_IMAGE not in kept and kept["video"].get("prompt"):
                    return kept["video"]
        return None

    @staticmethod
    def _kept_at(row: dict) -> PurePath | None:
        kept = next((entry.get("library_path") for entry in file_entries(row)
                     if entry.get("library_path")), None)
        return PurePath(kept) if kept else None
