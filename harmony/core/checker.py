"""Grade a supplied realization.

Calls exactly the rule functions the solver calls. The only differences are
that nothing is short-circuited, so a student sees every fault rather than
the first one, and that the previous chord is threaded through so the
three-chord rules can speak.
"""

from __future__ import annotations

from .key import Key
from .roman import ChordSpec
from .rules.registry import (
    Profile,
    StateContext,
    TransitionContext,
    Violation,
    evaluate_state,
    evaluate_transition,
)
from .voice import Voicing


def check(
    voicings: list[Voicing],
    specs: list[ChordSpec],
    key: Key,
    profile: Profile,
) -> list[Violation]:
    if len(voicings) != len(specs):
        raise ValueError(
            f"{len(voicings)} chords of voices against {len(specs)} Roman numerals"
        )

    state_rules = profile.rules("state")
    transition_rules = profile.rules("transition")
    out: list[Violation] = []

    for index, (voicing, spec) in enumerate(zip(voicings, specs)):
        ctx = StateContext(voicing, spec, key, index, profile)
        violations, _ = evaluate_state(ctx, state_rules, short_circuit=False)
        out.extend(violations)

    for index in range(len(voicings) - 1):
        ctx = TransitionContext(
            a=voicings[index], b=voicings[index + 1],
            spec_a=specs[index], spec_b=specs[index + 1],
            key=key, index=index, profile=profile,
            previous=voicings[index - 1] if index > 0 else None,
        )
        violations, _ = evaluate_transition(ctx, transition_rules, short_circuit=False)
        out.extend(violations)

    return sorted(out, key=lambda v: (v.chord_index, v.rule_id))


def errors_only(violations: list[Violation]) -> list[Violation]:
    """Just the hard faults. Style notes are preferences, not mistakes."""
    return [v for v in violations if v.severity == "error" and not v.waived]


def exceptions_only(violations: list[Violation]) -> list[Violation]:
    """Rules broken on purpose, with the reason practice broke them."""
    return [v for v in violations if v.waived]


def explained_breaks(violations: list[Violation]) -> list[Violation]:
    """Every rule the engine knowingly broke, waived or merely paid for.

    A waived rule cost nothing and a priced one cost something, but from a
    student's side both are the same event: a rule was broken and there is a
    reason. Reporting only the waived ones hides half of it.
    """
    return [v for v in violations if v.reason]


def voicings_from_lines(
    soprano: str, alto: str, tenor: str, bass: str
) -> list[Voicing]:
    """Build voicings from four space-separated lines of pitch names."""
    from .pitch import Pitch

    lines = {"soprano": soprano, "alto": alto, "tenor": tenor, "bass": bass}
    parsed = {}
    for name, text in lines.items():
        parsed[name] = [Pitch.parse(tok) for tok in text.split()]

    lengths = {name: len(v) for name, v in parsed.items()}
    if len(set(lengths.values())) != 1:
        detail = ", ".join(f"{n} has {c}" for n, c in lengths.items())
        raise ValueError(f"the four voices must be the same length: {detail}")

    return [
        Voicing(parsed["soprano"][i], parsed["alto"][i],
                parsed["tenor"][i], parsed["bass"][i])
        for i in range(lengths["soprano"])
    ]
