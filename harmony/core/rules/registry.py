"""Rule objects, violations, and the profile that switches them on.

Every rule has the same shape and lives in one registry. Nothing here knows
whether it is being used to search for an answer or to grade one - that is
the point. The solver and the checker call the same functions, so they
cannot drift apart.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..key import Key
from ..pitch import Pitch
from ..roman import ChordSpec
from ..voice import Voicing

PROFILE_DIR = Path(__file__).resolve().parents[2] / "profiles"


@dataclass
class Violation:
    rule_id: str
    voices: list[str]
    chord_index: int          # for transitions, the first chord of the pair
    message: str
    severity: str = "error"
    # Lets a rule scale its own cost - a ten-semitone leap should not cost
    # what an eight-semitone leap costs.
    weight: float = 1.0
    # A waived violation is one the rule found and a profile deliberately
    # excused. It costs nothing and blocks nothing, but it is still reported,
    # so the student meets the rule and the exception together instead of
    # meeting neither.
    waived: bool = False
    # Why practice permits this one. Set only on waived violations, and kept
    # separate from the message so it can be shown as the explanation it is.
    reason: str = ""

    def __str__(self) -> str:
        where = ", ".join(self.voices) if self.voices else "-"
        return f"{self.rule_id} [{where}] at chord {self.chord_index + 1}: {self.message}"


@dataclass
class StateContext:
    voicing: Voicing
    spec: ChordSpec
    key: Key
    index: int
    profile: "Profile"


@dataclass
class TransitionContext:
    a: Voicing
    b: Voicing
    spec_a: ChordSpec
    spec_b: ChordSpec
    key: Key
    index: int
    profile: "Profile"
    # Only the checker supplies this. The solver leaves it None because a
    # trellis edge may depend on two adjacent chords and no more; see
    # leap_recovery in transition.py.
    previous: Voicing | None = None


@dataclass
class Rule:
    id: str
    scope: str        # "state" | "transition"
    severity: str     # "error" | "warning" | "style"
    cost: float       # math.inf for hard rules
    category: str     # "voice_leading" | "spacing" | "doubling" | "resolution"
    check: Callable
    explanation: str
    citation: str = ""
    # What a profile charges for a violation this rule has excused. Zero
    # means an excuse is free, which is what waiving has always meant.
    waived_cost: float = 0.0

    @property
    def is_hard(self) -> bool:
        return math.isinf(self.cost)


REGISTRY: dict[str, Rule] = {}


def register(rule_id, scope, severity, cost, category, explanation, citation=""):
    """Decorator putting a check function into the registry as a Rule."""
    def wrap(fn):
        REGISTRY[rule_id] = Rule(
            id=rule_id, scope=scope, severity=severity, cost=cost,
            category=category, check=fn, explanation=explanation, citation=citation,
        )
        return fn
    return wrap


@dataclass
class Profile:
    name: str
    ranges: dict[str, tuple[Pitch, Pitch]]
    settings: dict[str, dict]
    params: dict
    description: str = ""

    @classmethod
    def load(cls, name_or_path: str) -> "Profile":
        # is_file, not exists: an empty name resolves to Path("."), which
        # exists perfectly well and is a directory.
        path = Path(name_or_path) if name_or_path else Path("")
        if not path.is_file():
            path = PROFILE_DIR / f"{name_or_path}.json"
        if not path.is_file():
            available = ", ".join(sorted(p.stem for p in PROFILE_DIR.glob("*.json")))
            raise FileNotFoundError(
                f"no profile {name_or_path!r}; available profiles are: {available}"
            )
        data = json.loads(path.read_text())
        ranges = {
            voice: (Pitch.parse(lo), Pitch.parse(hi))
            for voice, (lo, hi) in data["ranges"].items()
        }
        return cls(
            name=data.get("name", path.stem),
            description=data.get("description", ""),
            ranges=ranges,
            settings=data.get("rules", {}),
            params=data.get("params", {}),
        )

    def setting(self, rule_id: str) -> dict:
        return self.settings.get(rule_id, {})

    def is_enabled(self, rule_id: str) -> bool:
        return self.setting(rule_id).get("enabled", True)

    def severity_of(self, rule_id: str) -> str:
        return self.setting(rule_id).get("severity", REGISTRY[rule_id].severity)

    def cost_of(self, rule_id: str) -> float:
        raw = self.setting(rule_id).get("cost", REGISTRY[rule_id].cost)
        if isinstance(raw, str) and raw.lower() in ("inf", "infinity"):
            return math.inf
        if raw is None:
            return math.inf
        return float(raw)

    def waived_cost_of(self, rule_id: str) -> float:
        """What this profile charges for a fault it has excused.

        Zero by default: a waived violation is reported with its reason and
        costs nothing, which is how the engine has always read a waiver.
        Pricing one says something different and useful - the excuse is a
        last resort. The edge stays legal, so nothing becomes unwritable,
        but the search will take any alternative that avoids it and pay
        only where there is none.
        """
        raw = self.setting(rule_id).get("waived_cost", 0.0)
        if isinstance(raw, str) and raw.lower() in ("inf", "infinity"):
            return math.inf
        return float(raw or 0.0)

    def param(self, name: str, default=None):
        return self.params.get(name, default)

    def rules(self, scope: str | None = None) -> list[Rule]:
        """Active rules, with this profile's severity and cost applied."""
        out = []
        for rule_id, rule in REGISTRY.items():
            if not self.is_enabled(rule_id):
                continue
            if scope is not None and rule.scope != scope:
                continue
            out.append(Rule(
                id=rule.id, scope=rule.scope,
                severity=self.severity_of(rule_id), cost=self.cost_of(rule_id),
                waived_cost=self.waived_cost_of(rule_id),
                category=rule.category, check=rule.check,
                explanation=rule.explanation, citation=rule.citation,
            ))
        return sorted(out, key=lambda r: r.id)


def _apply(rules, ctx, short_circuit: bool = True) -> tuple[list[Violation], float]:
    """Run rules against a context, returning violations and accumulated cost.

    The two modes want different things here. The solver only needs to know
    that a candidate is dead, so it stops at the first hard violation and
    saves the remaining checks across tens of thousands of pairs. The checker
    is writing feedback for a student and must report every fault, so it
    passes short_circuit=False and pays for the full sweep.
    """
    violations: list[Violation] = []
    cost = 0.0
    for rule in rules:
        found = rule.check(ctx)
        if not found:
            continue
        for violation in found:
            if not violation.waived:
                violation.severity = rule.severity
            violations.append(violation)

        # An excused violation is not a fault, but a profile may price it.
        # This is where "allowed only when nothing else will do" is said:
        # the edge survives and gets expensive, so the search prefers any
        # path without it and pays only where there is no alternative.
        excused = [v for v in found if v.waived]
        if excused and rule.waived_cost and not math.isinf(cost):
            cost += rule.waived_cost * sum(v.weight for v in excused)

        binding = [v for v in found if not v.waived]
        if not binding:
            continue
        if rule.is_hard:
            cost = math.inf
            if short_circuit:
                return violations, cost
            continue
        if not math.isinf(cost):
            cost += rule.cost * sum(v.weight for v in binding)
    return violations, cost


def evaluate_state(ctx: StateContext, rules=None, short_circuit=True):
    return _apply(rules if rules is not None else ctx.profile.rules("state"),
                  ctx, short_circuit)


def evaluate_transition(ctx: TransitionContext, rules=None, short_circuit=True):
    return _apply(rules if rules is not None else ctx.profile.rules("transition"),
                  ctx, short_circuit)
