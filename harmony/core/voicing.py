"""Generate every voicing of a chord that is legal on its own terms.

Only state rules apply here. Whether a voicing is a good move *from* some
other voicing is a transition question, and belongs to the solver.
"""

from __future__ import annotations

import math

from .key import Key
from .pitch import Pitch, PitchClass
from .roman import ChordSpec
from .rules.registry import Profile, StateContext, evaluate_state
from .voice import Voicing


def pitches_in_range(pc: PitchClass, low: Pitch, high: Pitch) -> list[Pitch]:
    """Every octave placement of a pitch class that fits a voice."""
    out = []
    for octave in range(low.octave - 1, high.octave + 2):
        pitch = pc.at_octave(octave)
        if low.midi <= pitch.midi <= high.midi:
            out.append(pitch)
    return out


def candidates(spec: ChordSpec, voice: str, profile: Profile) -> list[Pitch]:
    low, high = profile.ranges[voice]
    out: list[Pitch] = []
    for pc in spec.pitch_classes:
        out.extend(pitches_in_range(pc, low, high))
    return sorted(out, key=lambda p: p.midi)


def generate(spec: ChordSpec, key: Key, profile: Profile,
             soprano: Pitch | None = None) -> list[tuple[Voicing, float]]:
    """All state-legal voicings, each with its soft-rule cost.

    Built bass upward, pruning on crossing and spacing at every step rather
    than producing the full cross product and filtering afterwards.

    A given `soprano` pins the top voice, which is how a supplied melody is
    harmonized: the search runs exactly as before, over a narrower column.
    """
    state_rules = profile.rules("state")
    low, high = profile.ranges["bass"]
    basses = pitches_in_range(spec.bass_pc, low, high)

    tenors = candidates(spec, "tenor", profile)
    altos = candidates(spec, "alto", profile)
    sopranos = candidates(spec, "soprano", profile)
    if soprano is not None:
        sopranos = [p for p in sopranos if p == soprano]
        if not sopranos:
            return []

    out: list[tuple[Voicing, float]] = []
    for bass in basses:
        for tenor in tenors:
            if tenor.midi < bass.midi:
                continue                                  # crossing
            for alto in altos:
                if alto.midi < tenor.midi:
                    continue                              # crossing
                if alto.midi - tenor.midi > 12:
                    continue                              # spacing
                for soprano in sopranos:
                    if soprano.midi < alto.midi:
                        continue                          # crossing
                    if soprano.midi - alto.midi > 12:
                        continue                          # spacing
                    voicing = Voicing(soprano, alto, tenor, bass)
                    ctx = StateContext(voicing, spec, key, 0, profile)
                    violations, cost = evaluate_state(ctx, state_rules)
                    if math.isinf(cost):
                        continue
                    out.append((voicing, cost))
    return out


def describe_failure(spec: ChordSpec, key: Key, profile: Profile) -> str:
    """Why a chord produced no voicings at all."""
    state_rules = profile.rules("state")
    reasons: dict[str, int] = {}
    low, high = profile.ranges["bass"]
    if not pitches_in_range(spec.bass_pc, low, high):
        return (f"{spec.numeral} needs {spec.bass_pc} in the bass, which has no "
                f"octave inside the bass range {low}-{high}")
    for bass in pitches_in_range(spec.bass_pc, low, high):
        for tenor in candidates(spec, "tenor", profile):
            for alto in candidates(spec, "alto", profile):
                for soprano in candidates(spec, "soprano", profile):
                    voicing = Voicing(soprano, alto, tenor, bass)
                    ctx = StateContext(voicing, spec, key, 0, profile)
                    violations, cost = evaluate_state(ctx, state_rules)
                    for v in violations:
                        reasons[v.rule_id] = reasons.get(v.rule_id, 0) + 1
    if not reasons:
        return f"{spec.numeral} produced no voicings and no reasons, which is a bug"
    ranked = sorted(reasons.items(), key=lambda kv: -kv[1])
    return (f"{spec.numeral} has no legal voicing; every attempt was rejected by "
            + ", ".join(f"{rule_id} ({count})" for rule_id, count in ranked))
