"""The names of the files two repos meet at, spelled once.

Each is a wire format: a writer in one repo, a reader in another, and a file
under a state directory both are told about.  Until now every config module
that built one of these paths spelled the name itself -- four of them, and
clipper's copy pointed at the wrong directory -- with no shared constant, no
schema and no test that ran both sides.

A name cannot change.  A broker started before the change, by the scheduled task
that revives it every couple of minutes, keeps writing the old one while an
orchestrator started after it reads the new, and neither knows.  So these are
constants in the one package every repo installs, each saying who writes it,
who reads it and what it holds -- the schema the files never had -- and
``tests/test_state_files.py`` runs each one's writer against its reader through
the :mod:`app_support.file_channel` calls both sides use.

A file one repo alone spells -- the satellites' channels, Nau's, the hosted
Origenerator's -- stays in that repo's config: one owner already.
"""
from __future__ import annotations

# --- The broker's, under its own state directory -----------------------------

BROKER_CMD = "broker_cmd.txt"
"""Fun Time -> broker.  A queue of verbs -- PARK, RETRACT, RESUME -- joined with
``append_command`` and drained whole each tick with ``consume_command_file``."""

BROKER_HEARTBEAT = "broker_heartbeat.txt"
"""Broker -> Fun Time.  The wall clock as text (``publish_stamp``), every half
second while the broker holds the serial port; read as an age (``stamp_age``)."""

GENAU_MODE = "genau_mode.txt"
"""Broker -> Fun Time.  ``"1"`` while Genau has the OSR2, ``"0"`` otherwise
(``write_flag`` / ``read_flag`` with a default of False)."""

GENAU_ENABLED = "genau_enabled.txt"
"""Fun Time and Origenerator -> broker.  ``"0"`` forbids the broker handing the
OSR2 to Genau; absent or blank means allowed (``read_flag`` with a default of
True), so the file is a switch that is on until somebody turns it off."""

OSR2_SERIAL_RX = "osr2_serial_rx.txt"
"""Broker -> Fun Time and Origenerator.  A stamp of the device's last word: how
the session knows the OSR2 is powered on."""

OSR2_SERIAL_TX = "osr2_serial_tx.txt"
"""Broker -> Fun Time.  A stamp of the last word TO the device: a driver sending
is a device in use even while it says nothing back."""

# --- Genau's channel, under the orchestrator's state directory ---------------

GENAU_CMD = "genau_cmd.txt"
"""Fun Time -> Genau.  A queue of verbs."""

GENAU_PAUSED = "genau_paused.txt"
"""Fun Time -> Genau.  ``"1"`` while paused (``read_paused_state``)."""

GENAU_DRIVE = "genau_drive.txt"
"""Genau -> Nau.  The drive readout, published whole; its lines are
``player_core.drive_readout``'s."""

GENAU_STATUS = "genau_status.txt"
"""Genau -> Fun Time.  ``key=value`` lines, published whole (``read_key_values``);
the keys are ``player_core.genau_status``'s."""
