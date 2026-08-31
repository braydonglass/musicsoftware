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


# What a writer types where the engine may choose the note itself.
HOLE = "_"


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


def transpose(melody: list[Pitch | None], from_key: Key, to_key: Key,
              low: Pitch | None = None, high: Pitch | None = None
              ) -> list[Pitch | None]:
    """The same tune on the same scale degrees of a different key.

    Solfege, not semitones. Mi in C major is E; mi in G major is B; and in C
    minor it is E-flat, because what is being kept is the degree and what
    spells it is the mode. Transposing by interval instead would carry C
    major's E straight into C minor and hand back a melody the key does not
    contain.

    An accidental keeps its distance from the scale rather than its letter,
    so a raised seventh stays a raised seventh: it is written against the new
    key's signature, not copied across from the old one's.

    The whole line then moves by octaves until it sits in the soprano's
    range. Degrees are preserved by octave, so this changes nothing about
    which notes they are - and if no octave fits, the untransposed octave is
    handed back rather than a silently mangled one, because a melody that
    cannot be sung in the new key is a fact for the caller to see.
    """
    from_sig, to_sig = from_key.signature(), to_key.signature()
    moved: list[Pitch | None] = []
    for pitch in melody:
        if pitch is None:
            moved.append(None)
            continue
        # distance from the tonic in letter-steps, which is the degree
        steps = pitch.diatonic_index - from_key.tonic.letter
        index = to_key.tonic.letter + steps
        letter = index % 7
        away = pitch.alteration - from_sig[pitch.letter]
        moved.append(Pitch(letter, index // 7, to_sig[letter] + away))

    if low is None or high is None:
        return moved
    real = [p for p in moved if p is not None]
    if not real:
        return moved
    for shift in (0, -1, 1, -2, 2):
        candidate = [None if p is None else Pitch(p.letter, p.octave + shift, p.alteration)
                     for p in moved]
        inside = [p for p in candidate if p is not None]
        if all(low.midi <= p.midi <= high.midi for p in inside):
            return candidate
    return moved


def parse_soprano(text: str) -> list[Pitch | None]:
    """Pitches, with ``_`` standing for a note the engine may choose.

    A hole is not a rest. The chord under it is realized as usual and all
    four voices sound; only the soprano is left free. This is what lets a
    melody be pinned in part, so adding a chord to a progression does not
    throw away the tune already chosen for the chords before it.
    """
    tokens = text.split()
    if not tokens:
        raise ValueError("the melody is empty")
    return [None if token == HOLE else Pitch.parse(token) for token in tokens]
