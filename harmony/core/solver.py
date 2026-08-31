"""Dynamic programming over a trellis.

Each column is one chord, each node a legal voicing of it, each left-to-right
path a complete realization. Soft rules make edges expensive; hard rules
delete them. The cheapest surviving path is the answer.

No rule logic lives here. The solver only knows that some number came back
infinite.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .key import Key
from .pitch import Pitch
from .roman import ChordSpec, RomanNumeralError, parse
from .rules.registry import Profile, TransitionContext, evaluate_transition

# Rules that need to see three chords at once. A trellis edge spans two, so
# these cannot bind during the search; the solver searches wide instead and
# ranks the surviving paths by them afterwards.
CONTEXT_RULES = {"leap_recovery"}
SEARCH_WIDTH = 12          # paths kept per node so the ranking has choices
MAX_RANKED = 400           # cap on how many finished paths get scored
from .voice import Voicing
from .voicing import describe_failure, generate


@dataclass
class Realization:
    voicings: list[Voicing]
    cost: float
    # The chords actually used. Identical to what was typed unless the solver
    # was allowed to re-invert something to make the progression work.
    specs: list[ChordSpec] | None = None

    def substitutions(self, written: list[ChordSpec]) -> list[tuple[int, str, str]]:
        """(chord number, what was written, what was used) for anything changed."""
        if self.specs is None:
            return []
        return [(i + 1, w.numeral, u.numeral)
                for i, (w, u) in enumerate(zip(written, self.specs))
                if w.numeral != u.numeral]


class NoRealization(Exception):
    """Raised when every path dies, carrying the reason it died."""


def realize(
    specs: list[ChordSpec],
    key: Key,
    profile: Profile,
    k: int = 1,
    soprano: list[Pitch] | None = None,
    allow_inversions: bool = False,
) -> list[Realization]:
    if not specs:
        raise ValueError("the progression is empty")
    if soprano is not None and len(soprano) > len(specs):
        raise ValueError(
            f"the melody has {len(soprano)} notes against {len(specs)} chords"
        )
    if soprano is not None:
        # A melody may be pinned in part. A ``None`` leaves that chord's
        # soprano to the search, and a melody shorter than the progression
        # leaves the chords past its end free - which is what happens when a
        # chord is added to a progression whose tune is already chosen.
        soprano = list(soprano) + [None] * (len(specs) - len(soprano))

    columns: list[list[tuple[Voicing, float, ChordSpec]]] = []
    for index, spec in enumerate(specs):
        fixed = soprano[index] if soprano else None
        column = [(v, c, spec) for v, c in generate(spec, key, profile, soprano=fixed)]

        if allow_inversions:
            # The bass line is the thing an inversion changes, so a substitution
            # is never free: it costs enough that what was written wins whenever
            # it can, and only gets used when nothing else works.
            for alternative in _inversions_of(spec, key):
                column += [(v, c + INVERSION_COST, alternative)
                           for v, c in generate(alternative, key, profile, soprano=fixed)]

        if not column:
            if fixed is not None and generate(spec, key, profile):
                raise NoRealization(
                    f"chord {index + 1}: {spec.numeral} cannot carry {fixed} in the "
                    f"soprano. It spells "
                    f"{' '.join(str(pc) for pc in spec.pitch_classes)}."
                )
            raise NoRealization(describe_failure(spec, key, profile))
        columns.append(column)

    all_transition_rules = profile.rules("transition")
    context_rules = [r for r in all_transition_rules if r.id in CONTEXT_RULES]
    transition_rules = [r for r in all_transition_rules if r.id not in CONTEXT_RULES]
    # Only hard rules can kill an edge. Soft violations ride along in the same
    # list and would otherwise be blamed for a failure they did not cause.
    hard_rule_ids = {rule.id for rule in transition_rules if rule.is_hard}
    width = max(1, k)
    # Search wider than asked when a context rule has to be satisfied after
    # the fact, so there are alternatives left to choose between.
    search_width = max(width, SEARCH_WIDTH) if context_rules else width

    # history[i][j] is a list of (accumulated_cost, previous_j, previous_rank),
    # cheapest first, at most `width` long.
    history: list[list[list[tuple[float, int | None, int | None]]]] = [
        [[(node_cost, None, None)] for _, node_cost, _ in columns[0]]
    ]

    for i in range(len(columns) - 1):
        previous = history[-1]
        layer: list[list[tuple[float, int | None, int | None]]] = []
        blocked: dict[str, int] = {}

        for target, (voicing_b, node_cost, spec_b) in enumerate(columns[i + 1]):
            candidates: list[tuple[float, int, int]] = []
            for source, (voicing_a, _, spec_a) in enumerate(columns[i]):
                if not previous[source]:
                    continue
                ctx = TransitionContext(
                    a=voicing_a, b=voicing_b,
                    spec_a=spec_a, spec_b=spec_b,
                    key=key, index=i, profile=profile,
                )
                violations, edge = evaluate_transition(ctx, transition_rules)
                if math.isinf(edge):
                    for violation in violations:
                        if violation.rule_id in hard_rule_ids:
                            blocked[violation.rule_id] = blocked.get(violation.rule_id, 0) + 1
                    continue
                for rank, (accumulated, _, _) in enumerate(previous[source]):
                    candidates.append((accumulated + edge + node_cost, source, rank))
            candidates.sort(key=lambda entry: entry[0])
            layer.append(candidates[:search_width])

        if not any(layer):
            raise NoRealization(_explain_dead_transition(specs, i, blocked))
        history.append(layer)

    finals: list[tuple[float, int, int]] = []
    for node, paths in enumerate(history[-1]):
        for rank, (cost, _, _) in enumerate(paths):
            finals.append((cost, node, rank))
    finals.sort(key=lambda entry: entry[0])

    ranked: list[tuple[int, float, list[Voicing]]] = []
    seen: set[tuple] = set()
    for cost, node, rank in finals[:MAX_RANKED]:
        voicings, used = _backtrack(columns, history, node, rank)
        signature = tuple(voicings)
        if signature in seen:
            continue
        seen.add(signature)
        faults = _context_faults(voicings, used, key, profile, context_rules)
        ranked.append((faults, cost, voicings, used))

    # Paths that satisfy the three-chord rules come first; cost decides the
    # rest. When none satisfies them the cheapest still comes back, and the
    # checker will say what is wrong with it rather than the engine pretending
    # there was no answer.
    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    return [Realization(voicings, cost, used)
            for _, cost, voicings, used in ranked[:width]]


INVERSION_COST = 6.0


def _inversions_of(spec: ChordSpec, key: Key) -> list[ChordSpec]:
    """Other inversions of the same chord, when none was written.

    A figure the writer typed is a decision about the bass line and is left
    alone. A bare numeral is not, so the solver may try the others.
    """
    if spec.figure or spec.aug6_type or spec.tonicized_degree is not None:
        return []
    # First inversion only. A six-four is not a general-purpose substitute:
    # it is unstable and belongs to the cadential, passing and pedal figures,
    # none of which the solver is in a position to judge.
    figures = ["6"] if spec.seventh_pc is None else ["65", "43", "42"]

    # A dominant triad may also take its seventh. Three tones in four voices
    # force a doubling, and a doubled tone approached in similar motion is a
    # perfect interval approached in similar motion - which is why iv -> V is
    # unwritable as a plain triad but fine as iv -> V7. The seventh gives the
    # voices a fourth pitch to land on.
    if spec.seventh_pc is None and spec.has_dominant_function:
        figures = figures + ["7", "65"]

    out = []
    for figure in figures:
        try:
            out.append(parse(spec.numeral + figure, key))
        except (RomanNumeralError, ValueError):
            continue
    return out


def _context_faults(voicings, specs, key, profile, rules) -> int:
    """How many three-chord rules this finished path breaks."""
    if not rules:
        return 0
    faults = 0
    for index in range(len(voicings) - 1):
        ctx = TransitionContext(
            a=voicings[index], b=voicings[index + 1],
            spec_a=specs[index], spec_b=specs[index + 1],
            key=key, index=index, profile=profile,
            previous=voicings[index - 1] if index > 0 else None,
        )
        violations, _ = evaluate_transition(ctx, rules, short_circuit=False)
        faults += sum(1 for v in violations if not v.waived)
    return faults


def solve(specs, key, profile, k: int = 1, soprano=None, reinvert: bool = True):
    """Realize as written, and re-voice if that answer has faults in it.

    One place, so the CLI, the web layer and the tests cannot drift apart on
    when a substitution is allowed.

    The test used to be whether writing it as asked had *an* answer. That
    was the same question while the motion rules deleted edges: no answer
    meant no clean answer. Once those rules are priced instead - so that
    every chord can follow every chord and the cost says what it took - the
    two questions come apart, and asking the old one silently stopped the
    re-voicing from ever running. I IV V I came back with an overlapping
    bass and tenor rather than as I IV V65 I, because the faulty answer
    existed and nothing looked at whether it was any good.

    So a faulty answer is not enough. If what was written comes back with
    something wrong in it, the inversions are tried too and the clean one
    wins; if neither is clean, the cheaper one does, which is the one that
    breaks less.
    """
    from .checker import check, errors_only

    def graded(results):
        first = results[0]
        used = first.specs or specs
        return len(errors_only(check(first.voicings, used, key, profile)))

    try:
        written = realize(specs, key, profile, k=k, soprano=soprano)
    except NoRealization:
        if not reinvert:
            raise
        return realize(specs, key, profile, k=k, soprano=soprano,
                       allow_inversions=True)

    if not reinvert or graded(written) == 0:
        return written
    try:
        revoiced = realize(specs, key, profile, k=k, soprano=soprano,
                           allow_inversions=True)
    except NoRealization:
        return written
    if graded(revoiced) < graded(written):
        return revoiced
    if graded(revoiced) == graded(written) and revoiced[0].cost < written[0].cost:
        return revoiced
    return written


def _backtrack(columns, history, node: int, rank: int):
    voicings: list[Voicing] = []
    used: list[ChordSpec] = []
    for column in range(len(columns) - 1, -1, -1):
        voicings.append(columns[column][node][0])
        used.append(columns[column][node][2])
        _, previous_node, previous_rank = history[column][node][rank]
        if previous_node is None:
            break
        node, rank = previous_node, previous_rank
    return list(reversed(voicings)), list(reversed(used))


def _explain_dead_transition(specs, index: int, blocked: dict[str, int]) -> str:
    """Say which move is impossible and which rules made it so.

    "No solution" is never a useful answer. An unrealizable progression is
    usually a real fact about the progression, and the reason is the lesson.
    """
    move = f"{specs[index].numeral} to {specs[index + 1].numeral}"
    if not blocked:
        return f"no voicing of {move} survives, and no rule claimed responsibility"
    ranked = sorted(blocked.items(), key=lambda kv: -kv[1])
    detail = ", ".join(f"{rule_id} ({count} times)" for rule_id, count in ranked)
    return (
        f"chords {index + 1} to {index + 2} ({move}) cannot be connected: every "
        f"pairing was rejected by {detail}"
    )
