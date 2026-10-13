from __future__ import annotations

from app_support.file_channel import consume_command_file
from app_support.osr2_hold import PARK, RESUME, RETRACT, ask_the_broker, hold_tcode
from app_support.state_files import BROKER_CMD


def test_asking_the_broker_queues_each_verb_for_its_next_tick(tmp_path):
    ask_the_broker(tmp_path, PARK)
    ask_the_broker(tmp_path, RESUME)

    assert consume_command_file(tmp_path / BROKER_CMD) == [PARK, RESUME]


def test_a_park_sets_the_osr2_down_at_home_over_a_whole_second():
    assert hold_tcode(PARK) == "L00000I1000"


def test_a_retract_sends_it_to_the_far_end_over_half_a_second():
    assert hold_tcode(RETRACT) == "L09999I500"
