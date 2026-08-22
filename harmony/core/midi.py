"""Standard MIDI file output.

Shared by the CLI and the web layer so there is only one encoder. A type-0
file with a tempo and a time signature, one chord per beat.

This is the one place meter is legitimately used: it is written into the
file's time signature, which is a notation fact, not a rule.
"""

from __future__ import annotations

import struct

from .voice import Voicing

TICKS_PER_BEAT = 480


def _varint(value: int) -> bytes:
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(out)


def to_bytes(
    voicings: list[Voicing],
    tempo_bpm: float = 84.0,
    beats_per_chord: int = 1,
    meter: tuple[int, int] = (4, 4),
    velocity: int = 72,
) -> bytes:
    """Encode a realization as a type-0 standard MIDI file."""
    if not voicings:
        raise ValueError("nothing to write")
    tempo_bpm = max(20.0, min(float(tempo_bpm), 400.0))

    events = bytearray()

    # tempo, in microseconds per quarter note
    micros = int(round(60_000_000 / tempo_bpm))
    events += _varint(0) + b"\xFF\x51\x03" + micros.to_bytes(3, "big")

    # time signature: numerator, log2(denominator), clocks per click, 32nds per quarter
    numerator, denominator = meter
    power = max(0, denominator.bit_length() - 1)
    events += _varint(0) + b"\xFF\x58\x04" + bytes([numerator, power, 24, 8])

    duration = TICKS_PER_BEAT * beats_per_chord
    for voicing in voicings:
        notes = sorted(pitch.midi for pitch in voicing.pitches)
        for note in notes:
            events += _varint(0) + bytes([0x90, note, velocity])
        # the whole duration sits on the first note-off; the rest are simultaneous
        for offset, note in enumerate(notes):
            events += _varint(duration if offset == 0 else 0) + bytes([0x80, note, 0])

    events += _varint(0) + b"\xFF\x2F\x00"

    track = b"MTrk" + struct.pack(">I", len(events)) + bytes(events)
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, TICKS_PER_BEAT)
    return header + track


def write(path: str, voicings, **kwargs) -> None:
    with open(path, "wb") as handle:
        handle.write(to_bytes(voicings, **kwargs))
