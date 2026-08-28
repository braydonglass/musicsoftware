"""State rules 1-5: everything decidable from a single chord."""

from __future__ import annotations

import math

from ..voice import ADJACENT_PAIRS, VOICE_NAMES
from .registry import StateContext, Violation, register


@register(
    rule_id="voice_range",
    scope="state", severity="error", cost=math.inf, category="spacing",
    explanation="Each voice must stay inside its singable range.",
)
def voice_range(ctx: StateContext) -> list[Violation]:
    out = []
    for name in VOICE_NAMES:
        pitch = ctx.voicing[name]
        low, high = ctx.profile.ranges[name]
        if not (low.midi <= pitch.midi <= high.midi):
            out.append(Violation(
                "voice_range", [name], ctx.index,
                f"{pitch} lies outside the {name} range {low}-{high}",
            ))
    return out


@register(
    rule_id="spacing",
    scope="state", severity="error", cost=math.inf, category="spacing",
    explanation=("No more than an octave between soprano and alto, or between "
                 "alto and tenor. Tenor to bass may open further."),
)
def spacing(ctx: StateContext) -> list[Violation]:
    out = []
    for upper, lower in (("soprano", "alto"), ("alto", "tenor")):
        gap = ctx.voicing[upper].midi - ctx.voicing[lower].midi
        if gap > 12:
            out.append(Violation(
                "spacing", [upper, lower], ctx.index,
                f"{gap} semitones between {upper} and {lower} exceeds an octave",
            ))
    return out


@register(
    rule_id="voice_crossing",
    scope="state", severity="error", cost=math.inf, category="voice_leading",
    explanation="Voices must stay in order: soprano above alto above tenor above bass.",
)
def voice_crossing(ctx: StateContext) -> list[Violation]:
    out = []
    for upper, lower in ADJACENT_PAIRS:
        if ctx.voicing[upper].midi < ctx.voicing[lower].midi:
            out.append(Violation(
                "voice_crossing", [upper, lower], ctx.index,
                f"{upper} ({ctx.voicing[upper]}) has fallen below "
                f"{lower} ({ctx.voicing[lower]})",
            ))
    return out


@register(
    rule_id="voice_unison",
    scope="state", severity="warning", cost=3.0, category="spacing",
    explanation=("Two voices on one pitch collapse four parts into three. Double "
                 "at the octave instead, and keep the fourth voice audible."),
)
def voice_unison(ctx: StateContext) -> list[Violation]:
    """Only adjacent pairs need checking.

    Voices are already ordered soprano to bass, so two non-adjacent voices
    cannot share a pitch without the voice between them sharing it too - and
    that shows up as two adjacent collisions.
    """
    return [
        Violation("voice_unison", [upper, lower], ctx.index,
                  f"{upper} and {lower} are both on {ctx.voicing[upper]}")
        for upper, lower in ADJACENT_PAIRS
        if ctx.voicing[upper].midi == ctx.voicing[lower].midi
    ]


@register(
    rule_id="doubled_leading_tone",
    scope="state", severity="warning", cost=10.0, category="doubling",
    explanation=("Never double the leading tone. Resolve both copies and you have "
                 "parallel octaves; resolve one and leap away with the other and "
                 "the effect is diluted. This is what rules out the usual doubling "
                 "for V6, which must take one of the alternates."),
)
def doubled_leading_tone(ctx: StateContext) -> list[Violation]:
    if ctx.spec.leading_tone_pc is None:
        return []
    chroma = ctx.spec.leading_tone_pc.chroma
    voices = [n for n in VOICE_NAMES if ctx.voicing[n].pitch_class.chroma == chroma]
    if len(voices) < 2:
        return []
    return [Violation(
        "doubled_leading_tone", voices, ctx.index,
        f"the leading tone {ctx.spec.leading_tone_pc} is doubled in "
        f"{' and '.join(voices)}",
        reason=("Doubling the leading tone is normally forbidden: resolve both "
                "copies and you have parallel octaves. It is permitted here "
                "because the alternative was a worse fault - a rule of motion "
                "outranks a rule of doubling, since parallels are audible and "
                "a doubled tone is not. Both copies must still resolve "
                "differently, and the parallel rules enforce that."),
    )]


@register(
    rule_id="doubled_tendency_tone",
    scope="state", severity="warning", cost=12.0, category="doubling",
    explanation=("The chordal seventh and any altered tone owe a resolution, and "
                 "doubling one asks for it twice. Costly rather than impossible: "
                 "a chord with too few tones to voice otherwise needs the option."),
)
def doubled_tendency_tone(ctx: StateContext) -> list[Violation]:
    out = []
    counts: dict[int, list[str]] = {}
    for name in VOICE_NAMES:
        counts.setdefault(ctx.voicing[name].pitch_class.chroma, []).append(name)

    labels = {}
    if ctx.spec.seventh_pc is not None:
        labels[ctx.spec.seventh_pc] = "chordal seventh"
    if ctx.spec.aug6_lower_pc is not None:
        labels[ctx.spec.aug6_lower_pc] = "lowered sixth"
    if ctx.spec.aug6_upper_pc is not None:
        labels[ctx.spec.aug6_upper_pc] = "raised fourth"
    for pc in ctx.spec.pitch_classes:
        if ctx.key.is_altered(pc) and pc not in labels:
            labels[pc] = "altered tone"
    tendency = [(label, pc) for pc, label in labels.items()]

    for label, pc in tendency:
        voices = counts.get(pc.chroma, [])
        if len(voices) > 1:
            out.append(Violation(
                "doubled_tendency_tone", voices, ctx.index,
                f"the {label} {pc} is doubled in {' and '.join(voices)}",
            ))
    return out


@register(
    rule_id="doubling_preference",
    scope="state", severity="style", cost=1.5, category="doubling",
    explanation=("Root position doubles the root. Second inversion doubles the "
                 "fifth - the bass. First inversion is free: third, root or fifth "
                 "are all in use, which is what makes it the escape hatch when a "
                 "chord cannot be doubled the usual way."),
)
def doubling_preference(ctx: StateContext) -> list[Violation]:
    if ctx.spec.aug6_type is not None:
        return []          # no root in the tertian sense to prefer
    if ctx.spec.inversion == 1:
        return []          # first inversion takes any of the three
    if ctx.spec.seventh_pc is not None:
        return []          # four tones, four voices, nothing to double

    tones = ctx.spec.pitch_classes
    if ctx.spec.inversion == 0:
        wanted, label = tones[0], "root"
    elif ctx.spec.inversion == 2:
        wanted, label = tones[2], "fifth"
    else:
        return []

    if sum(1 for c in ctx.voicing.chromas() if c == wanted.chroma) >= 2:
        return []
    where = {0: "root position", 2: "second inversion"}[ctx.spec.inversion]
    return [Violation(
        "doubling_preference", [], ctx.index,
        f"{ctx.spec.numeral} is in {where}, which doubles the {label} {wanted}",
    )]


@register(
    rule_id="missing_essential_tone",
    scope="state", severity="error", cost=math.inf, category="doubling",
    explanation=("A chord needs its root and its third. The root names it and "
                 "the third gives it quality - without either it is not the "
                 "chord that was written. Everything else, including which tone "
                 "gets doubled, is negotiable when the voice leading demands it."),
)
def missing_essential_tone(ctx: StateContext) -> list[Violation]:
    """The one doubling fact that is not a preference.

    Everything else about doubling is priced, because a rule of motion is
    worth more than a rule of doubling: parallels are audible and a doubled
    third is not. But a chord that has lost its root or its third has stopped
    being the chord the progression asked for, and no amount of good voice
    leading repairs that.
    """
    present = set(ctx.voicing.chromas())
    essential = {}

    if ctx.spec.aug6_type is not None:
        # An augmented sixth is the interval it is named for; lose either end
        # and nothing of the chord survives.
        for pc in (ctx.spec.aug6_lower_pc, ctx.spec.aug6_upper_pc):
            if pc is not None:
                essential[pc] = "augmented sixth"
    else:
        essential[ctx.spec.pitch_classes[0]] = "root"
        if len(ctx.spec.pitch_classes) >= 2:
            essential[ctx.spec.pitch_classes[1]] = "third"

    return [
        Violation("missing_essential_tone", [], ctx.index,
                  f"{ctx.spec.numeral} is missing its {label} {pc}")
        for pc, label in essential.items() if pc.chroma not in present
    ]


@register(
    rule_id="missing_seventh",
    scope="state", severity="error", cost=math.inf, category="doubling",
    explanation=("A chord written with a seventh figure must have its seventh. "
                 "V43 names a seventh chord in second inversion; drop the seventh "
                 "and the figure is describing a chord that is not there. This is "
                 "not a doubling preference - it is what the numeral said."),
)
def missing_seventh(ctx: StateContext) -> list[Violation]:
    if ctx.spec.seventh_pc is None:
        return []
    if ctx.spec.seventh_pc.chroma in set(ctx.voicing.chromas()):
        return []
    return [Violation("missing_seventh", [], ctx.index,
                      f"{ctx.spec.numeral} omits its seventh {ctx.spec.seventh_pc}")]


@register(
    rule_id="incomplete_chord",
    scope="state", severity="warning", cost=4.0, category="doubling",
    explanation=("Sound every chord member. When one must go, the fifth is the one "
                 "that goes, and the root is tripled."),
)
def incomplete_chord(ctx: StateContext) -> list[Violation]:
    present = set(ctx.voicing.chromas())
    missing = [pc for pc in ctx.spec.pitch_classes if pc.chroma not in present]
    if not missing:
        return []
    # Dropping the fifth of a root-position triad is the sanctioned omission,
    # so it costs less than losing a third or a seventh.
    fifth = ctx.spec.pitch_classes[2]
    only_the_fifth = len(missing) == 1 and missing[0].chroma == fifth.chroma
    if only_the_fifth and ctx.spec.inversion == 0:
        return [Violation(
            "incomplete_chord", [], ctx.index,
            f"{ctx.spec.numeral} omits its fifth {fifth}",
        )]
    return [Violation(
        "incomplete_chord", [], ctx.index,
        f"{ctx.spec.numeral} is missing {', '.join(str(pc) for pc in missing)}",
    ) for _ in missing]
