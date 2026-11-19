from __future__ import annotations

import pytest

from app_support import sentence_case

NAMES = ("Fun Time", "Job Queue", "Evolver")


@pytest.mark.parametrize("text", [
    "Generate with random seed",
    "Show this HUD again",
    "Send to the OSR2",
    "Models & LoRAs",
    "Open in Fun Time",
    "Evolver - Run history",
    "Evolver – Run history",
    "Saved. Close it now",
    "Saved: close it now",
    'Press "Generate" to start',
    "Press “Generate” to start",
    "Copy (Ctrl+C)",
    "Press Esc to stop",
    "Waiting for {Name}",
    "Video files (*.mp4);;All files (*)",
    "I can't",
    "",
])
def test_text_in_sentence_case_capitalizes_nothing_it_should_not(text):
    assert sentence_case.capitalized_words(text, NAMES) == []


@pytest.mark.parametrize(("text", "words"), [
    ("Generate with Random seed", ["Random"]),
    ("Upscale Factor", ["Factor"]),
    ("Evolver - Stage Error", ["Error"]),
    ("Place Tip Here", ["Tip", "Here"]),
    ("Pause the Queue", ["Queue"]),
    ("Fun Time Closing", ["Closing"]),
])
def test_text_in_title_case_names_each_word_sentence_case_keeps_lowercase(text, words):
    assert sentence_case.capitalized_words(text, NAMES) == words


def test_a_name_counts_only_once_a_repo_names_it():
    assert sentence_case.capitalized_words("Open the Enhanced folder", NAMES) == ["Enhanced"]
    assert sentence_case.capitalized_words("Open the Enhanced folder", (*NAMES, "Enhanced")) == []


def test_a_name_of_two_words_counts_only_whole():
    assert sentence_case.capitalized_words("Pause the Job Queue", NAMES) == []
    assert sentence_case.capitalized_words("Pause the Job", NAMES) == ["Job"]


def _module(tmp_path, source: str):
    package = tmp_path / "package"
    package.mkdir(exist_ok=True)
    (package / "screen.py").write_text(source, encoding="utf-8")
    return package


def test_the_text_a_caption_call_is_given_is_read_with_its_line(tmp_path):
    package = _module(tmp_path, 'button = QPushButton("Cancel All")\nlog("Not A Caption")\n')
    assert sentence_case.captions([package]) == [("package/screen.py", 1, "Cancel All")]


def test_a_keyword_or_a_constant_named_for_a_caption_is_read_too(tmp_path):
    package = _module(tmp_path, 'ParamDef("k", label="Upscale Factor")\n'
                                'SAVE_CAPTION = "Save Preset"\n'
                                'SIDE_LABELS = {1: "Image Actions"}\n')
    assert [text for _, _, text in sentence_case.captions([package])] == [
        "Upscale Factor", "Save Preset", "Image Actions"]


def test_a_repo_names_its_own_caption_calls(tmp_path):
    package = _module(tmp_path, 'ParamDef("enhance_scale", "Upscale Factor", 2.0)\n')
    assert sentence_case.captions([package]) == []
    assert [text for _, _, text in sentence_case.captions([package], calls=("ParamDef",))] == [
        "enhance_scale", "Upscale Factor"]


def test_a_caption_breaking_sentence_case_is_refused_with_where_it_is(tmp_path):
    package = _module(tmp_path, 'menu.addAction("Generate with Random seed")\n'
                                'menu.addAction("Open in Fun Time")\n')
    with pytest.raises(AssertionError) as refused:
        sentence_case.assert_captions_are_sentence_case([package], names=NAMES)
    assert "package/screen.py:1" in str(refused.value)
    assert "Random" in str(refused.value)
    assert "Fun Time" not in str(refused.value)


def test_a_message_box_is_read_and_a_log_line_is_not(tmp_path):
    package = _module(tmp_path, 'QMessageBox.warning(self, "Sign In Expired", "x")\n'
                                'log.warning("Could Not Read %s", path)\n')
    assert [text for _, _, text in sentence_case.captions([package])] == ["Sign In Expired", "x"]


def test_a_caption_may_name_another_caption_of_its_repo_as_it_reads_there(tmp_path):
    package = _module(tmp_path, 'QCheckBox("Enable audio")\nsetToolTip("Turn on Enable audio first")\n')
    sentence_case.assert_captions_are_sentence_case([package])


def test_a_caption_of_one_word_names_nothing_until_a_repo_names_it(tmp_path):
    package = _module(tmp_path, 'QPushButton("History")\nQLabel("Run History")\n')
    with pytest.raises(AssertionError, match="History"):
        sentence_case.assert_captions_are_sentence_case([package])
    sentence_case.assert_captions_are_sentence_case([package], names=("History",))


def test_a_caption_in_title_case_names_no_other_caption(tmp_path):
    package = _module(tmp_path, 'QCheckBox("Enable Audio")\nsetToolTip("Turn on Enable Audio first")\n')
    with pytest.raises(AssertionError, match="Audio"):
        sentence_case.assert_captions_are_sentence_case([package])


@pytest.mark.parametrize("text", ["s  |  Status: done", "%H:%M", r"\bfont\s*:\s*[A-Z_]+"])
def test_separators_time_formats_and_patterns_are_no_title_case(text):
    assert sentence_case.capitalized_words(text, NAMES) == []


def test_a_caption_inside_two_caption_calls_is_read_once(tmp_path):
    package = _module(tmp_path, 'QAction(QLabel("Cancel All"))\n')
    assert [text for _, _, text in sentence_case.captions([package])] == ["Cancel All"]


def test_a_caption_that_is_a_declared_name_is_in_sentence_case(tmp_path):
    package = _module(tmp_path, 'QLabel("Robot Hand")\n')
    sentence_case.assert_captions_are_sentence_case([package], names=("Robot Hand",))
