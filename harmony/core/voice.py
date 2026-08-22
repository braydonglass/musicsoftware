"""The four-voice chord, kept in its own module so rules and the voicing
generator can both import it without a cycle."""

from __future__ import annotations

from dataclasses import dataclass

from .pitch import Pitch

VOICE_NAMES = ("soprano", "alto", "tenor", "bass")

# Adjacent pairs, high to low. Spacing and overlap care about these.
ADJACENT_PAIRS = (("soprano", "alto"), ("alto", "tenor"), ("tenor", "bass"))

# All six pairs. Parallel motion cares about every one.
ALL_PAIRS = (
    ("soprano", "alto"), ("soprano", "tenor"), ("soprano", "bass"),
    ("alto", "tenor"), ("alto", "bass"), ("tenor", "bass"),
)

OUTER_PAIR = ("soprano", "bass")


@dataclass(frozen=True)
class Voicing:
    soprano: Pitch
    alto: Pitch
    tenor: Pitch
    bass: Pitch

    def __getitem__(self, name: str) -> Pitch:
        return getattr(self, name)

    @property
    def pitches(self) -> tuple[Pitch, Pitch, Pitch, Pitch]:
        """High to low, matching VOICE_NAMES."""
        return (self.soprano, self.alto, self.tenor, self.bass)

    def chromas(self) -> list[int]:
        return [p.pitch_class.chroma for p in self.pitches]

    def __str__(self) -> str:
        return " ".join(f"{n[0].upper()}:{p}" for n, p in zip(VOICE_NAMES, self.pitches))

    __repr__ = __str__
