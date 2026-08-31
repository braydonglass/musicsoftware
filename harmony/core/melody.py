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


# Where each chord likes to go next, and how much it likes it. Not a rule -
# nothing here refuses anything - just the ordinary pull of functional
# harmony, used to choose between chords that can all carry the same note.
GOES_TO = {
    "I":     {"IV": 3, "V": 3, "vi": 3, "ii": 3, "iii": 2, "I6": 1, "V6": 2, "vii°6": 1},
    "I6":    {"IV": 3, "ii": 3, "V": 3, "vi": 2, "I": 1},
    "ii":    {"V": 4, "V7": 4, "V65": 3, "vii°6": 2, "I6": 1},
    "ii6":   {"V": 4, "V7": 4, "V65": 3, "I6": 1},
    "iii":   {"vi": 3, "IV": 3, "ii": 2, "I6": 1},
    "IV":    {"V": 4, "I": 3, "ii": 2, "V7": 3, "I6": 2, "vii°6": 1},
    "IV6":   {"V": 3, "I": 2},
    "V":     {"I": 4, "vi": 2, "I6": 1},
    "V6":    {"I": 4},
    "V7":    {"I": 4, "vi": 1},
    "V65":   {"I": 4},
    "V43":   {"I6": 3, "I": 2},
    "vi":    {"ii": 3, "IV": 3, "V": 2, "iii": 1},
    "vi6":   {"ii": 2, "V": 2},
    "vii°6": {"I": 4, "I6": 3},
    "N6":    {"V": 4, "V7": 3},
    "i":     {"iv": 3, "V": 3, "VI": 3, "ii°6": 3, "III": 2, "i6": 1, "V6": 2,
              "vii°6": 1, "vii°7": 2},
    "i6":    {"iv": 3, "ii°6": 3, "V": 3, "VI": 2, "i": 1},
    "ii°6":  {"V": 4, "V7": 4, "V65": 3, "i6": 1},
    "III":   {"VI": 3, "iv": 3, "ii°6": 2, "i6": 1},
    "iv":    {"V": 4, "i": 3, "V7": 3, "i6": 2, "N6": 3, "vii°7": 2},
    "iv6":   {"V": 3, "i": 2},
    "VI":    {"ii°6": 3, "iv": 3, "V": 2, "III": 1, "N6": 2},
    "vii°7": {"i": 4, "i6": 3},
}
TONIC = {"major": ("I", "I6"), "minor": ("i", "i6")}
DOMINANT = ("V", "V6", "V7", "V65", "vii°6", "vii°7")
BEAM = 40


def suggest(options: list[list[str]], key: Key) -> list[str]:
    """Choose one chord per note, reading the melody as a phrase.

    Picking each note's first workable chord independently is what produces
    i i ii°6 i i ii°6 i ii°6: every chord carries its note and the line as a
    whole goes nowhere, and often will not realize at all, because whether
    two chords can be connected is not a fact about either of them alone.

    So the choice is made across the phrase with a beam search - open on the
    tonic, follow the ordinary pull of one chord toward the next, cadence at
    the end, and do not sit on one chord for three beats together. No rule
    is consulted and nothing is refused here; this only decides between
    chords that can all carry the same note. The solver still has the final
    word, and still says so when it cannot connect them.
    """
    if not options or any(not choices for choices in options):
        return [choices[0] if choices else "" for choices in options]
    root, first_inversion = TONIC[key.mode]
    beam = [([c], 10 if c == root else 6 if c == first_inversion else 0)
            for c in options[0]]
    for position in range(1, len(options)):
        last = position == len(options) - 1
        reachable = any(c in TONIC[key.mode] for c in options[position])
        nxt = []
        for sequence, score in beam:
            for chord in options[position]:
                value = score + GOES_TO.get(sequence[-1], {}).get(chord, 0)
                if chord == sequence[-1]:
                    value -= 1
                    if len(sequence) > 1 and sequence[-2] == chord:
                        value -= 4
                if "\u00b0" in chord:
                    # A diminished chord is every-note-a-tendency-tone, which
                    # leaves the fewest ways in and out of it: chosen as a
                    # default it is the one most likely to be a chord the
                    # solver then cannot connect. Wanted where the melody
                    # asks for it, not where anything else would do.
                    value -= 3
                if last:
                    if reachable and chord in TONIC[key.mode]:
                        value += 8
                        if chord == root:
                            value += 4
                        if sequence[-1] in DOMINANT:
                            value += 8
                    elif not reachable and chord in ("V", "V6", "V7"):
                        # the tune ends where no tonic reaches, so the phrase
                        # is asking for a half cadence
                        value += 10
                        if chord == "V":
                            value += 4
                nxt.append((sequence + [chord], value))
        nxt.sort(key=lambda pair: -pair[1])
        beam = nxt[:BEAM]
    return beam[0][0]


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
