"""Rule registry. Importing this package registers every rule."""

from . import state, transition  # noqa: F401  (import side effect is the point)
from .registry import (  # noqa: F401
    REGISTRY,
    Profile,
    Rule,
    StateContext,
    TransitionContext,
    Violation,
    evaluate_state,
    evaluate_transition,
)
