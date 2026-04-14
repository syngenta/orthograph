# Orthograph - Decision Log

## 2026-04-10: Architecture & Nomenclature

### Core Concept
- **GraphDataModel** is the single unified concept for representing graph data structure.
- Usable for any purpose: DB schema definition, query result validation, ETL contracts.
- Schema/projection distinction deferred to a later phase.

### Naming
- `NodeModel`: Base class for node type definitions (Pydantic BaseModel subclass)
- `RelationshipModel`: Base class for relationship type definitions
- `GraphDataModel`: Container that holds node types + relationship types + constraints
- `GraphValidator`: Engine that validates data against a GraphDataModel

### Type System
- Native Python types via Pydantic (no string-based type mapping)
- `Optional[T]` for optional properties
- `__optional__` ClassVar for entity-level optionality

### Optionality (3 levels)
1. **Property-level**: `Optional[str] = None` vs required `str`
2. **Entity-level**: `__optional__ = True` on NodeModel/RelationshipModel
3. **Cardinality-level**: `Cardinality.ZERO_OR_MORE` etc. on relationships

### Cardinality
- Named constants backed by min/max: `Cardinality.ONE`, `Cardinality.ZERO_OR_MORE`, etc.
- Custom via `CardinalitySpec(min=2, max=5)`

### Two input modes
1. Class-based: Python classes inheriting from NodeModel/RelationshipModel
2. YAML config: For configuration-driven schema definitions

### Backend-agnostic
- Core validation is DB-independent
- Extensions for Cypher, NetworkX, (future: RDF, GQL)
- Inspired by Pandera's multi-backend approach

### No backward compatibility
- Legacy code moved to `src/orthograph_legacy/` and `tests/legacy/`
- Clean start for the new implementation

### Tools landscape (key gaps filled)
- No existing Pydantic-native graph schema validation tool
- Neomodel: no Pydantic, Neo4j-only, runtime-only cardinality
- Neontology: Pydantic but no cardinality, no graph-wide validation
- Orthograph fills: Pydantic-native, DB-agnostic, cardinality, graph-wide validation

## 2026-04-10: Pre-commit Review and Architecture Refinements

### Validator API: `list` -> `Sequence` (covariant input types)
Pre-commit mypy revealed that `list[dict[str, Any] | NodeModel]` is invariant.
Users passing `list[dict[str, Any]]` (the common case) would get type errors.
Changed all public validator input parameters from `list[...]` to
`Sequence[...]` (from `collections.abc`). `Sequence` is covariant, so
`list[dict]` satisfies `Sequence[dict | NodeModel]`. Return types stay concrete.

### Test style: pytest functions over unittest classes
All tests refactored from `class TestX:` with `self` to plain `def test_x():`
functions. Imports moved to module level. Prefixed names for uniqueness
(e.g. `test_cardinality_spec_create_with_min_and_max`).

### mypy config: single source in mypy.ini
Removed duplicate `[tool.mypy]` from pyproject.toml. All mypy config lives
in mypy.ini exclusively. Added pydantic.mypy plugin, per-module overrides
for tests (relaxed), networkx extension (allow unimported Any), and
legacy code (ignored).

### Pre-commit dependencies
Added pytest, networkx, pyyaml, types-PyYAML to the mypy pre-commit
hook's additional_dependencies. Without these, mypy cannot resolve
`@pytest.fixture()` return types or networkx/yaml types.

### Ruff exclusions
Excluded `src/orthograph_legacy`, `notebooks`, `build` from ruff linting.
These are not active code and should not block the pre-commit pipeline.

### Removed stale `type: ignore` comments
The pydantic mypy plugin makes dynamic class creation in `io/yaml.py`
type-safe. Removed 4 unnecessary `# type: ignore` comments that were
suppressing non-existent errors.

## 2026-04-14: Extensions Redesign -- Two-Phase Architecture

### Problem
The original extensions (flat files: `introspector.py`, `adapter.py`, `_neo4j_common.py`)
mixed inspection logic with validation logic. Each backend produced `IntrospectedSchema`
dataclasses that were compared via `compare_schema()`. This was functional but:
- No shared interface (no ABC) across backends
- `IntrospectedSchema` was a plain dataclass, not serialisable or injectable
- Validation was tightly coupled to introspection (no way to inject external profiles)
- No property completeness metrics, no cardinality stats populated
- Duplicated logic across Neo4j/Memgraph introspectors

### Decision: Two-Phase Architecture (Inspect, then Validate)
Inspired by Soda Core (inspect-then-check) and SHACL (shapes graph vs. data graph):

- **Phase 1: Inspection** -- `GraphInspector` ABC with `inspect() -> GraphProfile`.
  Three implementations: `NetworkxInspector`, `Neo4jInspector`, `MemgraphInspector`.
- **Phase 2: Validation** -- `validate_profile(profile, model) -> ValidationResult`.
  The validator never touches the backend. Profiles are injectable, serialisable.

### `GraphProfile` as shared currency
A frozen Pydantic model with `NodeTypeProfile`, `RelationshipTypeProfile`,
`PropertyProfile` (with `completeness`, `observed_types`, `is_mandatory`),
`CardinalityStats`, and `ConstraintInfo`. Replaces the old `IntrospectedSchema`
dataclass. Richer data: counts, completeness, observed endpoint labels.

### `QueryStrategy` protocol (Neo4j)
Extensible strategy for Neo4j query generation. `ApocQueryStrategy` uses APOC
procedures; `CypherQueryStrategy` uses pure Cypher. Auto-detected, user-overridable.

### Module naming
No underscore-prefixed modules. Clear names: `models.py` (not `_base.py`),
`queries.py` (not `_queries.py`), `validation.py` (not `_validation.py`).

### Visualization moved to extensions
`depiction.py` moved to `extensions/visualization/mermaid.py`. Clean break,
no backward-compatible shim. All import sites updated.

### `schema_to_networkx()` kept in `networkx/conversion.py`
Useful utility for future converters. Prepares for a conversion extension
that can reshape data between formats.

## 2026-04-14: Undirected Relationship Semantics

### Problem
`__directed__ = False` was effectively metadata-only. It affected only Mermaid arrow
rendering (`---` vs `-->`) and Cypher MATCH patterns (`-` vs `->`). The rest of the
system ignored the flag:

- `GraphDataModel.get_outgoing/incoming_relationship_types()` -- only returned an undirected
  relationship as outgoing from its `__source_type__` and incoming to its `__target_type__`,
  not bidirectionally.
- `GraphValidator._check_referential_integrity()` -- strictly enforced `__source_uid__`
  must be `__source_type__` and `__target_uid__` must be `__target_type__`, even when
  the relationship was undirected. A reversed cross-type pair in the DB would be rejected.
- `GraphValidator._check_cardinality()` -- counted outgoing and incoming separately,
  even for undirected. This was semantically wrong (e.g. a node with 2 outgoing + 3
  incoming FRIEND_OF would be counted as 2 for cardinality, ignoring the 3 incoming).
- `CypherGenerator._rel_query()` (CREATE/MERGE) -- always emitted `->`, regardless of
  `__directed__`.
- Cypher parser `_check_endpoints()` and profile validator `_check_rel_endpoints()` --
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

### Error reporting for undirected type mismatches
When neither forward nor reverse endpoint ordering matches for an undirected relationship,
a single `WRONG_ENDPOINT_TYPE` error is emitted with a combined message listing both
expected endpoint types. For directed relationships, individual source/target errors are
reported as before.

### Problem
Visualization (`to_mermaid`) was placed inside `extensions/visualization/`
during the redesign. But visualization is not an extension in the same sense
as neo4j or networkx: it does not inspect or validate. It is a **consumer**
of orthograph's data structures (models, profiles, results).

### Decision: Move to top-level `src/orthograph/visualization/`
Visualization becomes its own subpackage at the same level as `core/`, `io/`,
and `extensions/`. Rationale:
- Different concern: rendering vs. inspecting/validating
- Different dependency profile (Jinja2, matplotlib vs. neo4j, networkx)
- Consumes outputs from both core (GraphDataModel) and extensions (GraphProfile,
  ValidationResult)
- `extensions/networkx/conversion.py` stays -- it produces a data object
  (nx.MultiDiGraph), not a visual format

### Renderer naming convention
Functions follow `{input_type}_to_{format}`:
- `model_to_mermaid(model: GraphDataModel) -> str`
- `profile_to_text(profile: GraphProfile) -> str`
- `result_to_text(result: ValidationResult) -> str`

### Implementation deferred to dedicated branch
The move and new renderers will be implemented on a separate branch
after the current extensions redesign is merged.
See `.agentic/visualization/plan.md` for the full plan.
