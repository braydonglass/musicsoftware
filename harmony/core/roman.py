"""Roman numeral token -> abstract chord specification.

The seventh and the leading tone are tagged here, at parse time, which is
what lets rules 4a, 8 and 9 be lookups instead of re-deriving harmonic
function from a pile of pitches.

Scope: diatonic triads and sevenths in all inversions, fully and half
diminished sevenths, secondary dominants of any degree, and the Italian,
French and German augmented sixths.

Still absent: modal mixture beyond what an explicit quality mark asks for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .key import Key
from .pitch import LETTER_SEMITONES, PitchClass

ROMAN_TO_DEGREE = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7}

TRIAD_STRUCTURES = {
    "major":      (4, 7),
    "minor":      (3, 7),
    "diminished": (3, 6),
    "augmented":  (4, 8),
}

TRIAD_FIGURES = {"": 0, "6": 1, "64": 2}
SEVENTH_FIGURES = {"7": 0, "65": 1, "43": 2, "42": 3, "2": 3}

# 65|64|43|42|2|7|6 - longest figures first so "V65" is not read as "V6"
_TOKEN_RE = re.compile(
    r"^(?P<flat>\u266d|b)?(?P<numeral>[IViv]+)(?P<mark>°|o|\+|ø)?"
    r"(?P<figure>65|64|43|42|2|7|6)?$"
)


class RomanNumeralError(ValueError):
    """Raised for tokens this version cannot read or will not accept."""


@dataclass
class ChordSpec:
    pitch_classes: list[PitchClass]        # spelled, root-position order
    bass_pc: PitchClass                    # determined by the inversion
    root_pc: PitchClass
    seventh_pc: PitchClass | None
    leading_tone_pc: PitchClass | None
    figure: str
    numeral: str                           # the original token, for messages
    degree: int = 0
    quality: str = ""
    has_dominant_function: bool = False
    inversion: int = 0
    # Where a leading tone resolves. The key's tonic for a plain dominant, the
    # tonicized root for a secondary one.
    resolution_root_pc: PitchClass | None = None
    tonicized_degree: int | None = None
    # Augmented sixths: "italian" | "french" | "german", plus the two tones
    # forming the augmented sixth itself, which must expand outward to an octave.
    aug6_type: str | None = None
    aug6_lower_pc: PitchClass | None = None
    aug6_upper_pc: PitchClass | None = None

    @property
    def tendency_tones(self) -> list[PitchClass]:
        """Tones owing a resolution, and therefore never to be doubled."""
        out = []
        for pc in (self.leading_tone_pc, self.seventh_pc,
                   self.aug6_lower_pc, self.aug6_upper_pc):
            if pc is not None and pc not in out:
                out.append(pc)
        return out

    @property
    def chroma_set(self) -> set[int]:
        return {pc.chroma for pc in self.pitch_classes}

    @property
    def symbol(self) -> str:
        """The chord as a player would name it: C, Am, G7/B, F#dim.

        A Roman numeral says what a chord *does* in its key; a chord symbol
        says what it *is*. They are two readings of the same sonority and a
        student needs both - V65 in C and G7/B are the same four notes, and
        the numeral is the half that stops meaning anything the moment the
        key changes.

        Only the numeral is returned for an augmented sixth. It is not built
        in thirds, so it has no root to name it after: writing it as a
        dominant seventh on the flat sixth would say something false about a
        chord whose whole identity is the interval it is named for.
        """
        if self.aug6_type is not None:
            return self.numeral
        root = str(self.root_pc)
        third = self.pitch_classes[1] if len(self.pitch_classes) > 1 else None
        fifth = self.pitch_classes[2] if len(self.pitch_classes) > 2 else None
        semis = lambda pc: (pc.chroma - self.root_pc.chroma) % 12
        minor_third = third is not None and semis(third) == 3
        flat_fifth = fifth is not None and semis(fifth) == 6
        sharp_fifth = fifth is not None and semis(fifth) == 8

        if self.seventh_pc is None:
            quality = ("dim" if minor_third and flat_fifth else
                       "aug" if not minor_third and sharp_fifth else
                       "m" if minor_third else "")
        else:
            seventh = semis(self.seventh_pc)
            if minor_third and flat_fifth:
                quality = "dim7" if seventh == 9 else "m7b5"
            elif minor_third:
                quality = "m7" if seventh == 10 else "mMaj7"
            else:
                quality = "7" if seventh == 10 else "maj7"

        name = root + quality
        if self.bass_pc.chroma != self.root_pc.chroma:
            name += "/" + str(self.bass_pc)
        return name

    def __str__(self) -> str:
        return f"{self.numeral} [{' '.join(str(pc) for pc in self.pitch_classes)}]"


def _build_tone(root: PitchClass, generic_offset: int, semitones: int) -> PitchClass:
    """Stack a tone on the root: letter from the generic step, alteration to fit."""
    ladder = root.letter + generic_offset
    letter = ladder % 7
    letter_chroma = LETTER_SEMITONES[letter] + 12 * (ladder // 7)
    root_chroma = LETTER_SEMITONES[root.letter] + root.alteration
    return PitchClass(letter, (root_chroma + semitones) - letter_chroma)


def _reject_chromatic_tones(tones, key: Key, degree: int, token: str) -> None:
    """Refuse chords that need notes outside the key.

    The token's case asserts a quality, and an asserted quality can demand a
    tone the key does not contain: bare ``vii`` in C major means a minor
    triad, which is B D F#, and ``ii`` in C minor means D F A against a
    diatonic A-flat. Both are chromatic, and v1 covers no chromaticism.

    The one sanctioned exception is minor's raised seventh, which dominant
    function requires - that is why V in C minor may spell a B natural.
    """
    letter_to_degree = {key.scale_degree(n).letter: n for n in range(1, 8)}

    for pc in tones:
        n = letter_to_degree[pc.letter]
        permitted = {key.scale_degree(n)}
        if key.mode == "minor" and n == 7 and degree in (5, 7):
            permitted.add(key.scale_degree(7, raised=True))
        if pc not in permitted:
            expected = " or ".join(sorted(str(p) for p in permitted))
            raise RomanNumeralError(
                f"{token!r} in {key} would need {pc}, but scale degree {n} of "
                f"{key} is {expected}. v1 covers diatonic chords only - no "
                f"secondary dominants, borrowed chords or applied leading tones. "
                f"Did you mean a different quality, as in vii° rather than vii?"
            )


def parse(token: str, key: Key) -> ChordSpec:
    """Read one Roman numeral token in a key."""
    text = token.strip()
    aug6 = _AUG6_RE.match(text)
    if aug6:
        return _parse_augmented_sixth(text, aug6, key)
    neapolitan = _NEAPOLITAN_RE.match(text)
    if neapolitan:
        return _parse_neapolitan(text, neapolitan, key)
    if "/" in text:
        return _parse_secondary(text, key)
    return _parse_simple(text, key)


def _parse_simple(token: str, key: Key, allow_chromatic: bool = False) -> ChordSpec:
    text = token.strip().replace("o", "°") if token.strip() not in ("", None) else token
    match = _TOKEN_RE.match(text)
    if not match:
        raise RomanNumeralError(
            f"cannot read {token!r} as a Roman numeral; expected something like "
            f"I, ii, V7, V65, vii°6 or viiø7"
        )

    numeral = match.group("numeral")
    mark = match.group("mark") or ""
    figure = match.group("figure") or ""
    flat = bool(match.group("flat"))

    upper = numeral.upper()
    if upper not in ROMAN_TO_DEGREE:
        raise RomanNumeralError(
            f"{token!r} uses {numeral!r}, which is not a Roman numeral I-VII"
        )
    degree = ROMAN_TO_DEGREE[upper]
    is_upper = numeral == upper

    is_seventh = figure in SEVENTH_FIGURES
    if figure and not is_seventh and figure not in TRIAD_FIGURES:
        raise RomanNumeralError(f"{token!r} carries an unknown figure {figure!r}")

    # Quality from case and mark.
    if mark == "+":
        quality = "augmented"
    elif mark in ("°", "ø"):
        quality = "diminished"
    elif is_upper:
        quality = "major"
    else:
        quality = "minor"

    if mark == "ø" and not is_seventh:
        raise RomanNumeralError(f"{token!r}: the half-diminished mark needs a seventh figure")
    if mark in ("°", "ø") and is_upper:
        raise RomanNumeralError(
            f"{token!r}: diminished chords take a lowercase numeral, as in vii°"
        )

    # Minor raises its seventh degree for dominant-function chords only. A
    # lowercase vii is one; an uppercase VII is the natural-seventh chord.
    raise_seventh = key.mode == "minor" and degree == 7 and not is_upper
    root_pc = key.scale_degree(degree, raised=raise_seventh)

    if flat:
        # Borrowed from the parallel mode. The root drops a semitone and keeps
        # its letter: the sixth degree of C is A, so its borrowed form is
        # A-flat and never G-sharp. Deriving the letter from the new chroma
        # instead is exactly the mistake spelled pitch exists to prevent.
        if key.mode == "minor" and degree in (3, 6, 7):
            raise RomanNumeralError(
                f"{token!r}: scale degree {degree} of {key} is already lowered, "
                f"so flattening it again would ask for a double flat. In a minor "
                f"key write {numeral} on its own."
            )
        if root_pc.alteration - 1 < -2:
            raise RomanNumeralError(
                f"{token!r} would need a triple flat in {key}"
            )
        root_pc = PitchClass(root_pc.letter, root_pc.alteration - 1)

    third_semitones, fifth_semitones = TRIAD_STRUCTURES[quality]
    tones = [
        root_pc,
        _build_tone(root_pc, 2, third_semitones),
        _build_tone(root_pc, 4, fifth_semitones),
    ]

    seventh_pc = None
    if is_seventh:
        if mark == "°":
            seventh_semitones = 9            # fully diminished
        elif mark == "ø":
            seventh_semitones = 10           # half diminished
        else:
            # Diatonic: whatever the scale puts a seventh above this root.
            seventh_degree = (degree + 5) % 7 + 1
            seventh_raised = key.mode == "minor" and seventh_degree == 7 and not is_upper
            diatonic = key.scale_degree(seventh_degree, raised=seventh_raised)
            root_chroma = LETTER_SEMITONES[root_pc.letter] + root_pc.alteration
            seventh_semitones = (diatonic.chroma - root_chroma) % 12
        seventh_pc = _build_tone(root_pc, 6, seventh_semitones)
        tones.append(seventh_pc)

    if is_seventh:
        inversion = SEVENTH_FIGURES[figure]
    else:
        inversion = TRIAD_FIGURES.get(figure, 0)

    # The cadential six-four is a dominant-function chord wearing tonic
    # clothing. Treating it as a stable tonic breaks the resolution rules
    # downstream, and grading it properly needs a strong-beat test that the
    # meter is deliberately kept away from. The spec permits refusing it in
    # v1 rather than getting it quietly wrong, so it is refused.
    if degree == 1 and figure == "64":
        raise RomanNumeralError(
            f"{token!r}: the cadential six-four is not supported in v1. It is a "
            f"dominant-function chord, not a stable tonic, and grading it needs "
            f"the strong-beat test that meter is intentionally kept out of the "
            f"rule engine. Write the dominant it decorates instead."
        )

    # The guard exists to catch quality typed by accident - bare "vii" meaning
    # a minor triad, "ii" in minor meaning a major-sixth chord. An explicit
    # mark is the writer being deliberate, and deliberate chords are allowed
    # their chromatic tones: a fully diminished seventh in a major key borrows
    # the flat sixth by definition, so vii°7 in C major must spell A-flat.
    # A quality mark and a flat are both explicit requests for a tone outside
    # the key, so neither is asked to justify itself to the diatonic check.
    if not allow_chromatic and not mark and not flat:
        _reject_chromatic_tones(tones, key, degree, token)

    leading_tone_pc = next((pc for pc in tones if pc == key.leading_tone), None)

    return ChordSpec(
        pitch_classes=tones,
        bass_pc=tones[inversion],
        root_pc=root_pc,
        seventh_pc=seventh_pc,
        leading_tone_pc=leading_tone_pc,
        figure=figure,
        numeral=token.strip(),
        degree=degree,
        quality=quality,
        has_dominant_function=degree in (5, 7),
        inversion=inversion,
        resolution_root_pc=key.tonic if degree in (5, 7) else None,
    )


AUG6_STRUCTURES = {
    # semitones above the tonic for each member, bass first
    "italian": (8, 0, 6),          # b6, 1, #4
    "french":  (8, 0, 2, 6),       # b6, 1, 2, #4
    "german":  (8, 0, 3, 6),       # b6, 1, b3, #4
}
AUG6_DEGREES = {
    "italian": (6, 1, 4),
    "french":  (6, 1, 2, 4),
    "german":  (6, 1, 3, 4),
}
_AUG6_NAMES = {"it": "italian", "italian": "italian",
               "ger": "german", "german": "german",
               "fr": "french", "french": "french"}
_AUG6_RE = re.compile(r"^(it|ger|fr|italian|german|french)\s*(?:\+?\s*6|65|43|63)?$", re.I)

# "N" alone means the Neapolitan sixth, which is how it nearly always appears.
# Root position has to be asked for explicitly, as bII.
_NEAPOLITAN_RE = re.compile(r"^(?:N|bII|\u266dII)\s*(6)?$", re.I)


def _parse_neapolitan(token: str, match, key: Key) -> ChordSpec:
    """A major triad on the lowered second degree, usually in first inversion.

    In C the root is D-flat, never C-sharp: it is the second degree, so it
    owns the letter D whatever the accidental. That spelling is what makes
    its fall to the leading tone read as the diminished third it is.
    """
    root = key.degree_at_chroma(2, 1)
    tones = [root, _build_tone(root, 2, 4), _build_tone(root, 4, 7)]

    explicit_root_position = token.strip().lower().lstrip("\u266d").startswith("b") \
        and not match.group(1)
    inversion = 0 if explicit_root_position else 1

    return ChordSpec(
        pitch_classes=tones,
        bass_pc=tones[inversion],
        root_pc=root,
        seventh_pc=None,
        leading_tone_pc=None,
        figure="6" if inversion else "",
        numeral=token.strip(),
        degree=2,
        quality="Neapolitan",
        has_dominant_function=False,
        inversion=inversion,
    )


def _parse_augmented_sixth(token: str, match, key: Key) -> ChordSpec:
    """Italian, French and German sixths.

    All three are built on the lowered sixth degree and all three contain the
    augmented sixth between b6 and #4, which is the whole point of the chord:
    it expands outward by semitone to an octave on scale degree 5. They differ
    only in the tone filling the middle.
    """
    kind = _AUG6_NAMES[match.group(1).lower()]
    degrees = AUG6_DEGREES[kind]
    offsets = AUG6_STRUCTURES[kind]
    tones = [key.degree_at_chroma(d, off) for d, off in zip(degrees, offsets)]

    return ChordSpec(
        pitch_classes=tones,
        bass_pc=tones[0],
        root_pc=tones[0],
        seventh_pc=None,
        leading_tone_pc=None,
        figure="+6",
        numeral=token.strip(),
        degree=6,
        quality=f"{kind} augmented sixth",
        has_dominant_function=False,
        inversion=0,
        aug6_type=kind,
        aug6_lower_pc=tones[0],     # b6, falls to 5
        aug6_upper_pc=tones[-1],    # #4, rises to 5
    )


def _parse_secondary(token: str, key: Key) -> ChordSpec:
    """V/V, V7/ii, vii°7/V and friends.

    Built by standing in the tonicized key for a moment. The applied chord is
    parsed there, which gets its spelling and its leading tone right for free,
    then re-tagged so the resolution rules know the leading tone is aimed at
    the tonicized root rather than at the home tonic.
    """
    left, _, right = token.partition("/")
    left, right = left.strip(), right.strip()
    if not left or not right:
        raise RomanNumeralError(
            f"{token!r}: a secondary chord needs both halves, as in V/V or vii°7/ii"
        )

    # The target is only consulted for its root, so chromatic quality clashes
    # in the target token do not matter here.
    target = _parse_simple(right, key, allow_chromatic=True)
    tonicized = Key(target.root_pc.letter, target.root_pc.alteration, "major")

    inner = _parse_simple(left, tonicized, allow_chromatic=False)
    if not inner.has_dominant_function:
        raise RomanNumeralError(
            f"{token!r}: only dominant-function chords can be applied. Use V, V7, "
            f"vii°, vii°7 or viiø7 before the slash."
        )
    if target.degree == 1:
        raise RomanNumeralError(
            f"{token!r}: applying a dominant to scale degree 1 is just the plain "
            f"dominant. Write {left} on its own."
        )

    inner.numeral = token.strip()
    inner.tonicized_degree = target.degree
    inner.resolution_root_pc = target.root_pc
    return inner


def parse_progression(tokens: str | list[str], key: Key) -> list[ChordSpec]:
    if isinstance(tokens, str):
        tokens = tokens.split()
    if not tokens:
        raise RomanNumeralError("the progression is empty")
    return [parse(token, key) for token in tokens]
