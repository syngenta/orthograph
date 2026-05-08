# ADR-007: Post-GQLAlchemy Review — API and Structure Decisions

**Date:** 2026-05-07
**Status:** Accepted
**Category:** extensions

## Trigger

Full code review after completing CAST-1233 (GQLAlchemy integration).
See `reviews/2026-05-07_post-gqlalchemy-review.md` for the full analysis.

## Decision: Shared `PropertySpecMixin` for Model Classes

`NodeModel` and `RelationshipModel` both define identical `get_property_specs()`,
`get_required_property_names()`, and `get_all_property_names()` classmethods.
These will be extracted to a shared mixin class.

**Rationale:** DRY principle. 30 lines duplicated verbatim. Bug fixes would
need to be applied in two places.

**Tradeoff:** Slightly more complex inheritance hierarchy (Mixin + BaseModel).
Acceptable because the mixin is pure logic with no state.

## Decision: Convenience Methods on `GraphDataModel` and `GraphValidator`

Adding `GraphDataModel.validate()`, `GraphDataModel.validate_profile()`,
and `GraphValidator.validate_node()` / `validate_relationship()` singular
methods. These are thin delegation wrappers.

**Rationale:** Reduces ceremony for the 80% use case. The verbose path
(`GraphValidator(model).validate([item])`) remains for advanced use.

**Tradeoff:** Slightly larger public API surface. Acceptable because
the methods are discoverable and self-explanatory.

## Decision: Keep `__source_uid__` / `__target_uid__` Dict Format as Primary

The magic-key dict format will remain the primary internal representation.
Tuple input `(src, tgt, label, props)` will be added as an **alternative**
input format, not a replacement.

**Rationale:** The dict format is used throughout the codebase (validator,
Cypher generator, result adapters, notebooks). Changing the canonical
format would be a breaking refactor. Adding tuple support is additive.

## Decision: Explicit `backend=` Parameter for GqlAlchemyClient

String-matching on class names is fragile. Adding an explicit `backend=`
parameter that defaults to auto-detection but can be overridden.

**Rationale:** Testability, robustness against GQLAlchemy API changes,
explicit over implicit.

## Decision: MemgraphQueries Intentionally Does NOT Implement QueryStrategy

The Memgraph schema procedures return all metadata in single calls (not
per-label), so the API shape genuinely differs from Neo4j's. This is
documented, not fixed.

**Rationale:** Forcing API alignment would either waste queries (calling
per-label when Memgraph gives all-at-once) or break the protocol contract
(accepting parameters it ignores). Documentation is the correct solution.

## Actions

- Epic/task breakdown: see `planning/overview.md`
- Detailed specs: see `planning/epics/E1–E4`
