"""Every shipped comparison, one verb each.

Three intent-named verbs, each delegating to the comparison engine:

* :func:`profile_to_definition` — does an observed profile satisfy a declared
  definition? (US: validate live graph against the contract)
* :func:`profiles` — symmetric diff between two observed profiles (US 31,
  e.g. staging↔prod).
* :func:`definitions` — symmetric diff between two declared definitions (US 30,
  e.g. version↔version).

These delegate only — no comparison logic lives here. ``Rule`` is re-exported so
consumers can pass a custom ``rules=`` set without reaching into
``orthograph.comparison.*``.
"""

from collections.abc import Sequence

from orthograph.comparison.engine import (
    compare_definitions,
    compare_profile_to_definition,
    compare_profiles,
)
from orthograph.comparison.rules import Rule
from orthograph.diagnostics.result import ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_profile.models import GraphProfile


__all__ = ["Rule", "profile_to_definition", "profiles", "definitions"]


def profile_to_definition(
    profile: GraphProfile,
    definition: GraphDefinition,
    rules: Sequence[Rule] | None = None,
) -> ValidationResult:
    """Check whether ``profile`` satisfies the constraints in ``definition``.

    Operand: an observed profile against a declared definition. ``rules``
    overrides the default satisfaction rule set.
    """
    return compare_profile_to_definition(
        profile=profile, definition=definition, rules=rules
    )


def profiles(
    left: GraphProfile,
    right: GraphProfile,
    rules: Sequence[Rule] | None = None,
) -> ValidationResult:
    """Symmetric diff between two observed profiles (US 31).

    Operand: two profiles (e.g. staging↔prod). Emits ``INFO`` issues for
    one-sided or differing addresses. ``rules`` overrides the default diff set.
    """
    return compare_profiles(left=left, right=right, rules=rules)


def definitions(
    left: GraphDefinition,
    right: GraphDefinition,
    rules: Sequence[Rule] | None = None,
) -> ValidationResult:
    """Symmetric diff between two declared definitions (US 30).

    Operand: two definitions (e.g. version↔version). Emits ``INFO`` issues for
    one-sided or differing addresses. ``rules`` overrides the default diff set.
    """
    return compare_definitions(left=left, right=right, rules=rules)
