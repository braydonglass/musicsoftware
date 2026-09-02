"""Spelled pitch and two-sized intervals.

Everything else in the package rests on this module. Two commitments:

* A pitch stores a letter, an octave and an alteration. MIDI is derived.
  Storing MIDI collapses F# and Gb, and half the voice-leading rules exist
  precisely to tell those apart.
* An interval carries a generic size (letter distance) and a specific size
  (semitones). Quality is what you get by crossing them, which is how a
  legal d5 -> P5 is distinguished from illegal parallel fifths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LETTER_SEMITONES = [0, 2, 4, 5, 7, 9, 11]   # C D E F G A B
LETTER_NAMES = "CDEFGAB"

REFERENCE = {1: 0, 2: 2, 3: 4, 4: 5, 5: 7, 6: 9, 7: 11, 8: 12}
PERFECT_GENERICS = {1, 4, 5, 8}

_PITCH_RE = re.compile(r"^([A-Ga-g])([#b♯♭x]*)(-?\d+)$")


class UnspellableInterval(Exception):
    """Raised when a construction would need a triple sharp or flat."""


class UnknownQuality(Exception):
    """Raised when generic and specific sizes cross to nothing nameable."""


def _alteration_from_symbols(symbols: str) -> int:
    value = 0
    for ch in symbols:
        if ch in "#♯":
            value += 1
        elif ch in "b♭":
            value -= 1
        elif ch == "x":
            value += 2
    return value


def _alteration_to_symbols(alteration: int) -> str:
    if alteration > 0:
        return "#" * alteration
    if alteration < 0:
        return "b" * -alteration
    return ""


@dataclass(frozen=True, order=False)
class Pitch:
    letter: int       # 0-6, C=0
    octave: int       # scientific pitch notation, C4 is middle C
    alteration: int   # -2..+2

    @property
    def diatonic_index(self) -> int:
        """Position on an endless ladder of letter names. Drives generic size."""
        return self.letter + 7 * self.octave

    @property
    def midi(self) -> int:
        """Semitone position. Drives specific size and playback."""
        return LETTER_SEMITONES[self.letter] + self.alteration + 12 * (self.octave + 1)

    @classmethod
    def parse(cls, text: str) -> "Pitch":
        match = _PITCH_RE.match(text.strip())
        if not match:
            raise ValueError(
                f"cannot read {text!r} as a pitch; expected something like C4, F#4, Bb3 or C##5"
            )
        name, symbols, octave = match.groups()
        alteration = _alteration_from_symbols(symbols)
        if abs(alteration) > 2:
            raise ValueError(f"{text!r} carries more than a double alteration")
        return cls(LETTER_NAMES.index(name.upper()), int(octave), alteration)

    def __str__(self) -> str:
        return f"{LETTER_NAMES[self.letter]}{_alteration_to_symbols(self.alteration)}{self.octave}"

    __repr__ = __str__

    @property
    def pitch_class(self) -> "PitchClass":
        return PitchClass(self.letter, self.alteration)


@dataclass(frozen=True)
class PitchClass:
    """A spelled pitch class: a letter and an alteration, no octave."""

    letter: int
    alteration: int

    @property
    def chroma(self) -> int:
        return (LETTER_SEMITONES[self.letter] + self.alteration) % 12

    @classmethod
    def parse(cls, text: str) -> "PitchClass":
        match = re.match(r"^([A-Ga-g])([#b♯♭x]*)$", text.strip())
        if not match:
            raise ValueError(f"cannot read {text!r} as a pitch class")
        name, symbols = match.groups()
        return cls(LETTER_NAMES.index(name.upper()), _alteration_from_symbols(symbols))

    def at_octave(self, octave: int) -> Pitch:
        return Pitch(self.letter, octave, self.alteration)

    def __str__(self) -> str:
        return f"{LETTER_NAMES[self.letter]}{_alteration_to_symbols(self.alteration)}"

    __repr__ = __str__


@dataclass(frozen=True)
class Interval:
    generic: int    # 1 = unison, 2 = second, ... 8 = octave. Always >= 1.
    specific: int   # semitones

    def simplified(self) -> "Interval":
        generic, specific = self.generic, self.specific
        while generic > 8:
            generic -= 7
            specific -= 12
        return Interval(generic, specific)

    @property
    def deviation(self) -> int:
        """Semitones away from the major-or-perfect form.

        Never raises, unlike :meth:`quality`, so rules can ask "is this
        augmented?" without first needing the interval to have a name.
        """
        simple = self.simplified()
        return simple.specific - REFERENCE[simple.generic]

    @property
    def quality(self) -> str:
        simple = self.simplified()
        deviation = self.deviation
        if simple.generic in PERFECT_GENERICS:
            table = {-1: "diminished", 0: "perfect", 1: "augmented"}
        else:
            table = {-2: "diminished", -1: "minor", 0: "major", 1: "augmented"}
        if deviation not in table:
            raise UnknownQuality(
                f"generic {self.generic} with {self.specific} semitones is not a nameable quality"
            )
        return table[deviation]

    @property
    def abbreviation(self) -> str:
        letter = {"diminished": "d", "minor": "m", "perfect": "P",
                  "major": "M", "augmented": "A"}[self.quality]
        return f"{letter}{self.generic}"

    def __str__(self) -> str:
        try:
            return self.abbreviation
        except UnknownQuality:
            return f"<{self.generic}/{self.specific}>"

    __repr__ = __str__


def interval_between(a: Pitch, b: Pitch) -> Interval:
    """Measure low to high, whatever order the arguments arrive in.

    The diatonic_index tiebreak matters when two pitches share a MIDI
    number: without it C#4 against Db4 reads as a unison rather than the
    diminished second it is.
    """
    low, high = (a, b) if (a.midi, a.diatonic_index) <= (b.midi, b.diatonic_index) else (b, a)
    # The +1 is inclusive counting. C up to G touches five letter names and
    # is a fifth, even though the index difference is 4.
    return Interval(
        high.diatonic_index - low.diatonic_index + 1,
        high.midi - low.midi,
    )


def pitch_at_interval(pitch: Pitch, interval: Interval, direction: str) -> Pitch:
    """Build the spelling-correct pitch an interval away.

    The letter comes from the generic size; the alteration is then whatever
    is needed to reach the specific size. Reversing that order is what
    produces Gb where F# belongs.
    """
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', not {direction!r}")
    sign = 1 if direction == "up" else -1

    target_diatonic = pitch.diatonic_index + sign * (interval.generic - 1)
    # Floor division and floor modulo, deliberately: truncating division
    # would break every pitch below C0.
    letter = target_diatonic % 7
    octave = target_diatonic // 7

    target_midi = pitch.midi + sign * interval.specific
    alteration = target_midi - (LETTER_SEMITONES[letter] + 12 * (octave + 1))
    if abs(alteration) > 2:
        raise UnspellableInterval(
            f"{interval} {direction} from {pitch} would need an alteration of {alteration:+d}"
        )
    return Pitch(letter, octave, alteration)


def melodic_interval(a: Pitch, b: Pitch) -> tuple[Interval, int]:
    """Interval from a to b, paired with a direction: +1 up, -1 down, 0 static."""
    if a.midi == b.midi and a.diatonic_index == b.diatonic_index:
        return Interval(1, 0), 0
    direction = 1 if (b.midi, b.diatonic_index) > (a.midi, a.diatonic_index) else -1
    return interval_between(a, b), direction
