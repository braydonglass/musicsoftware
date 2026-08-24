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


@dataclass(frozen=True)
class Opportunity:
    """A place a passing tone will go, and whether it may."""

    chord: int          # the tone sits on the weak half of this chord's beat
    voice: str
    pitch: Pitch | None
    refused_by: str = ""    # the rule that forbids it; empty when it is free

    @property
    def available(self) -> bool:
        return not self.refused_by


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


def opportunities(voicings: list[Voicing], specs: list[ChordSpec],
                  key: Key, profile: Profile) -> list[Opportunity]:
    """Every place a passing tone would go, refused ones included.

    Refusals are reported rather than dropped. Where a passing tone cannot
    go is worth as much to a writer as where one can, and the rule that
    forbids it is the lesson.
    """
    sonority_rules = [r for r in profile.rules("state") if r.id in SONORITY_RULES]
    motion_rules = [r for r in profile.rules("transition") if r.id in MOTION_RULES]

    out: list[Opportunity] = []
    for index in range(len(voicings) - 1):
        a, b = voicings[index], voicings[index + 1]
        for voice in VOICE_NAMES:
            pitch = filling(a[voice], b[voice], key)
            if pitch is None:
                continue
            passing = replace(a, **{voice: pitch})
            out.append(Opportunity(
                index, voice, pitch,
                _refusal(a, passing, b, specs[index], specs[index + 1], key,
                         index, profile, sonority_rules, motion_rules)))
    return out


# What a choice is refused with when the voice does not move by a third at
# all. Not a rule id: no rule is involved, there is simply nothing to fill.
# The web layer can send a stale choice after a re-realization changes the
# voicing under it, so this has to be answerable rather than fatal.
NO_THIRD = "no_third_to_fill"


@dataclass(frozen=True)
class Event:
    """One sounding moment: a full sonority and how long it lasts.

    An undecorated chord is a single event of one beat, so a realization
    with no passing tones in it reads exactly as it did before there were
    any. A decorated one is two events of half a beat, the second carrying
    the passing tones.
    """

    voicing: Voicing
    beats: float
    chord: int                      # which chord of the progression this is
    passing: tuple[str, ...] = ()   # voices sounding a non-chord tone here


def apply(voicings: list[Voicing], specs: list[ChordSpec], key: Key,
          profile: Profile, chosen) -> tuple[list[Event], list[Opportunity]]:
    """Place the passing tones a writer has chosen.

    Returns the events to sound and whatever had to be refused. Choices are
    taken one voice at a time and each is judged against the sonority the
    ones before it have already built: two passing tones that are each
    legal alone are not therefore legal together, and the second is the one
    that gets refused.
    """
    sonority_rules = [r for r in profile.rules("state") if r.id in SONORITY_RULES]
    motion_rules = [r for r in profile.rules("transition") if r.id in MOTION_RULES]

    wanted: dict[int, set[str]] = {}
    for index, voice in chosen:
        wanted.setdefault(index, set()).add(voice)

    events: list[Event] = []
    refused: list[Opportunity] = []

    for index, voicing in enumerate(voicings):
        # The last chord has nothing to pass into.
        voices = [v for v in VOICE_NAMES
                  if v in wanted.get(index, ()) and index < len(voicings) - 1]
        if not voices:
            events.append(Event(voicing, 1.0, index))
            continue

        after = voicings[index + 1]
        sonority, placed = voicing, []
        for voice in voices:
            pitch = filling(voicing[voice], after[voice], key)
            if pitch is None:
                refused.append(Opportunity(index, voice, None, NO_THIRD))
                continue
            candidate = replace(sonority, **{voice: pitch})
            why = _refusal(voicing, candidate, after, specs[index],
                           specs[index + 1], key, index, profile,
                           sonority_rules, motion_rules)
            if why:
                refused.append(Opportunity(index, voice, pitch, why))
                continue
            sonority = candidate
            placed.append(voice)

        if not placed:
            events.append(Event(voicing, 1.0, index))
            continue
        events.append(Event(voicing, 0.5, index))
        events.append(Event(sonority, 0.5, index, tuple(placed)))

    return events, refused
