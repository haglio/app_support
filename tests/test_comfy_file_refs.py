from __future__ import annotations

from app_support.comfy_file_refs import (
    frame_name,
    reference_basename,
    split_annotation,
    unannotated,
)


def test_split_annotation_takes_the_type_tag_off_and_nothing_else():
    assert split_annotation("image/gen_00001_.png [output]") == ("image/gen_00001_.png", "[output]")
    assert split_annotation("frame.png [input]") == ("frame.png", "[input]")
    assert split_annotation("frame.png") == ("frame.png", "")
    assert split_annotation("a name with spaces.png") == ("a name with spaces.png", "")
    assert split_annotation("") == ("", "")
    assert split_annotation(None) == ("", "")
    assert unannotated("x.png [temp]") == "x.png"


def test_frame_name_is_the_key_a_stored_file_and_a_reference_share():
    assert frame_name("image/gen_00001_.png [output]") == "gen_00001_.png"
    assert frame_name("Sub/Wan22_T2I_00005_.PNG [output]") == "wan22_t2i_00005_.png"
    assert frame_name("gen_00001_.png") == "gen_00001_.png"
    assert frame_name("C:\\comfy\\output\\image\\GEN_00001_.PNG") == "gen_00001_.png"
    assert frame_name("") == ""
    assert frame_name(None) == ""


def test_a_reference_with_space_around_it_names_the_same_frame_as_one_without():
    assert frame_name("  image/gen_00001_.png [output] ") == frame_name("image/gen_00001_.png [output]")
    assert frame_name(" gen_00001_.png\n") == "gen_00001_.png"


def test_reference_basename_tolerates_either_separator():
    assert reference_basename("a/b/c.png") == "c.png"
    assert reference_basename("a\\b\\c.png") == "c.png"
    assert reference_basename("c.png") == "c.png"
    assert reference_basename(None) == ""
