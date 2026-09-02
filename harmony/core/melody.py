"""Harmonizing a given soprano.

Two jobs. Which chords could carry a particular melody note, and - once
chosen - filling in the three voices underneath without moving the melody.

A candidate is only offered if at least one legal voicing of it actually
puts that note in the soprano. Containing the pitch class is not enough:
the note may lie outside the soprano range, or the only voicings that reach
it may double a tendency tone.
"""

from __future__ import annotations

import math

from .key import Key
from .pitch import Pitch
from .roman import ChordSpec, RomanNumeralError, parse
from .rules.registry import Profile, TransitionContext, evaluate_transition
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
    index: int | None = None,
    cache: dict | None = None,
) -> list[dict]:
    """Every chord that can carry this note in the soprano, with its spelling.

    index and cache are optional and exist for one caller: a melody-wide
    request that goes on to call workable()/suggest() for the same notes,
    where passing the same (index, cache) pair through all three means the
    generate() this already ran is reused rather than repeated. Called on
    its own - the CLI, or a single note with no position in a phrase -
    index is None and every call is independent, exactly as before.
    """
    out = []
    for token in vocabulary or vocabulary_for(key):
        try:
            spec = parse(token, key)
        except (RomanNumeralError, ValueError):
            continue
        if soprano.pitch_class.chroma not in spec.chroma_set:
            continue
        voicings = (_voicings(cache, index, token, spec, key, profile, soprano)
                    if cache is not None and index is not None
                    else generate(spec, key, profile, soprano=soprano))
        if not voicings:
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
#
# The dominant family is spelled the same in both modes and belongs to
# both, so it points at both tonics. Listing only the major one was a real
# mistake and not a cosmetic one: in a minor key V65 -> i then scored zero,
# nothing preferred it to V65 -> iv, and the search cheerfully chose a
# retrogression the solver could not connect. A key never mixes the two, so
# naming both targets costs nothing.
GOES_TO = {
    "I":     {"IV": 3, "V": 3, "vi": 3, "ii": 3, "iii": 2, "I6": 1, "V6": 2, "vii°6": 1},
    "I6":    {"IV": 3, "ii": 3, "V": 3, "vi": 2, "I": 1},
    "ii":    {"V": 4, "V7": 4, "V65": 3, "vii°6": 2, "I6": 1},
    "ii6":   {"V": 4, "V7": 4, "V65": 3, "I6": 1},
    "iii":   {"vi": 3, "IV": 3, "ii": 2, "I6": 1},
    "IV":    {"V": 4, "I": 3, "ii": 2, "V7": 3, "I6": 2, "vii°6": 1},
    "IV6":   {"V": 3, "I": 2},
    "V":     {"I": 4, "i": 4, "vi": 2, "VI": 2, "I6": 1, "i6": 1},
    "V6":    {"I": 4, "i": 4},
    "V7":    {"I": 4, "i": 4, "vi": 1, "VI": 1},
    "V65":   {"I": 4, "i": 4},
    "V43":   {"I6": 3, "i6": 3, "I": 2, "i": 2},
    "vi":    {"ii": 3, "IV": 3, "V": 2, "iii": 1},
    "vi6":   {"ii": 2, "V": 2},
    "vii°6": {"I": 4, "i": 4, "I6": 3, "i6": 3},
    "N6":    {"V": 4, "V7": 3, "V65": 3},
    "i":     {"iv": 3, "V": 3, "VI": 3, "ii°6": 3, "III": 2, "i6": 1, "V6": 2,
              "vii°6": 1, "vii°7": 2},
    "i6":    {"iv": 3, "ii°6": 3, "V": 3, "VI": 2, "i": 1},
    "ii°6":  {"V": 4, "V7": 4, "V65": 3, "i6": 1},
    "III":   {"VI": 3, "iv": 3, "ii°6": 2, "i6": 1},
    "iv":    {"V": 4, "i": 3, "V7": 3, "i6": 2, "N6": 3, "vii°7": 2},
    "iv6":   {"V": 3, "i": 2},
    "VI":    {"ii°6": 3, "iv": 3, "V": 2, "III": 1, "N6": 2},
    "vii°7": {"i": 4, "i6": 3, "I": 4, "I6": 3},
}
TONIC = {"major": ("I", "I6"), "minor": ("i", "i6")}
DOMINANT = ("V", "V6", "V7", "V65", "vii°6", "vii°7")
BEAM = 40


def _voicings(cache, index, token, spec, key, profile, note):
    """generate(), memoized on (index, token) for the life of one request.

    workable() and suggest() always run back to back on the same melody and
    ask this for the same (index, token) pairs - the melody note at a given
    index never changes between them - so the second call was pure waste
    without this. Keyed on index rather than the note itself because a hole
    substitutes the whole vocabulary in, and the token/spec pairing already
    determines everything generate() needs beyond the note.
    """
    key_ = (index, token)
    if key_ not in cache:
        cache[key_] = generate(spec, key, profile, soprano=note)
    return cache[key_]


def _layers(options, melody, key, profile, cache=None):
    """Every (chord, spec, voicing) the melody allows, note by note.

    A hole (melody[index] is None) has no note to constrain it, so
    options[index] is always empty there - that means "nothing was
    checked," not "nothing is possible." The vocabulary stands in instead,
    so a hole is a real link in the chain rather than a break in it.
    """
    if cache is None:
        cache = {}
    out = []
    for index, note in enumerate(melody):
        here = []
        tokens = options[index] if note is not None else vocabulary_for(key)
        for token in tokens:
            try:
                spec = parse(token, key)
            except (RomanNumeralError, ValueError):
                continue
            for voicing, _ in _voicings(cache, index, token, spec, key, profile, note):
                here.append((token, spec, voicing))
        out.append(here)
    return out


def _reaches(layers, key, profile, rules):
    """Trim to the voicings that lie on a complete path, or None if none do.

    Forward for what can be reached, backward for what can still reach the
    end. On a chain that is exact: a voicing survives precisely when some
    whole path runs through it.
    """
    def passes(index, left, right):
        ctx = TransitionContext(a=left[2], b=right[2], spec_a=left[1],
                                spec_b=right[1], key=key, index=index,
                                profile=profile)
        _, cost = evaluate_transition(ctx, rules)
        return not math.isinf(cost)

    if not layers or any(not layer for layer in layers):
        return None
    alive = [list(layers[0])]
    for index in range(1, len(layers)):
        previous = alive[-1]
        alive.append([n for n in layers[index]
                      if any(passes(index - 1, before, n) for before in previous)])
        if not alive[-1]:
            return None
    for index in range(len(alive) - 2, -1, -1):
        after = alive[index + 1]
        alive[index] = [n for n in alive[index]
                        if any(passes(index, n, later) for later in after)]
        if not alive[index]:
            return None
    return alive


def workable(options: list[list[str]], melody: list[Pitch | None],
             key: Key, profile: Profile, cache: dict | None = None) -> list[list[str]]:
    """Prune each note's chords to the ones that can actually be used.

    candidates_for answers whether a chord can carry a note. It cannot
    answer whether that chord can be reached from the one before it or left
    for the one after, because that is not a fact about either chord alone -
    so the list it returns contains chords that error the moment they are
    clicked.

    Asked of voicings rather than of chords, which is what makes it exact.
    Two chords having some legal pair between them is not enough: the
    voicing that lets a chord in from the left need not be one that lets it
    out to the right.

    What this does not promise, and cannot: that any *combination* of the
    survivors works. Each is on some complete path; picking one per note can
    still take a step off all of them. That is suggest()'s problem.
    """
    rules = profile.rules("transition")
    alive = _reaches(_layers(options, melody, key, profile, cache), key, profile, rules)
    if alive is None:
        return options
    kept = []
    for index, layer in enumerate(alive):
        survivors = {token for token, _, _ in layer}
        kept.append([c for c in options[index] if c in survivors] or options[index])
    return kept


def suggest(options: list[list[str]], key: Key,
            melody: list[Pitch | None] | None = None,
            profile: Profile | None = None,
            cache: dict | None = None) -> list[str]:
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
    # A hole has no note to constrain it, so options[index] is always empty
    # there - that means "nothing was checked", not "nothing fits". Search
    # the vocabulary instead, restricted to what can actually be voiced
    # unconstrained, so one hole does not collapse the whole phrase to the
    # naive per-note fallback below - which is exactly the degenerate
    # pattern this function exists to avoid.
    if cache is None:
        cache = {}
    if melody is not None and profile is not None:
        options = [
            choices if melody[index] is not None else
            [token for token in vocabulary_for(key)
             if _voicings(cache, index, token, parse(token, key), key, profile, None)]
            for index, choices in enumerate(options)
        ]

    if not options or any(not choices for choices in options):
        return [choices[0] if choices else "" for choices in options]

    # Which chord can follow which at all, worked out once before the search
    # rather than checked after it.
    #
    # Filtering afterwards does not work. The beam fills with high-scoring
    # lines that cannot be played and prunes away the ones that can: the
    # sequences that hold together for Twinkle in D minor sit on the tonic
    # for four beats, and the repetition penalty buries them long before
    # anything asks whether they are playable. A search that cannot see the
    # constraint optimises its way past the answer.
    cells, joinable, rules = {}, {}, None
    if melody is not None and profile is not None:
        rules = profile.rules("transition")
        for index, note in enumerate(melody):
            for token in options[index]:
                try:
                    spec = parse(token, key)
                except (RomanNumeralError, ValueError):
                    continue
                cells[(index, token)] = [(token, spec, v) for v, _
                                         in _voicings(cache, index, token, spec, key, profile, note)]
        for index in range(len(options) - 1):
            for left in options[index]:
                for right in options[index + 1]:
                    joinable[(index, left, right)] = any(
                        not math.isinf(evaluate_transition(
                            TransitionContext(a=x[2], b=y[2], spec_a=x[1],
                                              spec_b=y[1], key=key, index=index,
                                              profile=profile), rules)[1])
                        for x in cells.get((index, left), [])
                        for y in cells.get((index + 1, right), []))

    def can_follow(index, left, right):
        return joinable.get((index, left, right), True)

    def search(width):
        """The beam at a given width, best first."""
        root, first_inversion = TONIC[key.mode]
        beam = [([c], 10 if c == root else 6 if c == first_inversion else 0)
                for c in options[0]]
        for position in range(1, len(options)):
            last = position == len(options) - 1
            reachable = any(c in TONIC[key.mode] for c in options[position])
            nxt = []
            for sequence, score in beam:
                for chord in options[position]:
                    if not can_follow(position - 1, sequence[-1], chord):
                        continue
                    value = score + GOES_TO.get(sequence[-1], {}).get(chord, 0)
                    if chord == sequence[-1]:
                        value -= 1
                        if len(sequence) > 1 and sequence[-2] == chord:
                            value -= 4
                    if "\u00b0" in chord:
                        # Every note of a diminished chord is a tendency
                        # tone, so it has the fewest ways in and out and is
                        # the likeliest default the solver then refuses.
                        # Wanted where the melody asks for it, not where
                        # anything else would do.
                        value -= 3
                    if last:
                        if reachable and chord in TONIC[key.mode]:
                            value += 8
                            if chord == root:
                                value += 4
                            if sequence[-1] in DOMINANT:
                                value += 8
                        elif not reachable and chord in ("V", "V6", "V7"):
                            # the tune ends where no tonic reaches, so the
                            # phrase is asking for a half cadence
                            value += 10
                            if chord == "V":
                                value += 4
                    nxt.append((sequence + [chord], value))
            nxt.sort(key=lambda pair: -pair[1])
            if not nxt:
                # Nothing can follow anything here. Step without the
                # constraint rather than return nothing, and let the solver
                # name the fault.
                nxt = sorted([(seq + [c], sc) for seq, sc in beam
                              for c in options[position]], key=lambda pair: -pair[1])
            beam = nxt[:width]
        return beam

    if melody is None or profile is None:
        return search(BEAM)[0][0]

    # The best-scoring line whose chords can actually be joined.
    #
    # Pairwise feasibility gets most of the way there and is not the whole
    # story: a step that is legal on its own can still leave nowhere to go
    # three chords later. So each candidate is swept forward and backward
    # through the same trellis, which is exact and costs no search, and the
    # first that survives is the answer.
    #
    # Widening only when the narrow beam fails. Eleven notes of Lightly Row
    # in C minor need four hundred candidates before one holds together;
    # seven notes of Twinkle need none of that, and should not pay for it.
    best = None
    for width in (BEAM, BEAM * 10):
        beam = search(width)
        if best is None and beam:
            best = beam[0][0]
        for sequence, _ in beam:
            layers = [cells.get((index, token), [])
                      for index, token in enumerate(sequence)]
            if _reaches(layers, key, profile, rules) is not None:
                return sequence
    return best


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

    # Of the octaves that fit, take the one that moves the tune least.
    #
    # Taking the first that fitted instead meant every change of key could
    # drop the melody an octave and leave it there: C major to G and back
    # returned E4 where E5 went out, because E4 is in the soprano's range
    # and the search stopped at the first thing that was. Two keys out of
    # twenty-six came back to where they started. It also parks the tune at
    # the bottom of the range, which is where the three voices underneath
    # have the least room to work.
    # Measured against the melody that came in, not against the transposed
    # one: the transposed copy is what is being shifted, so scoring the
    # shifts by their distance from it makes shift zero win by definition
    # and reinstates the bug this replaced.
    incoming = [p for p in melody if p is not None]
    was = sum(p.midi for p in incoming) / len(incoming)
    best = None
    for shift in (0, -1, 1, -2, 2):
        candidate = [None if p is None else Pitch(p.letter, p.octave + shift, p.alteration)
                     for p in moved]
        inside = [p for p in candidate if p is not None]
        if not all(low.midi <= p.midi <= high.midi for p in inside):
            continue
        now = sum(p.midi for p in inside) / len(inside)
        if best is None or abs(now - was) < best[0]:
            best = (abs(now - was), candidate)
    return best[1] if best else moved


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
