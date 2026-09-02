"""Keys, scale degrees, and the two predicates the doubling rules need.

Minor is modelled as one scale with a raised seventh applied per chord,
not as three separate scales. Which chords raise it is decided in
``roman.py``, where the numeral is known; this module only offers the
choice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .pitch import LETTER_NAMES, LETTER_SEMITONES, Pitch, PitchClass

MAJOR_OFFSETS = [0, 2, 4, 5, 7, 9, 11]
NATURAL_MINOR_OFFSETS = [0, 2, 3, 5, 7, 8, 10]
RAISED_SEVENTH_OFFSET = 11

_KEY_RE = re.compile(r"^([A-Ga-g])([#b♯♭]*)\s+(major|minor)$", re.IGNORECASE)


@dataclass(frozen=True)
class Key:
    tonic_letter: int
    tonic_alteration: int
    mode: str   # "major" | "minor"

    @classmethod
    def parse(cls, text: str) -> "Key":
        match = _KEY_RE.match(text.strip())
        if not match:
            raise ValueError(
                f"cannot read {text!r} as a key; expected something like "
                f"'C major', 'f# minor' or 'Eb major'"
            )
        name, symbols, mode = match.groups()
        alteration = symbols.count("#") + symbols.count("♯") \
            - symbols.count("b") - symbols.count("♭")
        return cls(LETTER_NAMES.index(name.upper()), alteration, mode.lower())

    @property
    def tonic(self) -> PitchClass:
        return PitchClass(self.tonic_letter, self.tonic_alteration)

    def degree_at_chroma(self, degree: int, semitones_above_tonic: int) -> PitchClass:
        """A scale degree's letter, spelled to sit a given distance above the tonic.

        This is what chromatic alteration needs: the flat sixth of C is A-flat
        because the sixth degree owns the letter A, whatever the accidental.
        Augmented sixth chords are built entirely out of this.
        """
        if not 1 <= degree <= 7:
            raise ValueError(f"scale degree must be 1-7, got {degree}")
        tonic_chroma = LETTER_SEMITONES[self.tonic_letter] + self.tonic_alteration
        ladder = self.tonic_letter + degree - 1
        letter = ladder % 7
        letter_chroma = LETTER_SEMITONES[letter] + 12 * (ladder // 7)
        return PitchClass(letter, (tonic_chroma + semitones_above_tonic) - letter_chroma)

    def scale_degree(self, degree: int, raised: bool = False) -> PitchClass:
        """The spelled pitch class of a scale degree.

        G major gives F#, never Gb. Eb major gives Ab, never G#. The letter
        is fixed by counting up the alphabet from the tonic; the alteration
        is then whatever reaches the right chroma.
        """
        if not 1 <= degree <= 7:
            raise ValueError(f"scale degree must be 1-7, got {degree}")

        offsets = MAJOR_OFFSETS if self.mode == "major" else NATURAL_MINOR_OFFSETS
        offset = offsets[degree - 1]
        if raised and self.mode == "minor" and degree == 7:
            offset = RAISED_SEVENTH_OFFSET

        return self.degree_at_chroma(degree, offset)

    @property
    def leading_tone(self) -> PitchClass:
        """Scale degree 7, raised in minor. The tone rules 4a and 8 care about."""
        return self.scale_degree(7, raised=(self.mode == "minor"))

    @lru_cache(maxsize=None)
    def signature(self) -> dict[int, int]:
        """Letter -> alteration, as the key signature spells it.

        Minor uses the natural form, so the raised seventh reads as an
        accidental rather than as part of the key. Cached: is_altered()
        calls this once per pitch class checked, from inside the solver's
        innermost voicing loop, and it is invariant for a given Key.
        """
        return {
            self.scale_degree(n).letter: self.scale_degree(n).alteration
            for n in range(1, 8)
        }

    def is_leading_tone(self, pitch: Pitch | PitchClass) -> bool:
        pc = pitch.pitch_class if isinstance(pitch, Pitch) else pitch
        return pc == self.leading_tone

    def is_altered(self, pitch: Pitch | PitchClass) -> bool:
        """True when the pitch is chromatically inflected against the signature."""
        pc = pitch.pitch_class if isinstance(pitch, Pitch) else pitch
        return pc.alteration != self.signature()[pc.letter]

    def __str__(self) -> str:
        return f"{self.tonic} {self.mode}"

    __repr__ = __str__
