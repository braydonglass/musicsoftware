"""Passing tones, placed where the writer asks for them.

The engine decides nothing here. It reports where a passing tone will fit,
spells the one that fits, and refuses any that break rules already in the
registry - naming the rule that refused it. Which of the surviving
opportunities to take is the writer's choice and nobody else's.

Only the rules that can speak about a non-chord tone are consulted. A
passing tone is not a chord tone, so the harmonic rules - doubling,
completeness, the resolution of a tendency tone - would be answering a
question nobody asked. See ``MOTION_RULES`` and ``SONORITY_RULES``.

Meter never enters. A passing tone sits on the weak half of the beat it
decorates, which is a fact about the beat rather than about the bar, so
this module needs no time signature and is not given one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .key import Key
from .pitch import Pitch, melodic_interval
from .roman import ChordSpec
from .rules.registry import (
    Profile,
    StateContext,
    TransitionContext,
    evaluate_state,
    evaluate_transition,
)
from .voice import VOICE_NAMES, Voicing


def filling(a: Pitch, b: Pitch, key: Key) -> Pitch | None:
    """The diatonic step between two pitches a third apart, or None.

    The letter is not a choice: a third spans exactly one letter name, so
    the key signature supplies the accidental and nothing else does.
    Deriving the alteration from semitones instead is what writes G-sharp
    where A-flat belongs.
    """
    interval, direction = melodic_interval(a, b)
    if direction == 0 or interval.generic != 3:
        return None
    # A third means the two letter positions differ by exactly two, so the
    # midpoint is a whole number and lands on the letter between them.
    ladder = (a.diatonic_index + b.diatonic_index) // 2
    letter = ladder % 7
    return Pitch(letter, ladder // 7, key.signature()[letter])


# Rules that can speak about a sonority holding a non-chord tone. Every one
# of them asks about motion or position, so a passing tone is a fair subject.
MOTION_RULES = (
    "parallel_perfect",
    "consecutive_perfects",
    "hidden_perfect",
    "unequal_fifths",
    "unequal_fourths",
    "voice_overlap",
    "melodic_augmented",
)
SONORITY_RULES = (
    "voice_range",
    "spacing",
    "voice_crossing",
    "voice_unison",
)

# Deliberately absent, and the absence is the point: incomplete_chord,
# missing_essential_tone, missing_seventh, doubling_preference,
# doubled_leading_tone, doubled_tendency_tone, leading_tone_resolution,
# seventh_resolution and augmented_sixth_resolution all read ctx.spec to ask
# what the chord owes. A passing tone owes it nothing - it is not in the
# chord - so those rules would be answering a question nobody asked, and
# every passing tone ever written would fail them.
#
# large_leap and leap_recovery are absent for the opposite reason: a passing
# tone moves by step by construction, so neither can ever fire.


# Where each figure sits in the beat it decorates. The weak-half figures
# leave the chord sounding on the beat and decorate after it; the strong-half
# ones put a dissonance on the beat and resolve to the chord after it.
#
# No time signature is involved in that distinction. The first half of a beat
# is stronger than its second, which is a fact about the beat. Which *beats*
# of a bar are strong is a fact about the bar, and this module still does not
# know it - see the limit recorded in the README.
WEAK_HALF = ("passing", "neighbour", "anticipation", "escape")
STRONG_HALF = ("suspension", "appoggiatura")
KINDS = WEAK_HALF + STRONG_HALF

LABELS = {
    "passing": "passing tone",
    "neighbour": "neighbour tone",
    "anticipation": "anticipation",
    "escape": "escape tone",
    "suspension": "suspension",
    "appoggiatura": "appoggiatura",
}


def step_from(pitch: Pitch, key: Key, direction: int) -> Pitch:
    """The next letter up or down, spelled by the key signature.

    The same commitment as everywhere else: the letter comes first and the
    accidental follows from the key, so the neighbour above B in C major is
    C and never B-sharp.
    """
    ladder = pitch.diatonic_index + direction
    letter = ladder % 7
    return Pitch(letter, ladder // 7, key.signature()[letter])


@dataclass(frozen=True)
class Opportunity:
    """A place a figure will go, and whether it may.

    ``chord`` is the beat being decorated. A weak-half figure decorates the
    second half of that chord's beat and needs the chord after it; a
    strong-half one decorates the first half and, for a suspension, needs
    the chord before.
    """

    chord: int
    voice: str
    pitch: Pitch | None
    kind: str = "passing"
    refused_by: str = ""    # the rule that forbids it; empty when it is free

    @property
    def available(self) -> bool:
        return not self.refused_by

    @property
    def slot(self) -> str:
        """What the writer clicked, as one string.

        A neighbour offers two notes in the same voice on the same beat, so
        the pitch has to be part of what identifies a choice.
        """
        return f"{self.chord}:{self.voice}:{self.kind}:{self.pitch}"


def _refusal(a: Voicing, passing: Voicing, b: Voicing,
             spec_a: ChordSpec, spec_b: ChordSpec, key: Key, index: int,
             profile: Profile, sonority_rules, motion_rules) -> str:
    """The first rule refusing this passing tone, or "" when none does.

    The passing sonority is graded under the chord it decorates: the tone
    sits inside that chord's beat, so spec_a is its context on both legs of
    the move.
    """
    violations, _ = evaluate_state(
        StateContext(passing, spec_a, key, index, profile),
        sonority_rules, short_circuit=False)

    legs = ((a, passing, spec_a, spec_a), (passing, b, spec_a, spec_b))
    for before, after, before_spec, after_spec in legs:
        found, _ = evaluate_transition(
            TransitionContext(a=before, b=after, spec_a=before_spec,
                              spec_b=after_spec, key=key, index=index,
                              profile=profile),
            motion_rules, short_circuit=False)
        violations += found

    blocking = [v for v in violations if v.severity == "error" and not v.waived]
    return blocking[0].rule_id if blocking else ""


def _weak_half_candidates(a: Voicing, b: Voicing, voice: str, key: Key,
                          spec: ChordSpec):
    """Every note that could decorate the second half of this beat.

    Yields (kind, pitch). A candidate that happens to be a tone of the chord
    it decorates is dropped: a non-chord tone that belongs to the chord is
    not a figure, it is just the chord.
    """
    here, there = a[voice], b[voice]
    out = []

    filled = filling(here, there, key)
    if filled is not None:
        out.append(("passing", filled))

    if here.midi == there.midi and here.diatonic_index == there.diatonic_index:
        # A held note has nowhere to anticipate and nothing to escape from,
        # but it is exactly what a neighbour decorates.
        out.append(("neighbour", step_from(here, key, 1)))
        out.append(("neighbour", step_from(here, key, -1)))
    else:
        _, direction = melodic_interval(here, there)
        out.append(("anticipation", there))
        # The escape steps away from where the line is going and then leaps
        # back across it, which is what makes it an escape rather than a
        # passing tone.
        escape = step_from(here, key, -direction)
        if melodic_interval(escape, there)[0].generic > 2:
            out.append(("escape", escape))

    return [(kind, pitch) for kind, pitch in out
            if pitch.pitch_class.chroma not in spec.chroma_set]


def opportunities(voicings: list[Voicing], specs: list[ChordSpec],
                  key: Key, profile: Profile, kinds=None,
                  chosen=()) -> list[Opportunity]:
    """Every place a figure would go, judged against what is already there.

    ``chosen`` matters more than it looks. Judging each candidate against
    the bare chord shows a writer a note that will refuse itself the moment
    it is clicked, because by then another figure on the same beat has
    changed the sonority it has to fit. Offers are therefore measured
    against the beat as the choices already made have left it, and what is
    offered is what will actually work.

    Refused candidates come back too, carrying the rule that forbids them.
    Whether to show them is the page's business, not this function's.
    """
    wanted = tuple(kinds) if kinds is not None else KINDS
    sonority_rules = [r for r in profile.rules("state") if r.id in SONORITY_RULES]
    motion_rules = [r for r in profile.rules("transition") if r.id in MOTION_RULES]
    picked = _picks_by_chord(chosen)

    out: list[Opportunity] = []
    for index in range(len(voicings) - 1):
        a, b = voicings[index], voicings[index + 1]
        sonority, placed, _ = _place_on_beat(
            a, b, specs[index], specs[index + 1], index, key, profile,
            picked.get(index, []), sonority_rules, motion_rules)

        for voice in VOICE_NAMES:
            for kind, pitch in _weak_half_candidates(a, b, voice, key, specs[index]):
                if kind not in wanted:
                    continue
                if voice in placed:
                    continue          # that voice is spoken for on this beat
                candidate = replace(sonority, **{voice: pitch})
                out.append(Opportunity(
                    index, voice, pitch, kind,
                    _refusal(a, candidate, b, specs[index], specs[index + 1], key,
                             index, profile, sonority_rules, motion_rules)))
    return out


# What a choice is refused with when it no longer fits the voicing under it -
# a re-realization can move the notes a slot was measured against. Not a rule
# id: no rule is involved, the figure simply has nowhere to go.
DOES_NOT_FIT = "no_longer_fits_here"

# One voice can carry one figure per beat. Asking for two is not a rule
# violation either, just an impossibility.
ALREADY_DECORATED = "voice_already_decorated"


@dataclass(frozen=True)
class Event:
    """One sounding moment: a full sonority and how long it lasts.

    An undecorated chord is a single event of one beat, so a realization
    with no figures in it reads exactly as it did before there were any. A
    decorated one is two events of half a beat.
    """

    voicing: Voicing
    beats: float
    chord: int                          # which chord of the progression this is
    decorating: tuple[str, ...] = ()    # voices sounding a non-chord tone here
    tied: tuple[str, ...] = ()          # voices held over from the event before


def _parse_slot(slot):
    """A slot string back into its parts, or None if it is not one."""
    parts = str(slot).split(":")
    if len(parts) != 4:
        return None
    try:
        return int(parts[0]), parts[1], parts[2], parts[3]
    except ValueError:
        return None


def _picks_by_chord(chosen) -> dict:
    """Slot strings grouped by the beat they decorate."""
    out: dict[int, list[tuple[str, str, str]]] = {}
    for slot in chosen or ():
        parsed = _parse_slot(slot)
        if parsed:
            index, voice, kind, note = parsed
            out.setdefault(index, []).append((voice, kind, note))
    return out


def _place_on_beat(voicing, after, spec_a, spec_b, index, key, profile,
                   picks, sonority_rules, motion_rules):
    """Work the chosen figures into one beat, one at a time.

    Each is judged against the sonority the ones before it have already
    built, because two figures that are legal alone are not therefore legal
    together. Returns what the beat became, which voices carry a figure,
    and what had to be refused.
    """
    sonority, placed, refused = voicing, [], []
    for voice in VOICE_NAMES:
        for want_voice, kind, note in picks:
            if want_voice != voice:
                continue
            if voice in placed:
                refused.append(
                    Opportunity(index, voice, None, kind, ALREADY_DECORATED))
                continue
            offered = {(k, str(pc)): pc for k, pc in
                       _weak_half_candidates(voicing, after, voice, key, spec_a)}
            pitch = offered.get((kind, note))
            if pitch is None:
                refused.append(
                    Opportunity(index, voice, None, kind, DOES_NOT_FIT))
                continue
            candidate = replace(sonority, **{voice: pitch})
            why = _refusal(voicing, candidate, after, spec_a, spec_b, key,
                           index, profile, sonority_rules, motion_rules)
            if why:
                refused.append(Opportunity(index, voice, pitch, kind, why))
                continue
            sonority = candidate
            placed.append(voice)
    return sonority, placed, refused


def apply(voicings: list[Voicing], specs: list[ChordSpec], key: Key,
          profile: Profile, chosen) -> tuple[list[Event], list[Opportunity]]:
    """Place the figures a writer has chosen.

    ``chosen`` is a list of slot strings, as ``Opportunity.slot`` writes
    them. The candidates are rebuilt here rather than trusted from the
    slot, so a stale click cannot smuggle in a note that no longer fits.

    Returns the events to sound and whatever had to be refused. Choices are
    taken one at a time and each is judged against the sonority the ones
    before it have already built: two figures that are each legal alone are
    not therefore legal together, and the second is the one refused.
    """
    sonority_rules = [r for r in profile.rules("state") if r.id in SONORITY_RULES]
    motion_rules = [r for r in profile.rules("transition") if r.id in MOTION_RULES]

    picked = _picks_by_chord(chosen)
    events: list[Event] = []
    refused: list[Opportunity] = []

    for index, voicing in enumerate(voicings):
        picks = picked.get(index, [])
        # The last chord has nothing to decorate into.
        if not picks or index >= len(voicings) - 1:
            events.append(Event(voicing, 1.0, index))
            continue

        sonority, placed, said_no = _place_on_beat(
            voicing, voicings[index + 1], specs[index], specs[index + 1], index,
            key, profile, picks, sonority_rules, motion_rules)
        refused += said_no

        if not placed:
            events.append(Event(voicing, 1.0, index))
            continue
        events.append(Event(voicing, 0.5, index))
        events.append(Event(sonority, 0.5, index, tuple(placed)))

    return events, refused
