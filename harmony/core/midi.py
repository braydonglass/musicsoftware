"""Standard MIDI file output.

Shared by the CLI and the web layer so there is only one encoder. A type-0
file with a tempo and a time signature.

This is the one place meter is legitimately used: it is written into the
file's time signature, which is a notation fact, not a rule.

The encoder takes either a plain list of voicings, one per beat, or the
event list a decorated realization produces, where a beat may be split. It
schedules per voice rather than per chord, because a voice holding through
a split beat must sound once - striking it again turns every decorated
chord into a pair of block eighth notes.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .voice import VOICE_NAMES, Voicing

TICKS_PER_BEAT = 480


def _varint(value: int) -> bytes:
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(out)


@dataclass(frozen=True)
class _Beat:
    """A whole-beat chord, so undecorated input takes the same path."""

    voicing: Voicing
    beats: float
    chord: int


def _as_events(items, beats_per_chord: int):
    if items and hasattr(items[0], "voicing"):
        return list(items)
    return [_Beat(v, float(beats_per_chord), i) for i, v in enumerate(items)]


def timeline(events) -> list[tuple[float, float, int]]:
    """When each voice's notes start and stop, measured in beats.

    Two rules, and the difference between them is the whole point. A voice
    holding its pitch across a split beat sounds once: nothing happened to
    it, and re-striking it would articulate a note the writer did not
    write. A voice repeating its pitch under the *next* chord is struck
    again: the harmony beneath it changed, so it is sung again rather than
    tied over.
    """
    out: list[tuple[float, float, int]] = []
    for name in VOICE_NAMES:
        note: int | None = None
        start = at = 0.0
        chord = None
        for event in events:
            pitch = event.voicing[name].midi
            if note is not None and (pitch != note or event.chord != chord):
                out.append((start, at, note))
                note = None
            if note is None:
                note, start, chord = pitch, at, event.chord
            at += event.beats
        if note is not None:
            out.append((start, at, note))
    return out


def to_bytes(
    items,
    tempo_bpm: float = 84.0,
    beats_per_chord: int = 1,
    meter: tuple[int, int] = (4, 4),
    velocity: int = 72,
) -> bytes:
    """Encode a realization - decorated or not - as a type-0 MIDI file."""
    if not len(items):
        raise ValueError("nothing to write")
    tempo_bpm = max(20.0, min(float(tempo_bpm), 400.0))
    events = _as_events(items, beats_per_chord)

    out = bytearray()

    # tempo, in microseconds per quarter note
    micros = int(round(60_000_000 / tempo_bpm))
    out += _varint(0) + b"\xFF\x51\x03" + micros.to_bytes(3, "big")

    # time signature: numerator, log2(denominator), clocks per click, 32nds per quarter
    numerator, denominator = meter
    power = max(0, denominator.bit_length() - 1)
    out += _varint(0) + b"\xFF\x58\x04" + bytes([numerator, power, 24, 8])

    # Note-offs sort before note-ons at the same tick, and pitches ascend
    # within each. Nothing depends on that order musically; it is fixed so
    # the bytes are reproducible.
    scheduled: list[tuple[int, int, int]] = []
    for start, end, note in timeline(events):
        scheduled.append((int(round(start * TICKS_PER_BEAT)), 1, note))
        scheduled.append((int(round(end * TICKS_PER_BEAT)), 0, note))
    scheduled.sort()

    previous = 0
    for tick, kind, note in scheduled:
        out += _varint(tick - previous)
        out += bytes([0x90 if kind else 0x80, note, velocity if kind else 0])
        previous = tick

    out += _varint(0) + b"\xFF\x2F\x00"

    track = b"MTrk" + struct.pack(">I", len(out)) + bytes(out)
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, TICKS_PER_BEAT)
    return header + track


def write(path: str, items, **kwargs) -> None:
    with open(path, "wb") as handle:
        handle.write(to_bytes(items, **kwargs))
