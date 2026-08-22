"""Transition rules 6-10: everything decidable from a pair of chords."""

from __future__ import annotations

import math

from ..pitch import (LETTER_SEMITONES, PitchClass, UnknownQuality,
                     interval_between, melodic_interval)
from ..voice import ADJACENT_PAIRS, ALL_PAIRS, OUTER_PAIR, VOICE_NAMES
from .registry import TransitionContext, Violation, register


def _fifth_above(pc: PitchClass) -> PitchClass:
    ladder = pc.letter + 4
    letter = ladder % 7
    letter_chroma = LETTER_SEMITONES[letter] + 12 * (ladder // 7)
    root_chroma = LETTER_SEMITONES[pc.letter] + pc.alteration
    return PitchClass(letter, (root_chroma + 7) - letter_chroma)


def waiver_for(spec) -> str:
    """Why this chord is allowed to break a perfect-consonance rule, if it is.

    The excuse belongs to the musical situation, not to whichever rule
    happens to notice it first. Every rule that polices perfect consonances
    consults this, so a chord cannot be excused by one and condemned by
    another for the same motion.
    """
    if spec.tonicized_degree is not None:
        return ("A secondary dominant's applied leading tone must rise and its "
                "seventh must fall. Both obligations point the same way, and "
                "honouring them is what opens the fifth. Leaving a tendency "
                "tone unresolved would be the worse fault.")
    if spec.quality == "diminished":
        return ("Every note of a diminished chord is a tendency tone, so every "
                "voice is already committed to a step and there is no spare "
                "voice left to break the fifth with. This is the textbook "
                "unequal fifth - a genuine parallel fifth here would still be "
                "caught, because quality is stored rather than counted.")
    return ""


def _moved(ctx, name) -> bool:
    return ctx.a[name].midi != ctx.b[name].midi


def _direction(ctx, name) -> int:
    delta = ctx.b[name].midi - ctx.a[name].midi
    return (delta > 0) - (delta < 0)


def _is_watched_perfect(interval, watched) -> bool:
    simple = interval.simplified()
    if simple.generic not in watched:
        return False
    try:
        return simple.quality == "perfect"
    except Exception:
        return False


@register(
    rule_id="parallel_perfect",
    scope="transition", severity="error", cost=math.inf, category="voice_leading",
    explanation=("Two voices already a perfect unison, fifth or octave apart must "
                 "not move to the same perfect interval. The independence of the "
                 "parts collapses."),
)
def parallel_perfect(ctx: TransitionContext) -> list[Violation]:
    # Which perfect intervals may not be repeated. Fifths, octaves and unisons
    # always. The fourth is the fifth inverted, so including it is the strict
    # counterpoint position; four-part practice permits it between upper voices
    # because the bass supplies the consonance underneath.
    watched = ctx.profile.param("parallel_intervals", [1, 5, 8])
    bass_only = ctx.profile.param("parallel_fourths_with_bass_only", True)
    out = []
    for upper, lower in ALL_PAIRS:
        # Voices holding still are not moving in parallel.
        if not (_moved(ctx, upper) and _moved(ctx, lower)):
            continue
        before = interval_between(ctx.a[upper], ctx.a[lower])
        after = interval_between(ctx.b[upper], ctx.b[lower])
        # A diminished fifth is not a perfect consonance, which is exactly why
        # d5 -> P5 does not land here.
        if not (_is_watched_perfect(before, watched)
                and _is_watched_perfect(after, watched)):
            continue
        generic = after.simplified().generic
        if before.simplified().generic != generic:
            continue
        if generic == 4 and bass_only and lower != "bass":
            continue
        name = {1: "unisons", 4: "fourths", 5: "fifths", 8: "octaves"}[generic]
        # The German sixth resolving straight to V produces a pair of perfect
        # fifths that centuries of practice accept - Mozart's, by reputation.
        # Reported rather than hidden: the rule and the exception are both the
        # lesson, and a silent waiver teaches neither.
        waived = (name == "fifths" and ctx.spec_a.aug6_type == "german"
                  and ctx.profile.param("german_sixth_fifths", "forbid") == "allow")
        out.append(Violation(
            "parallel_perfect", [upper, lower], ctx.index,
            f"parallel {name}: {ctx.a[upper]}/{ctx.a[lower]} moving to "
            f"{ctx.b[upper]}/{ctx.b[lower]}",
            severity="exception" if waived else "error",
            waived=waived,
            reason=("The German sixth already contains a perfect fifth above its "
                    "bass, and both of those notes are obliged to move by "
                    "semitone - the lowered sixth down, the raised fourth up. "
                    "Holding the resolution means holding the fifth, so the "
                    "fifths move in parallel. Mozart wrote them; the alternative "
                    "is a cadential six-four in between."
                    if waived else ""),
        ))
    return out


@register(
    rule_id="consecutive_perfects",
    scope="transition", severity="error", cost=math.inf, category="voice_leading",
    explanation=("Two perfect consonances in a row between the same pair - a fifth "
                 "to an octave, an octave to a unison - hollow the texture out even "
                 "when the sizes differ and the motion is contrary. Between the "
                 "outer voices there is nothing to hide behind."),
)
def consecutive_perfects(ctx: TransitionContext) -> list[Violation]:
    """Perfect to perfect, different sizes.

    parallel_perfect covers the same interval twice and hidden_perfect covers
    similar motion into one. Neither sees a fifth opening to an octave by
    contrary motion, which between soprano and bass is as exposed as it gets.
    """
    scope = ctx.profile.param("consecutive_perfects_pairs", "outer")
    pairs = ALL_PAIRS if scope == "all" else (OUTER_PAIR,)
    out = []
    for upper, lower in pairs:
        if not (_moved(ctx, upper) and _moved(ctx, lower)):
            continue
        # Contrary motion between inner voices is how the parts get out of each
        # other's way; forbidding it there leaves iv -> V in minor with nowhere
        # to go. Between soprano and bass nothing is hidden, so any motion counts.
        if (_direction(ctx, upper) != _direction(ctx, lower)
                and (upper, lower) != OUTER_PAIR):
            continue
        # Fifths and octaves only. Similar motion into a fourth is
        # hidden_perfect's business; what is left here is the contrary-motion
        # case between the outer voices, where nothing is concealed.
        watched = ctx.profile.param("consecutive_perfect_intervals", [5, 8])
        before = interval_between(ctx.a[upper], ctx.a[lower])
        after = interval_between(ctx.b[upper], ctx.b[lower])
        if not (_is_watched_perfect(before, watched)
                and _is_watched_perfect(after, watched)):
            continue
        before, after = before.simplified(), after.simplified()
        if before.generic == after.generic:
            continue                       # same size is parallel_perfect's business
        names = {1: "unison", 4: "fourth", 5: "fifth", 8: "octave"}
        out.append(Violation(
            "consecutive_perfects", [upper, lower], ctx.index,
            f"perfect {names[before.generic]} to perfect {names[after.generic]}: "
            f"{ctx.a[upper]}/{ctx.a[lower]} moving to {ctx.b[upper]}/{ctx.b[lower]}",
        ))
    return out


@register(
    rule_id="unequal_fifths",
    scope="transition", severity="error", cost=math.inf, category="voice_leading",
    explanation=("Two fifths in a row where only the quality differs - perfect to "
                 "diminished, or diminished to perfect. Not parallel fifths, since "
                 "the intervals are not the same, but the ear hears two fifths "
                 "moving together and both directions are policed."),
)
def unequal_fifths(ctx: TransitionContext) -> list[Violation]:
    """Both directions, policed by default and excused where practice excuses.

    A diminished chord or a secondary dominant drives every voice to a step
    resolution, and holding those resolutions can force one fifth into the
    other. Those cases are reported as exceptions rather than errors, so the
    rule and the reason to break it arrive together.
    """
    scope = ctx.profile.param("unequal_fifths", "all")
    pairs = ALL_PAIRS if scope == "all" else [p for p in ALL_PAIRS if "bass" in p]
    out = []
    for upper, lower in pairs:
        if not (_moved(ctx, upper) and _moved(ctx, lower)):
            continue
        before = interval_between(ctx.a[upper], ctx.a[lower]).simplified()
        after = interval_between(ctx.b[upper], ctx.b[lower]).simplified()
        if before.generic != 5 or after.generic != 5:
            continue
        try:
            qualities = {before.quality, after.quality}
        except UnknownQuality:
            continue
        # Both directions. P5 -> d5 is the traditionally tolerated one and
        # d5 -> P5 the suspect one, but the ear hears two fifths moving
        # together either way. P5 -> P5 belongs to parallel_perfect.
        if qualities != {"perfect", "diminished"}:
            continue
        excuse = waiver_for(ctx.spec_a)
        out.append(Violation(
            "unequal_fifths", [upper, lower], ctx.index,
            f"{before.quality} fifth to {after.quality} fifth: "
            f"{ctx.a[upper]}/{ctx.a[lower]} moving to "
            f"{ctx.b[upper]}/{ctx.b[lower]}",
            severity="exception" if excuse else "error",
            waived=bool(excuse),
            reason=excuse,
        ))
    return out


@register(
    rule_id="voice_overlap",
    scope="transition", severity="error", cost=math.inf, category="voice_leading",
    explanation=("A voice must not move past where its neighbour just sat. The ear "
                 "loses track of which line is which."),
)
def voice_overlap(ctx: TransitionContext) -> list[Violation]:
    out = []
    for upper, lower in ADJACENT_PAIRS:
        if ctx.b[lower].midi > ctx.a[upper].midi:
            out.append(Violation(
                "voice_overlap", [lower, upper], ctx.index,
                f"{lower} rises to {ctx.b[lower]}, above where {upper} sat "
                f"({ctx.a[upper]})",
            ))
        if ctx.b[upper].midi < ctx.a[lower].midi:
            out.append(Violation(
                "voice_overlap", [upper, lower], ctx.index,
                f"{upper} falls to {ctx.b[upper]}, below where {lower} sat "
                f"({ctx.a[lower]})",
            ))
    return out


@register(
    rule_id="leading_tone_resolution",
    scope="transition", severity="error", cost=math.inf, category="resolution",
    explanation=("The leading tone of a V or vii\u00b0 rises to the tonic. It is "
                 "frustrated when it leaps away instead - a fault in an outer "
                 "voice, where it is most audible, and permitted in an inner one. "
                 "Moving down by step is not frustration and is allowed anywhere."),
)
def leading_tone_resolution(ctx: TransitionContext) -> list[Violation]:
    spec = ctx.spec_a
    if spec.leading_tone_pc is None or not spec.has_dominant_function:
        return []

    tonic = spec.resolution_root_pc or ctx.key.tonic
    outer = ctx.profile.param("leading_tone_outer_voices", ["soprano", "bass"])
    out = []

    for name in VOICE_NAMES:
        here, there = ctx.a[name], ctx.b[name]
        if here.pitch_class != spec.leading_tone_pc:
            continue
        step = there.midi - here.midi

        if step == 1 and there.pitch_class == tonic:
            continue                       # resolved as expected
        # Descending by step is not frustration. The packet is explicit: what
        # counts is leaping away from the tonic, not stepping down from it.
        if -2 <= step < 0:
            continue

        frustrated_but_inner = name not in outer
        out.append(Violation(
            "leading_tone_resolution", [name], ctx.index,
            f"the leading tone {here} in the {name} leaps to {there} instead of "
            f"rising to {tonic}",
            severity="exception" if frustrated_but_inner else "error",
            waived=frustrated_but_inner,
            reason=("A frustrated leading tone in an inner voice is allowed - it "
                    "is where the ear notices it least, and it lets the chord "
                    "that follows keep all four members. In the soprano or bass "
                    "it would still be a fault."
                    if frustrated_but_inner else ""),
        ))
    return out


@register(
    rule_id="seventh_resolution",
    scope="transition", severity="error", cost=math.inf, category="resolution",
    explanation="A chordal seventh falls by step.",
)
def seventh_resolution(ctx: TransitionContext) -> list[Violation]:
    spec = ctx.spec_a
    if spec.seventh_pc is None:
        return []
    out = []
    for name in VOICE_NAMES:
        here, there = ctx.a[name], ctx.b[name]
        if here.pitch_class != spec.seventh_pc:
            continue
        interval, direction = melodic_interval(here, there)
        if direction == -1 and interval.generic == 2 and interval.specific in (1, 2):
            continue
        out.append(Violation(
            "seventh_resolution", [name], ctx.index,
            f"the chordal seventh {here} in the {name} moves to {there} instead of "
            f"falling by step",
        ))
    return out


@register(
    rule_id="melodic_augmented",
    scope="transition", severity="error", cost=math.inf, category="voice_leading",
    explanation=("No voice may leap an augmented interval. The augmented second "
                 "between the sixth and raised seventh of minor is the usual "
                 "offender."),
)
def melodic_augmented(ctx: TransitionContext) -> list[Violation]:
    out = []
    for name in VOICE_NAMES:
        interval, direction = melodic_interval(ctx.a[name], ctx.b[name])
        if direction == 0:
            continue
        if interval.deviation > 0:
            out.append(Violation(
                "melodic_augmented", [name], ctx.index,
                f"the {name} moves {ctx.a[name]} to {ctx.b[name]}, an augmented "
                f"interval",
            ))
    return out


@register(
    rule_id="large_leap",
    scope="transition", severity="style", cost=1.0, category="voice_leading",
    explanation="Leaps wider than a perfect fifth are costly; the wider, the more so.",
)
def large_leap(ctx: TransitionContext) -> list[Violation]:
    out = []
    for name in VOICE_NAMES:
        semitones = abs(ctx.b[name].midi - ctx.a[name].midi)
        if semitones > 7:
            out.append(Violation(
                "large_leap", [name], ctx.index,
                f"the {name} leaps {semitones} semitones, {ctx.a[name]} to "
                f"{ctx.b[name]}",
                weight=float(semitones - 7),
            ))
    return out


@register(
    rule_id="leap_recovery",
    scope="transition", severity="error", cost=math.inf, category="voice_leading",
    explanation=("A leap in the melody must be answered by a step in the "
                 "opposite direction. Applied to the soprano only: the inner "
                 "voices and the bass exist to complete the harmony, and asking "
                 "them to shape a line as well leaves nothing to complete it "
                 "with."),
)
def leap_recovery(ctx: TransitionContext) -> list[Violation]:
    """Needs three chords, so a trellis edge cannot see it on its own.

    An edge may depend on the chord before it and the chord after it and no
    more; carrying the previous voicing in the DP state would square the
    search space. The solver instead searches wide and then ranks the paths
    it found by this rule, which is why `previous` is None during the search
    and supplied afterwards - and by the checker, which always has it.
    """
    if ctx.previous is None:
        return []
    out = []
    for name in ctx.profile.param("motion_voices", ["soprano"]):
        leap = ctx.a[name].midi - ctx.previous[name].midi
        if abs(leap) <= 4:
            continue          # a third or less is a step-like move, not a leap
        step = ctx.b[name].midi - ctx.a[name].midi
        if step != 0 and abs(step) <= 2 and (step > 0) != (leap > 0):
            continue          # answered by a step the other way
        out.append(Violation(
            "leap_recovery", [name], ctx.index,
            f"the {name} leaps {abs(leap)} semitones to {ctx.a[name]} and then "
            f"moves to {ctx.b[name]} instead of stepping back the other way",
        ))
    return out


@register(
    rule_id="outer_voice_similar_motion",
    scope="transition", severity="style", cost=0.6, category="voice_leading",
    explanation="Contrary or oblique motion between soprano and bass is preferred.",
)
def outer_voice_similar_motion(ctx: TransitionContext) -> list[Violation]:
    soprano, bass = _direction(ctx, "soprano"), _direction(ctx, "bass")
    if soprano == 0 or bass == 0 or soprano != bass:
        return []
    return [Violation(
        "outer_voice_similar_motion", list(OUTER_PAIR), ctx.index,
        "soprano and bass move in the same direction",
    )]


@register(
    rule_id="augmented_sixth_resolution",
    scope="transition", severity="error", cost=math.inf, category="resolution",
    explanation=("The augmented sixth expands outward by semitone to an octave: "
                 "the lowered sixth falls to scale degree 5 and the raised fourth "
                 "rises to meet it."),
)
def augmented_sixth_resolution(ctx: TransitionContext) -> list[Violation]:
    spec = ctx.spec_a
    if spec.aug6_type is None:
        return []
    out = []
    for name in VOICE_NAMES:
        here, there = ctx.a[name], ctx.b[name]
        if here.pitch_class == spec.aug6_lower_pc and there.midi - here.midi != -1:
            out.append(Violation(
                "augmented_sixth_resolution", [name], ctx.index,
                f"the lowered sixth {here} in the {name} moves to {there} instead "
                f"of falling a semitone",
            ))
        elif here.pitch_class == spec.aug6_upper_pc and there.midi - here.midi != 1:
            out.append(Violation(
                "augmented_sixth_resolution", [name], ctx.index,
                f"the raised fourth {here} in the {name} moves to {there} instead "
                f"of rising a semitone",
            ))
    return out


@register(
    rule_id="hidden_perfect",
    scope="transition", severity="error", cost=math.inf, category="voice_leading",
    explanation=("Approaching a perfect fifth or octave by similar motion, with "
                 "the upper voice leaping, exposes the perfect interval."),
)
def hidden_perfect(ctx: TransitionContext) -> list[Violation]:
    scope = ctx.profile.param("hidden_perfect_pairs", "outer")
    pairs = ALL_PAIRS if scope == "all" else (OUTER_PAIR,)
    out = []
    for upper, lower in pairs:
        if not (_moved(ctx, upper) and _moved(ctx, lower)):
            continue
        if _direction(ctx, upper) != _direction(ctx, lower):
            continue
        arrival = interval_between(ctx.b[upper], ctx.b[lower])
        # Which perfect intervals count as exposed. Fifths and octaves carry
        # the classical prohibition; the fourth is a consonance between upper
        # voices and is normally approached freely, so including it is opt-in.
        watched = list(ctx.profile.param("hidden_perfect_intervals", [5, 8]))
        # The fourth can be policed everywhere or only where it is exposed.
        # V and IV have roots a step apart, so their upper voices must move
        # together, and some pair always lands on a fourth or a fifth - policing
        # fourths in the inner parts makes IV -> V structurally unwritable.
        if 4 in watched and (upper, lower) != OUTER_PAIR \
                and ctx.profile.param("hidden_fourth_pairs", "all") == "outer":
            watched = [i for i in watched if i != 4]
        simple = arrival.simplified()
        if simple.generic not in watched:
            continue
        try:
            if simple.quality != "perfect":
                continue
        except Exception:
            continue
        # This rule owns every similar approach to a perfect interval, whatever
        # it came from - a fifth opening to a fourth is as exposed as a third
        # doing it. It stands aside only for the one case parallel_perfect
        # already names: the identical interval twice.
        departure = interval_between(ctx.a[upper], ctx.a[lower]).simplified()
        if (departure.generic == simple.generic
                and _is_watched_perfect(departure, watched)):
            continue
        # How much of a leap it takes to make the approach exposed.
        #   "upper"  - classical: only the upper voice leaping counts
        #   "either" - either voice leaping counts, which catches a stepping
        #              upper part over a leaping bass
        #   "none"   - any similar approach at all, which is stricter than any
        #              textbook and makes iv -> V in minor unrealizable
        leap = ctx.profile.param("hidden_perfect_leap", "upper")
        upper_leap = abs(ctx.b[upper].midi - ctx.a[upper].midi) > 2
        lower_leap = abs(ctx.b[lower].midi - ctx.a[lower].midi) > 2
        if leap == "upper" and not upper_leap:
            continue
        if leap == "either" and not (upper_leap or lower_leap):
            continue
        name = {4: "fourth", 5: "fifth", 8: "octave"}[simple.generic]
        excuse = waiver_for(ctx.spec_a)
        out.append(Violation(
            "hidden_perfect", [upper, lower], ctx.index,
            f"hidden {name}: {upper} moves to {ctx.b[upper]} in similar motion "
            f"with {lower}",
            severity="exception" if excuse else "error",
            waived=bool(excuse),
            reason=excuse,
        ))
    return out
