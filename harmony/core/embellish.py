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


def _judge(sonority: Voicing, spec: ChordSpec, key: Key, index: int,
           legs, profile: Profile, sonority_rules, motion_rules) -> str:
    """The first rule refusing this sonority, or "" when none does.

    The decorated sonority is graded under the chord it decorates, and each
    leg carries its own pair of specs, because a strong-half figure is
    approached from the chord before while a weak-half one is left towards
    the chord after.
    """
    violations, _ = evaluate_state(
        StateContext(sonority, spec, key, index, profile),
        sonority_rules, short_circuit=False)

    for before, after, before_spec, after_spec in legs:
        found, _ = evaluate_transition(
            TransitionContext(a=before, b=after, spec_a=before_spec,
                              spec_b=after_spec, key=key, index=index,
                              profile=profile),
            motion_rules, short_circuit=False)
        violations += found

    blocking = [v for v in violations if v.severity == "error" and not v.waived]
    return blocking[0].rule_id if blocking else ""


def _refusal(a, passing, b, spec_a, spec_b, key, index, profile,
             sonority_rules, motion_rules) -> str:
    """A weak-half figure: held into from its own chord, out to the next."""
    return _judge(passing, spec_a, key, index,
                  ((a, passing, spec_a, spec_a), (passing, b, spec_a, spec_b)),
                  profile, sonority_rules, motion_rules)


def _strong_refusal(prev, sonority, resolution, spec_prev, spec, key, index,
                    profile, sonority_rules, motion_rules) -> str:
    """A strong-half figure: leapt or held into, resolving within the beat."""
    legs = [(sonority, resolution, spec, spec)]
    if prev is not None:
        legs.insert(0, (prev, sonority, spec_prev, spec))
    return _judge(sonority, spec, key, index, legs, profile,
                  sonority_rules, motion_rules)


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

    A weak-half figure needs the chord after it and so is not offered on the
    last beat. A strong-half one needs the chord before, and is.

    Refused candidates come back too, carrying the rule that forbids them.
    Whether to show them is the page's business, not this function's.
    """
    wanted = tuple(kinds) if kinds is not None else KINDS
    sonority_rules = [r for r in profile.rules("state") if r.id in SONORITY_RULES]
    motion_rules = [r for r in profile.rules("transition") if r.id in MOTION_RULES]
    picked = _picks_by_chord(chosen)

    out: list[Opportunity] = []
    for index in range(len(voicings)):
        here = voicings[index]
        prev, after, spec_prev, spec, spec_after = _beat_context(voicings, specs, index)
        strong, weak, on_strong, on_weak, _, _ = _place_on_beat(
            prev, here, after, spec_prev, spec, spec_after, index, key, profile,
            picked.get(index, []), sonority_rules, motion_rules)

        for voice in VOICE_NAMES:
            busy = voice in on_weak or voice in on_strong
            if after is not None and not busy:
                for kind, pitch in _weak_half_candidates(here, after, voice, key, spec):
                    if kind not in wanted:
                        continue
                    candidate = replace(weak, **{voice: pitch})
                    out.append(Opportunity(
                        index, voice, pitch, kind,
                        _refusal(here, candidate, after, spec, spec_after, key,
                                 index, profile, sonority_rules, motion_rules)))

            if not busy:
                for kind, pitch in _strong_half_candidates(prev, here, voice, key, spec):
                    if kind not in wanted:
                        continue
                    candidate = replace(strong, **{voice: pitch})
                    out.append(Opportunity(
                        index, voice, pitch, kind,
                        _strong_refusal(prev, candidate, weak, spec_prev, spec, key,
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


def _strong_half_candidates(prev: Voicing | None, here: Voicing, voice: str,
                            key: Key, spec: ChordSpec):
    """Notes that could sound on the first half of this beat and resolve.

    Both figures put a dissonance where the chord belongs and resolve it by
    step to the chord tone on the second half. What separates them is how
    the dissonance is reached: a suspension is held over from the chord
    before, an appoggiatura is leapt to.

    No time signature is consulted. That the first half of a beat is
    stronger than its second is a fact about the beat. Which beats of a bar
    are strong is a fact about the bar, and this engine does not know it -
    so a suspension on a weak beat cannot be refused here.
    """
    out = []
    target = here[voice]
    if prev is None:
        # Both figures are defined by how they are reached. With no chord
        # before this one there is nothing to hold over and nothing to leap
        # from, so neither can be claimed.
        return []

    held = prev[voice]
    interval, direction = melodic_interval(held, target)
    if direction < 0 and interval.generic == 2:
        out.append(("suspension", held))

    for step in (1, -1):
        note = step_from(target, key, step)
        if melodic_interval(prev[voice], note)[0].generic <= 2:
            continue          # stepped into, which is a passing shape, not a leap
        out.append(("appoggiatura", note))

    return [(kind, pitch) for kind, pitch in out
            if pitch.pitch_class.chroma not in spec.chroma_set]


def _picks_by_chord(chosen) -> dict:
    """Slot strings grouped by the beat they decorate."""
    out: dict[int, list[tuple[str, str, str]]] = {}
    for slot in chosen or ():
        parsed = _parse_slot(slot)
        if parsed:
            index, voice, kind, note = parsed
            out.setdefault(index, []).append((voice, kind, note))
    return out


def _place_on_beat(prev, voicing, after, spec_prev, spec, spec_after, index,
                   key, profile, picks, sonority_rules, motion_rules):
    """Work the chosen figures into one beat, one at a time.

    A beat carries two halves and can decorate both: a dissonance resolving
    on the first, a decoration leaving on the second. Each figure is judged
    against the sonority the ones before it have already built, because two
    that are legal alone are not therefore legal together.

    Returns the two halves, which voices carry a figure on each, which are
    tied over from the chord before, and what had to be refused.
    """
    strong, weak = voicing, voicing
    on_strong, on_weak, tied, refused = [], [], [], []

    def refuse(voice, kind, pitch, why):
        refused.append(Opportunity(index, voice, pitch, kind, why))

    for voice in VOICE_NAMES:
        for want_voice, kind, note in picks:
            if want_voice != voice:
                continue

            if kind in STRONG_HALF:
                if voice in on_strong or voice in on_weak:
                    refuse(voice, kind, None, ALREADY_DECORATED)
                    continue
                offered = {(k, str(pc)): pc for k, pc in
                           _strong_half_candidates(prev, voicing, voice, key, spec)}
                pitch = offered.get((kind, note))
                if pitch is None:
                    refuse(voice, kind, None, DOES_NOT_FIT)
                    continue
                candidate = replace(strong, **{voice: pitch})
                why = _strong_refusal(prev, candidate, weak, spec_prev, spec, key,
                                      index, profile, sonority_rules, motion_rules)
                if why:
                    refuse(voice, kind, pitch, why)
                    continue
                strong = candidate
                on_strong.append(voice)
                if kind == "suspension":
                    # Held over rather than struck again, which is the whole
                    # point of it and which the encoder has to be told.
                    tied.append(voice)
                continue

            if after is None:
                refuse(voice, kind, None, DOES_NOT_FIT)   # nothing to move into
                continue
            if voice in on_weak or voice in on_strong:
                refuse(voice, kind, None, ALREADY_DECORATED)
                continue
            offered = {(k, str(pc)): pc for k, pc in
                       _weak_half_candidates(voicing, after, voice, key, spec)}
            pitch = offered.get((kind, note))
            if pitch is None:
                refuse(voice, kind, None, DOES_NOT_FIT)
                continue
            candidate = replace(weak, **{voice: pitch})
            why = _refusal(voicing, candidate, after, spec, spec_after, key,
                           index, profile, sonority_rules, motion_rules)
            if why:
                refuse(voice, kind, pitch, why)
                continue
            weak = candidate
            on_weak.append(voice)

    return strong, weak, on_strong, on_weak, tied, refused


def _beat_context(voicings, specs, index):
    """The chord before, the chord after, and the specs that go with them."""
    prev = voicings[index - 1] if index else None
    after = voicings[index + 1] if index + 1 < len(voicings) else None
    spec = specs[index]
    return (prev, after, specs[index - 1] if index else spec,
            spec, specs[index + 1] if after is not None else spec)


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
        if not picks:
            events.append(Event(voicing, 1.0, index))
            continue

        prev, after, spec_prev, spec, spec_after = _beat_context(voicings, specs, index)
        strong, weak, on_strong, on_weak, tied, said_no = _place_on_beat(
            prev, voicing, after, spec_prev, spec, spec_after, index, key,
            profile, picks, sonority_rules, motion_rules)
        refused += said_no

        if not on_strong and not on_weak:
            events.append(Event(voicing, 1.0, index))
            continue
        # The beat splits once whatever is on it: a dissonance resolving on
        # the first half, a decoration leaving on the second, or both.
        events.append(Event(strong, 0.5, index, tuple(on_strong), tuple(tied)))
        events.append(Event(weak, 0.5, index, tuple(on_weak)))

    return events, refused
