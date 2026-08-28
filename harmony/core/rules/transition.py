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
    another for the same motion. That now includes the fourth as well as
    the fifth, so the wording speaks of intervals rather than of fifths.
    """
    if spec.tonicized_degree is not None:
        return ("A secondary dominant's applied leading tone must rise and its "
                "seventh must fall. Both obligations point the same way, and "
                "honouring them is what opens the interval. Leaving a tendency "
                "tone unresolved would be the worse fault.")
    if spec.aug6_type is not None:
        return ("An augmented sixth drives both of its outer tones outward by "
                "semitone at once - the lowered sixth down, the raised fourth "
                "up - and holding those two resolutions is what forces the "
                "fifth. The chord it resolves into inherits the same problem. "
                "Practice breaks the unequal fifth here rather than leave a "
                "tendency tone hanging.")
    if spec.quality == "diminished":
        return ("Every note of a diminished chord is a tendency tone, so every "
                "voice is already committed to a step and there is no spare "
                "voice left to break the interval with. This is the textbook "
                "unequal fifth, and the fourth it inverts to - a genuine "
                "parallel perfect interval here would still be caught, because "
                "quality is stored rather than counted.")
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
    rule_id="parallel_altered",
    scope="transition", severity="error", cost=math.inf, category="voice_leading",
    explanation=("The same altered interval twice between one pair - a diminished "
                 "fifth to a diminished fifth, an augmented fourth to an augmented "
                 "fourth. The letter distance never changes and both voices move, "
                 "so what is written is two fifths or two fourths running "
                 "together, whatever their quality."),
)
def parallel_altered(ctx: TransitionContext) -> list[Violation]:
    """The case that fell between the other three.

    Perfect to the same perfect is parallel_perfect. Perfect to altered,
    either direction, is unequal_fifths or unequal_fourths. Altered to the
    same altered belonged to nobody, and it is reachable: the diminished
    chord on the second degree of a minor key writes a pair of diminished
    fifths into V7 without difficulty.

    No waiver_for here, deliberately. That excuse is for an interval whose
    *quality* changes under a chord that commits every voice at once, and
    its own text draws the line: a genuine parallel fifth is still caught,
    because quality is stored rather than counted. Two diminished fifths in
    a row are two fifths in a row.
    """
    watched = ctx.profile.param("parallel_intervals", [1, 5, 8])
    bass_only = ctx.profile.param("parallel_fourths_with_bass_only", True)
    out = []
    for upper, lower in ALL_PAIRS:
        if not (_moved(ctx, upper) and _moved(ctx, lower)):
            continue
        before = interval_between(ctx.a[upper], ctx.a[lower]).simplified()
        after = interval_between(ctx.b[upper], ctx.b[lower]).simplified()
        if before.generic not in watched or after.generic != before.generic:
            continue
        # A change of quality is the unequal rules' to report, not this one's.
        if before.specific != after.specific:
            continue
        try:
            quality = before.quality
        except UnknownQuality:
            continue
        if quality == "perfect":
            continue                       # parallel_perfect owns these
        if before.generic == 4 and bass_only and lower != "bass":
            continue
        names = {1: "unison", 4: "fourth", 5: "fifth", 8: "octave"}
        out.append(Violation(
            "parallel_altered", [upper, lower], ctx.index,
            f"parallel {quality} {names[before.generic]}s: "
            f"{ctx.a[upper]}/{ctx.a[lower]} moving to "
            f"{ctx.b[upper]}/{ctx.b[lower]}",
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
    rule_id="unequal_fourths",
    scope="transition", severity="error", cost=math.inf, category="voice_leading",
    explanation=("Two fourths in a row where only the quality differs - perfect to "
                 "augmented, or augmented to perfect. The ear hears two fourths "
                 "moving together, and the other rules cannot see it: "
                 "parallel_perfect wants both intervals perfect and hidden_perfect "
                 "wants the arrival perfect."),
)
def unequal_fourths(ctx: TransitionContext) -> list[Violation]:
    """The fourth's analogue of unequal_fifths, and it has to be its own rule.

    A perfect fourth moving to an augmented one is not parallel fourths -
    the intervals differ in quality, which is exactly the distinction
    spelled pitch exists to preserve. But it is not nothing either: both
    voices move together and the letter distance never changes, so what is
    written on the staff is two fourths in a row.

    The gap this closes is specific. parallel_perfect asks that *both*
    intervals be watched perfect ones, and hidden_perfect asks that the
    *arrival* be perfect. An augmented fourth is neither, so a fourth
    sliding into a tritone passed both untouched - which is easy to reach
    in minor, where the diminished chord on the second degree puts a
    tritone over the very note a fourth wants to land on.
    """
    scope = ctx.profile.param("unequal_fourths", "all")
    pairs = ALL_PAIRS if scope == "all" else [p for p in ALL_PAIRS if "bass" in p]
    out = []
    for upper, lower in pairs:
        if not (_moved(ctx, upper) and _moved(ctx, lower)):
            continue
        before = interval_between(ctx.a[upper], ctx.a[lower]).simplified()
        after = interval_between(ctx.b[upper], ctx.b[lower]).simplified()
        if before.generic != 4 or after.generic != 4:
            continue
        try:
            qualities = {before.quality, after.quality}
        except UnknownQuality:
            continue
        # One of each. Perfect to perfect is parallel_perfect's business, and
        # augmented to augmented is a tritone held rather than a fourth moving.
        if len(qualities) != 2 or "perfect" not in qualities:
            continue
        excuse = waiver_for(ctx.spec_a)
        out.append(Violation(
            "unequal_fourths", [upper, lower], ctx.index,
            f"{before.quality} fourth to {after.quality} fourth: "
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
                 "frustrated when it leaps away instead. Which voices that is a "
                 "fault in is the profile's to say, in leading_tone_outer_voices, "
                 "and separately in applied_leading_tone_voices for a secondary "
                 "dominant, which commits every voice at once; elsewhere it is "
                 "reported as an exception with the reason. Moving down by step "
                 "is not frustration and is allowed anywhere."),
)
def leading_tone_resolution(ctx: TransitionContext) -> list[Violation]:
    spec = ctx.spec_a
    if spec.leading_tone_pc is None or not spec.has_dominant_function:
        return []

    tonic = spec.resolution_root_pc or ctx.key.tonic
    outer = ctx.profile.param("leading_tone_outer_voices", ["soprano", "bass"])
    # A secondary dominant commits every voice at once: the applied leading
    # tone must rise and the seventh must fall, and honouring both is what
    # opens the fifth that hidden_perfect already forgives through waiver_for.
    # Excusing the fifth while condemning the tone that forced it is exactly
    # the inconsistency waiver_for exists to prevent - and it is not academic,
    # it left `I V/V V I` with no realization at all. Which voices the excuse
    # covers stays the profile's to say, in its own parameter, so a profile
    # that wants applied leading tones held to the letter can still say so.
    if spec.tonicized_degree is not None:
        outer = ctx.profile.param("applied_leading_tone_voices", ["soprano", "bass"])
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

        # The excuse an inner voice gets is narrow and specific: the leading
        # tone may fall to the fifth of the chord it was resolving into, and
        # only that. Any other leap away is a fault wherever it happens. The
        # figure exists to avoid parallel fifths or to keep the resolving
        # chord complete, which is why it is priced rather than free - the
        # profile's waived_cost decides how badly the search wants to avoid it.
        falls_to_fifth = there.pitch_class == _fifth_above(tonic)
        frustrated_but_inner = name not in outer and falls_to_fifth
        excuse = ""
        if frustrated_but_inner:
            excuse = waiver_for(spec) or (
                "A leading tone in an inner voice may fall to the fifth of the "
                "chord it resolves into. It is where the ear notices it least, "
                "and it is what lets that chord keep all four members or the "
                "voices avoid parallel fifths. In the soprano or bass, and for "
                "any other leap away, it is still a fault.")
        out.append(Violation(
            "leading_tone_resolution", [name], ctx.index,
            f"the leading tone {here} in the {name} leaps to {there} instead of "
            f"rising to {tonic}",
            severity="exception" if frustrated_but_inner else "error",
            waived=frustrated_but_inner,
            reason=excuse,
        ))
    return out


@register(
    rule_id="seventh_resolution",
    scope="transition", severity="error", cost=math.inf, category="resolution",
    explanation=("A chordal seventh falls by step - unless the chord that "
                 "follows contains it, which makes it a consonance and "
                 "leaves nothing to resolve."),
)
def seventh_resolution(ctx: TransitionContext) -> list[Violation]:
    """Falls by step - unless the next chord stops it being a dissonance.

    The seventh resolves downward because it is dissonant against its own
    root. When the chord that follows contains that same tone as a chord
    member, the dissonance has gone: nothing is left to resolve, and the
    voice may simply hold. That is what makes V7 -> iv writable at all, since
    the seventh of V7 is the root of iv in every minor key.
    """
    spec = ctx.spec_a
    if spec.seventh_pc is None:
        return []
    consonant_next = spec.seventh_pc in ctx.spec_b.pitch_classes
    out = []
    for name in VOICE_NAMES:
        here, there = ctx.a[name], ctx.b[name]
        if here.pitch_class != spec.seventh_pc:
            continue
        interval, direction = melodic_interval(here, there)
        if direction == -1 and interval.generic == 2 and interval.specific in (1, 2):
            continue
        held = there.pitch_class == spec.seventh_pc
        if held and consonant_next:
            out.append(Violation(
                "seventh_resolution", [name], ctx.index,
                f"the seventh {here} in the {name} is held rather than resolved",
                severity="exception", waived=True,
                reason=(f"A seventh falls by step because it is a dissonance "
                        f"against its own root. Here {spec.seventh_pc} is a "
                        f"member of {ctx.spec_b.numeral} as well, so the "
                        f"dissonance is gone and there is nothing left to "
                        f"resolve - the voice keeps the note and it becomes a "
                        f"consonance."),
            ))
            continue
        out.append(Violation(
            "seventh_resolution", [name], ctx.index,
            f"the chordal seventh {here} in the {name} moves to {there} instead of "
            f"falling by step",
        ))
    return out


@register(
    rule_id="similar_motion",
    scope="transition", severity="style", cost=6.0, category="voice_leading",
    explanation=("Three or more voices moving the same way. Not a fault in "
                 "itself, but the shape that makes one: with three voices "
                 "together some pair lands on a perfect fourth, fifth or octave "
                 "in similar motion about nine times in ten, and with all four "
                 "it is certain. Priced rather than forbidden, because the "
                 "remainder really are clean."),
)
def similar_motion(ctx: TransitionContext) -> list[Violation]:
    """Steer away from the shape, and let the interval rules judge the result.

    The faults this anticipates - parallel and direct fifths, fourths and
    octaves - each have a rule of their own that decides the actual case.
    What this adds is a reason to prefer a texture where they cannot easily
    arise, which is the writer's usual instruction: keep the voices out of
    each other's way and most of the trouble never comes up.

    Forbidding it outright costs three of the twenty-four corpus
    progressions, all in minor, where iv to V leaves the upper voices
    little choice. So it is a price, not a wall.
    """
    limit = ctx.profile.param("similar_motion_limit", 3)
    for direction in (1, -1):
        moving = [name for name in VOICE_NAMES if _direction(ctx, name) == direction]
        if len(moving) < limit:
            continue
        return [Violation(
            "similar_motion", moving, ctx.index,
            f"{len(moving)} voices move {'up' if direction > 0 else 'down'} "
            f"together: {', '.join(moving)}",
            weight=float(len(moving) - limit + 1),
        )]
    return []


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
    explanation=("Approaching a perfect interval by similar motion exposes it. "
                 "Which intervals count, which pairs are watched and how much of "
                 "a leap it takes are the profile's to say - the fourth in "
                 "particular is a consonance between upper voices and is opt-in."),
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
        #   "none"   - any similar approach at all
        leap = ctx.profile.param("hidden_perfect_leap", "upper")
        # The fourth answers to its own setting, because it is the interval
        # stepwise similar motion actually reaches: IV to V drops some pair
        # into one every time, the upper voice stepping. One switch for all
        # three cannot express that. Set to "none" it would also condemn the
        # direct octave in V to I, where the alto steps to the tonic over a
        # leaping bass, and there would be no authentic cadence left to
        # write - which is exactly what happened when this was one knob.
        if simple.generic == 4:
            leap = ctx.profile.param("hidden_fourth_leap", leap)
        # Between soprano and bass nothing is hidden. The excuse for a
        # stepping upper voice is that the ear does not follow the pair
        # closely enough to notice, and that is untrue of the two voices it
        # follows most. The outer pair therefore answers to its own setting,
        # which the shipped profile sets to "none" - and it is affordable
        # precisely because it is only the one pair: the same strictness
        # across all six costs nine of the twenty-four corpus progressions,
        # while here the cadence simply arrives by contrary motion instead.
        if (upper, lower) == OUTER_PAIR:
            leap = ctx.profile.param("hidden_outer_leap", leap)
        upper_leap = abs(ctx.b[upper].midi - ctx.a[upper].midi) > 2
        lower_leap = abs(ctx.b[lower].midi - ctx.a[lower].midi) > 2
        #   "excuse" - no leap required, but a stepwise approach is reported
        #              as an exception rather than a fault. The edge survives
        #              and waived_cost prices it, which is how a profile says
        #              "avoid this wherever anything else will do". Forbidding
        #              it outright between the inner pairs costs seven of the
        #              twenty-four corpus progressions, the authentic cadence
        #              among them; excusing it costs none, and the engine
        #              still takes it only where there is no alternative.
        excused_by_step = False
        if leap == "upper" and not upper_leap:
            continue
        if leap == "either" and not (upper_leap or lower_leap):
            continue
        if leap == "excuse" and not upper_leap:
            excused_by_step = True
        name = {4: "fourth", 5: "fifth", 8: "octave"}[simple.generic]
        excuse = waiver_for(ctx.spec_a)
        if not excuse and excused_by_step:
            excuse = (f"The upper voice steps into this {name} rather than "
                      f"leaping to it, which is the classical excuse, and "
                      f"between inner voices it stands. Priced rather than "
                      f"free: the search takes it only where no other voicing "
                      f"will do.")
        out.append(Violation(
            "hidden_perfect", [upper, lower], ctx.index,
            f"hidden {name}: {upper} moves to {ctx.b[upper]} in similar motion "
            f"with {lower}",
            severity="exception" if excuse else "error",
            waived=bool(excuse),
            reason=excuse,
        ))
    return out
