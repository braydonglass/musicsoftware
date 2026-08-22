"""Harmonizing a given soprano.

Two jobs. Which chords could carry a particular melody note, and - once
chosen - filling in the three voices underneath without moving the melody.

A candidate is only offered if at least one legal voicing of it actually
puts that note in the soprano. Containing the pitch class is not enough:
the note may lie outside the soprano range, or the only voicings that reach
it may double a tendency tone.
"""

from __future__ import annotations

from .key import Key
from .pitch import Pitch
from .roman import ChordSpec, RomanNumeralError, parse
from .rules.registry import Profile
from .voicing import generate

# A teaching vocabulary: the chords a first harmonization exercise draws on.
# Anything else can still be typed into the progression directly.
MAJOR_VOCABULARY = [
    "I", "I6", "ii", "ii6", "iii", "IV", "IV6",
    "V", "V6", "V7", "V65", "V43", "vi", "vi6", "vii°6", "N6",
]
MINOR_VOCABULARY = [
    "i", "i6", "ii°6", "III", "iv", "iv6",
    "V", "V6", "V7", "V65", "V43", "VI", "vii°6", "vii°7", "N6",
]


def vocabulary_for(key: Key) -> list[str]:
    return MAJOR_VOCABULARY if key.mode == "major" else MINOR_VOCABULARY


def candidates_for(
    soprano: Pitch,
    key: Key,
    profile: Profile,
    vocabulary: list[str] | None = None,
) -> list[dict]:
    """Every chord that can carry this note in the soprano, with its spelling."""
    out = []
    for token in vocabulary or vocabulary_for(key):
        try:
            spec = parse(token, key)
        except (RomanNumeralError, ValueError):
            continue
        if soprano.pitch_class.chroma not in spec.chroma_set:
            continue
        if not generate(spec, key, profile, soprano=soprano):
            continue
        out.append({
            "numeral": token,
            "spelling": [str(pc) for pc in spec.pitch_classes],
            "bass": str(spec.bass_pc),
            "function": _function_of(spec),
        })
    return out


def _function_of(spec: ChordSpec) -> str:
    if spec.aug6_type or spec.has_dominant_function:
        return "dominant"
    if spec.degree in (2, 4):
        return "predominant"
    if spec.degree in (1, 3, 6):
        return "tonic"
    return "other"


def parse_soprano(text: str) -> list[Pitch]:
    tokens = text.split()
    if not tokens:
        raise ValueError("the melody is empty")
    return [Pitch.parse(token) for token in tokens]
