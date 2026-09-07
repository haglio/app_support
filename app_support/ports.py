"""The port numbers this family claims on one machine, spelled once.

Each is an agreement: a process in one repo binds it, processes in others send
to it, and nothing on either side fails when a copy drifts -- a datagram sent to
a port nobody is listening on is indistinguishable, to every sender here, from a
listener that is down.  So a mistyped port is not an error anywhere; it is a
feature that quietly stops working.

They were compiled-in defaults in five repos' configs, none of which knew about
the others.  Here they are one list, each saying who listens and who sends, and
the suite holds two things a scattered list could not: that no two of them are
the same number, and that every one of them says who meets on it.

A port is admitted by being claimed on the machine, not by having senders in
another repo: two of these could collide with each other whoever sends to them,
and that is the failure one list exists to make impossible.  This is where
:mod:`app_support.state_files` draws its line differently -- a file only one
repo spells belongs to that repo, because two files in different directories
cannot collide.
"""
from __future__ import annotations

TCODE_UDP = 50557
"""The broker listens; Fun Time, Genau, Nau and Origenerator send.

The device protocol: position-and-duration lines the broker relays over serial
to the hardware.  ``player_core.tcode.UdpTCodeSink`` is the socket all four
senders reach it through, and its own default is this number."""

GENAU_UDP = 50555
"""Genau listens; the broker and Fun Time's VR player send.

The verbs that steer Genau from outside -- show, hide, sync, and the motion and
tempo it should take up."""

AUDIO_COMPANION = 50556
"""Fun Time's audio companion listens; Genau and Fun Time's VR player send.

What the companion is told about the session it is scoring."""

USERSCRIPT_HTTP = 8770
"""Fun Time's loopback server listens; Chrome sends.

Bound to ``127.0.0.1`` only.  It serves the autofill userscript -- whose own
``@updateURL`` header carries this number, since Chrome refuses to update a
script from a ``file://`` path -- and answers the pause poll the browser tab
pages make."""
