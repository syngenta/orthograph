# ADR-004: Undirected Relationships and Visualization Package

**Date:** 2026-04-14
**Status:** Accepted
**Category:** core

## Part A: Undirected Relationship Semantics

### Problem

`__directed__ = False` was effectively metadata-only. It affected only Mermaid arrow
rendering (`---` vs `-->`) and Cypher MATCH patterns (`-` vs `->`). The rest of the
system ignored the flag:

- `GraphDataModel.get_outgoing/incoming_relationship_types()` — only returned an undirected
  relationship as outgoing from its `__source_type__` and incoming to its `__target_type__`,
  not bidirectionally.
- `GraphValidator._check_referential_integrity()` — strictly enforced `__source_uid__`
  must be `__source_type__` and `__target_uid__` must be `__target_type__`, even when
  the relationship was undirected. A reversed cross-type pair in the DB would be rejected.
- `GraphValidator._check_cardinality()` — counted outgoing and incoming separately,
  even for undirected. This was semantically wrong (e.g. a node with 2 outgoing + 3
  incoming FRIEND_OF would be counted as 2 for cardinality, ignoring the 3 incoming).
- `CypherGenerator._rel_query()` (CREATE/MERGE) — always emitted `->`, regardless of
  `__directed__`.
- Cypher parser `_check_endpoints()` and profile validator `_check_rel_endpoints()` —
  both did strict directional endpoint matching.

### Decision: `directed=false` means either endpoint order is valid

For an undirected relationship `R` with `__source_type__ = A`, `__target_type__ = B`:

- Both `A->B` and `B->A` are valid in data and in queries.
- Cardinality counts total connections (outgoing + incoming) per node per rel type.
- Cypher MATCH and CREATE/MERGE both use `-` (no arrow).
- `get_outgoing_relationship_types(A)` and `get_outgoing_relationship_types(B)` both
  return `R`. Same for incoming lookups.
- For same-type endpoints (`A == B`), no duplicates are returned from lookups (the first
  branch `source_type is node_type` always catches it before the undirected `elif`).

### Error Reporting for Undirected Type Mismatches

When neither forward nor reverse endpoint ordering matches for an undirected relationship,
a single `WRONG_ENDPOINT_TYPE` error is emitted with a combined message listing both
expected endpoint types. For directed relationships, individual source/target errors are
reported as before.

---

## Part B: Visualization Package — Move to Top-Level

### Problem

Visualization (`to_mermaid`) was placed inside `extensions/visualization/`
during the redesign (ADR-003). But visualization is not an extension in the same sense
as neo4j or networkx: it does not inspect or validate. It is a **consumer**
of orthograph's data structures (models, profiles, results).

### Decision: Move to top-level `src/orthograph/visualization/`

Visualization becomes its own subpackage at the same level as `core/`, `io/`,
and `extensions/`. Rationale:

- Different concern: rendering vs. inspecting/validating
- Different dependency profile (Jinja2, matplotlib vs. neo4j, networkx)
- Consumes outputs from both core (GraphDataModel) and extensions (GraphProfile,
  ValidationResult)
- `extensions/networkx/conversion.py` stays — it produces a data object
  (nx.MultiDiGraph), not a visual format

### Renderer Naming Convention

Functions follow `{input_type}_to_{format}`:

- `model_to_mermaid(model: GraphDataModel) -> str`
- `profile_to_text(profile: GraphProfile) -> str`
- `result_to_text(result: ValidationResult) -> str`

### Implementation

Implemented on branch `CAST-1224-change-architecture-of-visualization-module`.
See `planning/epics/E5_visualization.md` for the full implementation record.
