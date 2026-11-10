from __future__ import annotations

OUTPUT_TAG = "[output]"
INPUT_TAG = "[input]"
TEMP_TAG = "[temp]"
LOAD_IMAGE_TYPE_TAGS = frozenset({OUTPUT_TAG, INPUT_TAG, TEMP_TAG})


def split_annotation(image_ref: str | None) -> tuple[str, str]:
    ref = (image_ref or "").strip()
    stem, _, tag = ref.rpartition(" ")
    if stem and tag in LOAD_IMAGE_TYPE_TAGS:
        return stem, tag
    return ref, ""


def unannotated(image_ref: str | None) -> str:
    return split_annotation(image_ref)[0]


def reference_basename(path: str | None) -> str:
    return (path or "").replace("\\", "/").rsplit("/", 1)[-1]


def frame_name(image_ref: str | None) -> str:
    return reference_basename(unannotated(image_ref)).lower()
