from __future__ import annotations

TCODE_UDP = 50557
OSR2_SLOT = 50558
GENAU_UDP = 50555
AUDIO_COMPANION = 50556
# Chrome refuses to update a userscript from a file:// path, so the script's @updateURL carries this number.
USERSCRIPT_HTTP = 8770

WHO_MEETS_ON: dict[str, str] = {
    "TCODE_UDP": "The broker listens; Fun Time, Genau, the Main Funestra and Origenerator send.",
    "OSR2_SLOT": "The broker listens; whichever sender has the OSR2 connects and sends.",
    "GENAU_UDP": "Genau listens; the broker and Fun Time's headset send.",
    "AUDIO_COMPANION": "Fun Time's audio companion listens; Genau and Fun Time's headset send.",
    "USERSCRIPT_HTTP": "Fun Time's loopback server listens; Chrome sends.",
}
