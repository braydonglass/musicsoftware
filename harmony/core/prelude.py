"""Keyboard figuration: a realization broken into a running figure.

The block-chord realization says which four notes sound together. A prelude
says the same chord one note at a time, in a fixed order, over and over. Bach's
Prelude in C is the pattern everybody knows: C3 E3 G3 C4 E4 G3 C4 E4, sixteen
sixteenths to the bar, the harmony changing underneath once a bar.

Two things follow from that, and they are why this module exists rather than
being folded into ``embellish``.

The figure is monophonic. An ``Event`` carries a whole ``Voicing`` and sounds
all four voices at once, which is exactly what an arpeggio does not do. And
the figure needs a note the realization does not have: Bach's fifth pitch, the
E4 above the soprano C4, belongs to no voice. So figuration gets its own flat
note list, and ``midi.encode`` takes it directly.

Nothing here re-voices. The ladder is built from the realization as the solver
wrote it, so the staff and the ear agree about what was written. This engine
spaces its chords more widely than Bach spaced his, so the figure comes out as
a broad spread rather than a compact keyboard texture; that is a true report
of the realization, not a fault in the figure. Realizing in closed position
narrows it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .pitch import Pitch
from .roman import ChordSpec
from .voice import VOICE_NAMES, Voicing


@dataclass(frozen=True)
class Note:
    """One struck note of the figure.

    Flat on purpose: a start, a length and a pitch, with no voice attached,
    because the figure has no voices. ``chord`` survives so the page can still
    light up the column the note came from, and ``rung`` survives so a test
    can say which step of the ladder was meant without reasoning backwards
    from a MIDI number.
    """

    pitch: Pitch
    start: float
    beats: float
    chord: int
    rung: int


@dataclass(frozen=True)
class Form:
    """A figuration pattern, and how it sits in a bar.

    A step is one rung, or several struck together. The second kind is what
    separates an accompaniment from an arpeggio: a waltz's second and third
    beats are a chord, not a note, and no amount of rearranging single rungs
    will make one.
    """

    id: str
    label: str
    meter: tuple[int, int]
    unit: float                      # beats per step: 0.25 a sixteenth
    pattern: tuple                   # per step, a rung or a tuple of rungs
    sustained: tuple[int, ...] = ()  # pattern positions held to the group's end
    drone: tuple[int, ...] = ()      # rungs struck once and held for the bar
    rungs: int = 0                   # how tall the ladder must be

    def step(self, position: int) -> tuple[int, ...]:
        """The rungs one step strikes. A bare rung reads as a step of one."""
        rungs = self.pattern[position]
        return rungs if isinstance(rungs, tuple) else (rungs,)

    @property
    def beats_per_measure(self) -> float:
        numerator, denominator = self.meter
        return numerator * 4.0 / denominator

    @property
    def group_beats(self) -> float:
        return self.unit * len(self.pattern)

    @property
    def repeats(self) -> int:
        """How many times the pattern says itself in one bar."""
        count = self.beats_per_measure / self.group_beats
        if abs(count - round(count)) > 1e-9:
            raise ValueError(
                f"the {self.id} pattern does not divide its own bar"
            )
        return int(round(count))


def above(pitch: Pitch, spec: ChordSpec) -> Pitch:
    """The next tone of the chord above a pitch, spelled as the chord spells it.

    This is the rule that finds Bach's fifth note. Over the tonic of C with a
    soprano C4 it gives E4; over ii7 above D4, F4; over V7 above D4, F4. Those
    are bars 1 to 3 of BWV 846.

    It walks letter names rather than semitones, and takes the accidental from
    the chord's own spelling, so a German augmented sixth (Ab C Eb F#) answers
    F#4 with Ab4 rather than G#4. The two are the same key on a piano and are
    not the same note on a stave, and every voice-leading rule in this package
    depends on the difference.

    The comparison on ``midi`` is what stops a same-sounding letter counting
    as higher: above B#3 the answer is E4, not the C4 that shares its number.
    """
    by_letter = {pc.letter: pc for pc in spec.pitch_classes}
    ladder = pitch.diatonic_index + 1
    # Two octaves of letters is enough for any chord that owns a letter at
    # all; the bound stops a malformed spec spinning.
    while ladder < pitch.diatonic_index + 15:
        letter = ladder % 7
        if letter in by_letter:
            candidate = Pitch(letter, ladder // 7, by_letter[letter].alteration)
            if candidate.midi > pitch.midi:
                return candidate
        ladder += 1
    raise ValueError(f"nothing in {spec.numeral} lies above {pitch}")


def ladder_for(voicing: Voicing, spec: ChordSpec, rungs: int) -> list[Pitch]:
    """The pitches the figure steps through, low to high.

    Duplicates are dropped by sounding pitch, not by voice. A doubled root is
    one rung, so the pattern steps past it to a real note instead of striking
    the same key twice in a row - which is the difference between a figure and
    a stutter. Dropping them also shortens the ladder, so the extension below
    makes up the difference and the bar keeps its rhythm.
    """
    seen: dict[int, Pitch] = {}
    for name in VOICE_NAMES:
        pitch = voicing[name]
        # First spelling wins. Two voices on one key are one sound, and the
        # stave already draws them as one head.
        seen.setdefault(pitch.midi, pitch)
    rung_list = [seen[key] for key in sorted(seen)]
    while len(rung_list) < rungs:
        rung_list.append(above(rung_list[-1], spec))
    return rung_list


def check(form: Form) -> None:
    """Refuse a form that would strike a note it is already holding.

    Two notes of one MIDI number overlapping is not a thicker sound, it is a
    shorter one: the encoder writes note-offs before note-ons at a shared
    tick, so the second note's ending silences the first. A form that wants a
    rung droning under the figure must keep the figure off that rung.
    """
    for position in range(len(form.pattern)):
        for rung in form.step(position):
            if rung >= form.rungs:
                raise ValueError(
                    f"the {form.id} pattern reaches rung {rung}, past the "
                    f"{form.rungs} its ladder is built to"
                )
            if rung in form.drone:
                raise ValueError(
                    f"the {form.id} pattern strikes rung {rung} at position "
                    f"{position} while droning it"
                )
    for held in form.sustained:
        for rung in form.step(held):
            for position in range(held + 1, len(form.pattern)):
                if rung in form.step(position):
                    raise ValueError(
                        f"the {form.id} pattern strikes rung {rung} at "
                        f"position {position} while sustaining it from "
                        f"position {held}"
                    )


BACH_C = Form(
    id="bach-c",
    label="Bach, Prelude in C",
    meter=(4, 4),
    unit=0.25,
    # bass, tenor, alto, soprano, then the tone above the soprano - and the
    # top three again. Over C3 E3 G3 C4 that is bar 1 of BWV 846 exactly.
    pattern=(0, 1, 2, 3, 4, 2, 3, 4),
    # Bach holds the two low notes under the running figure. Striking them as
    # sixteenths turns the prelude into a music box.
    sustained=(0, 1),
    rungs=5,
)

ALBERTI = Form(
    id="alberti",
    label="Alberti bass",
    meter=(4, 4),
    unit=0.5,
    pattern=(0, 2, 1, 2),
    # The top of the voicing stays out of the figure and sings over it.
    drone=(3,),
    rungs=4,
)

WALTZ = Form(
    id="waltz",
    label="Broken-chord waltz",
    meter=(3, 4),
    unit=0.5,
    pattern=(0, 1, 2, 3, 2, 1),
    rungs=4,
)

RISE_FALL = Form(
    id="rise-fall",
    label="Rise and fall",
    meter=(4, 4),
    unit=0.25,
    # Bach's five rungs, but turning back down instead of repeating the top
    # three. Same material, and it arrives somewhere else.
    pattern=(0, 1, 2, 3, 4, 3, 2, 1),
    rungs=5,
)

HARP = Form(
    id="harp",
    label="Harp sweep",
    meter=(4, 4),
    unit=0.25,
    # Straight up the ladder and start again. The four rungs above the
    # voicing come from the chord tones over the soprano, so a sweep climbs
    # about three octaves without ever leaving the harmony.
    pattern=(0, 1, 2, 3, 4, 5, 6, 7),
    rungs=8,
)

MOONLIGHT = Form(
    id="moonlight",
    label="Slow triplets",
    meter=(12, 8),
    unit=0.5,
    # The bass is held for the bar and the three notes above it turn over it
    # four times. Beethoven's Op. 27 no. 2 in outline.
    pattern=(1, 2, 3),
    drone=(0,),
    rungs=4,
)

NOCTURNE = Form(
    id="nocturne",
    label="Nocturne left hand",
    meter=(6, 8),
    unit=0.5,
    # A low note under a rocking pair. The bass is held so the figure has
    # something to sit on rather than a hole where beat one was.
    pattern=(0, 2, 3, 2, 3, 2),
    sustained=(0,),
    rungs=4,
)

MURKY = Form(
    id="murky",
    label="Murky bass",
    meter=(4, 4),
    unit=0.5,
    pattern=(0, 2, 0, 2),
    drone=(3,),
    rungs=4,
)

OOMPAH = Form(
    id="oompah",
    label="Oom-pah-pah waltz",
    meter=(3, 4),
    unit=1.0,
    pattern=(0, (1, 2, 3), (1, 2, 3)),
    rungs=4,
)

STRIDE = Form(
    id="stride",
    label="Stride",
    meter=(4, 4),
    unit=1.0,
    # The bass alternates between the bottom of the chord and the next rung
    # up, and the chord answers it on the weak beats.
    pattern=(0, (2, 3), 1, (2, 3)),
    rungs=4,
)

BOOM_CHICK = Form(
    id="boom-chick",
    label="Boom-chick",
    meter=(2, 4),
    unit=1.0,
    pattern=(0, (1, 2, 3)),
    rungs=4,
)

PULSE = Form(
    id="pulse",
    label="Repeated chords",
    meter=(4, 4),
    unit=0.5,
    # Every eighth is the chord, over a held bass. The Waldstein opens on it.
    pattern=((1, 2, 3),),
    drone=(0,),
    rungs=4,
)

FORMS: tuple[Form, ...] = (
    BACH_C, RISE_FALL, HARP, ALBERTI, MOONLIGHT, NOCTURNE, WALTZ,
    OOMPAH, STRIDE, BOOM_CHICK, MURKY, PULSE,
)
BY_ID = {form.id: form for form in FORMS}

for _form in FORMS:
    check(_form)
    _form.repeats          # raises now rather than on the first realization
del _form


def figurate(voicings, specs, form: Form) -> list[Note]:
    """Break a realization into a figure: one chord to a bar."""
    if len(voicings) != len(specs):
        raise ValueError(
            f"{len(voicings)} chords of voices against {len(specs)} numerals"
        )
    bar = form.beats_per_measure
    notes: list[Note] = []
    for index, (voicing, spec) in enumerate(zip(voicings, specs)):
        rungs = ladder_for(voicing, spec, form.rungs)
        origin = index * bar
        for rung in form.drone:
            notes.append(Note(rungs[rung], origin, bar, index, rung))
        for repeat in range(form.repeats):
            base = origin + repeat * form.group_beats
            for position in range(len(form.pattern)):
                start = base + position * form.unit
                beats = (base + form.group_beats - start
                         if position in form.sustained else form.unit)
                for rung in form.step(position):
                    notes.append(Note(rungs[rung], start, beats, index, rung))
    notes.sort(key=lambda note: (note.start, note.pitch.midi))
    return notes


def spans(notes) -> list[tuple[float, float, int]]:
    """The (start, end, midi) triples the encoder speaks."""
    return [(note.start, note.start + note.beats, note.pitch.midi)
            for note in notes]
