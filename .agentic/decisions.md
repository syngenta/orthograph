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

## 2026-04-14: Cardinality Semantics -- ZERO_OR_MORE Is a Valid Constraint

### Trigger
User feedback questioned whether `ZERO_OR_MORE` (0..*) is semantically valid,
arguing that "zero means the relationship doesn't exist" and suggesting it
should always be `ONE_OR_MORE`.

### Finding
The current semantics are correct. Cardinality constrains the **instance count
per node**, not the existence of the relationship type in the schema. These are
orthogonal axes:
- `__optional__` controls whether the relationship type must appear at all
- `CardinalitySpec(min, max)` controls how many instances each node may have

`ZERO_OR_MORE` (0..*) is standard UML/ER/OWL notation meaning "optional
participation, unbounded." It is the correct permissive default for a schema
framework that must handle partial data (query results, ETL fragments).

`ONE_OR_MORE` (1..*) means mandatory participation -- every node must have at
least one instance. The two cardinalities model different business rules and
are not interchangeable.

### Design: Two Orthogonal Axes

| Axis | What it controls | Mechanism |
|---|---|---|
| **Entity-level optionality** | Whether the relationship *type* must appear at all in the data | `__optional__ = True/False` |
| **Cardinality** | How many instances each *individual node* may have | `CardinalitySpec(min, max)` |

**Use `ZERO_OR_MORE`** (the default) when validating partial query results,
optional relationships, or documenting what *can* exist without enforcing
participation.

**Use `ONE_OR_MORE`** when every node must participate (mandatory relationship),
validating canonical/complete data, or the business rule requires at least one
instance.

### Test gap identified and closed
Prior to this work, `Cardinality.ONE_OR_MORE` was only structurally tested
(min/max values) -- never exercised through `contains()` or `GraphValidator`.
`ZERO_OR_MORE.contains(0)` was also never asserted.  No test exercised
`__target_cardinality__` violations.  Seven new tests were added to close
these gaps across `test_types.py`, `test_relationship_model.py`, and
`test_validator.py`.

### Pre-commit mypy: `py.typed` marker
The pre-commit mypy hook ran in an isolated venv without the local package
installed.  Because `src/orthograph/py.typed` was missing, mypy treated all
orthograph exports as `Any`, causing ~49 `Class cannot subclass` false
positives on any commit touching test files.  Adding `py.typed` and the local
package (`.`) to `additional_dependencies` resolved this.

### Actions
- Expanded `Cardinality` class and per-constant docstrings in `core/types.py`
- Documented `__source_cardinality__` / `__target_cardinality__` defaults
  and their relationship to `__optional__` in `relationship_model.py`
- Added explanatory section with side-by-side `ZERO_OR_MORE` vs `ONE_OR_MORE`
  examples in notebook 03
- Added 7 tests: `contains()` for `ZERO_OR_MORE`/`ONE_OR_MORE`, side-by-side
  validator comparison, target cardinality violation, default cardinality assertion
- Added `py.typed` marker and fixed pre-commit mypy configuration

## 2026-04-17: GQLAlchemy Integration

### Problem

Orthograph defines graph schemas and validates data, but has no OGM (object
persistence/retrieval) and no general-purpose query builder. Users who need
both strict schema governance and database interaction must manually wire
Orthograph validation around a separate database client. GQLAlchemy provides
a mature OGM and fluent query builder for Memgraph and Neo4j but lacks
schema validation, cardinality constraints, endpoint enforcement, and Cypher
static analysis.

### Decision: GQLAlchemy as an optional Orthograph extension

GQLAlchemy is added as an **optional dependency** and exposed through a new
extension module `orthograph.extensions.gqlalchemy`. This follows the same
pattern as the existing `neo4j`, `memgraph`, and `networkx` extensions.

**Key architectural choices:**

1. **Only Orthograph is modified.** GQLAlchemy is treated as an external
   dependency. No fork, no patches.

2. **Orthograph models are the single source of truth.** Users define
   `NodeModel` / `RelationshipModel` classes. GQLAlchemy `Node` / `Relationship`
   classes are auto-generated at runtime via `codegen.py`. Users never define
   or import GQLAlchemy model classes directly.

3. **Extension module, not deep wrapping.** The integration lives in
   `orthograph.extensions.gqlalchemy/` and is only imported when needed.
   Core Orthograph has zero awareness of GQLAlchemy.

4. **Bridge via plain dicts.** Orthograph (Pydantic v2) and GQLAlchemy
   (Pydantic v1) model hierarchies cannot share a base class. All data
   exchange happens through plain Python dicts. The codegen layer translates
   Orthograph model metadata into GQLAlchemy class definitions. The result
   adapter layer converts GQLAlchemy objects back into validation dicts.

5. **Schema features Orthograph has but GQLAlchemy lacks** (cardinality,
   endpoint types, directed/undirected, entity optionality) are enforced
   by Orthograph's validation layer, not by the generated GQLAlchemy classes.

6. **Both Memgraph and Neo4j** are supported via GQLAlchemy's vendor
   abstraction (`Memgraph` and `Neo4j` classes both implement `DatabaseClient`).

### Deferred decisions

| Decision | Status | Notes |
|---|---|---|
| Cardinality enforcement on write | Deferred | Requires pre-save DB query for current count. Performance cost unclear. Can be added as opt-in `enforce_cardinality=True` later. |
| Result validation default | Decided: opt-in | `validate_results=False` by default on `execute_validated()`. Activated with `validate_results=True`. |
| Index/constraint auto-creation | Deferred | Not implemented in first version. Users use `CypherGenerator.generate_constraints()` or GQLAlchemy's `Field(unique=True, db=db)` directly. |

### Tradeoffs accepted

| Tradeoff | Accepted cost | Benefit |
|---|---|---|
| Dynamic class generation via `type()` | Harder to debug, no IDE autocomplete on generated classes | Users never see generated classes; they use Orthograph models |
| Pydantic v1/v2 coexistence | Runtime complexity, potential subtle bugs | No fork of GQLAlchemy needed; clean separation |
| Schema features enforced outside GQLAlchemy | GQLAlchemy's own validation is bypassed/redundant | Orthograph's richer validation is always the authority |
| GQLAlchemy's `Extra.allow` on models | Generated classes accept undeclared properties | Orthograph validates BEFORE save; extra props are caught |
| No re-implementation of query builder | Users must import `gqlalchemy.match/create/merge` | Full access to GQLAlchemy's query builder; no maintenance burden |

### Alternatives considered

1. **Fork GQLAlchemy and add Pydantic v2 + validation** -- Rejected.
   Maintenance burden of a fork. GQLAlchemy's OGM design is fundamentally
   different from Orthograph's schema-first approach.

2. **Build OGM from scratch in Orthograph** -- Rejected for now. Large
   effort. GQLAlchemy already handles connection management, Cypher
   generation, result deserialization, and multi-vendor support.

3. **Use Neomodel instead of GQLAlchemy** -- Rejected. Neomodel is Neo4j-only,
   not Pydantic-based, and has a heavier ORM abstraction that conflicts with
   Orthograph's schema-first philosophy.

4. **Lightweight bridge (users wire both libraries manually)** -- Rejected
   in favor of extension module. A bridge requires users to understand both
   APIs and handle conversion themselves. The extension provides a cohesive
   experience.

5. **Deep wrapping (hide GQLAlchemy completely)** -- Rejected. Would require
   re-implementing the query builder API surface. The extension module exposes
   GQLAlchemy's query builder directly and adds validation on top.

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pydantic v1/v2 conflict | Low | High | Both coexist since Pydantic 2.0. Test in CI. |
| GQLAlchemy API changes | Medium | Medium | Pin `>= 1.6, < 2.0`. All imports behind extension boundary. |
| `pymgclient` build issues | Medium | Medium | Only needed for Memgraph. Document clearly. |
| Dynamic class generation breaks | Low | Medium | Comprehensive codegen tests. |

### References

- GQLAlchemy docs: https://memgraph.github.io/gqlalchemy/
- GQLAlchemy source: https://github.com/memgraph/gqlalchemy
- Detailed integration plan: `.agentic/extensions/gqlalchemy.md`
- Target behavior notebook: `notebooks/09_gqlalchemy_integration.ipynb`

## 2026-05-07: Post-GQLAlchemy Review -- API & Structure Decisions

### Trigger

Full code review after completing CAST-1233 (GQLAlchemy integration).
See `reviews/2026-05-07_post-gqlalchemy-review.md` for the full analysis.

### Decision: Shared `PropertySpecMixin` for model classes

`NodeModel` and `RelationshipModel` both define identical `get_property_specs()`,
`get_required_property_names()`, and `get_all_property_names()` classmethods.
These will be extracted to a shared mixin class.

**Rationale:** DRY principle. 30 lines duplicated verbatim. Bug fixes would
need to be applied in two places.

**Tradeoff:** Slightly more complex inheritance hierarchy (Mixin + BaseModel).
Acceptable because the mixin is pure logic with no state.

### Decision: Convenience methods on `GraphDataModel` and `GraphValidator`

Adding `GraphDataModel.validate()`, `GraphDataModel.validate_profile()`,
and `GraphValidator.validate_node()` / `validate_relationship()` singular
methods. These are thin delegation wrappers.

**Rationale:** Reduces ceremony for the 80% use case. The verbose path
(`GraphValidator(model).validate([item])`) remains for advanced use.

**Tradeoff:** Slightly larger public API surface. Acceptable because
the methods are discoverable and self-explanatory.

### Decision: Keep `__source_uid__` / `__target_uid__` dict format as primary

The magic-key dict format will remain the primary internal representation.
Tuple input `(src, tgt, label, props)` will be added as an **alternative**
input format, not a replacement.

**Rationale:** The dict format is used throughout the codebase (validator,
Cypher generator, result adapters, notebooks). Changing the canonical
format would be a breaking refactor. Adding tuple support is additive.

### Decision: Explicit `backend=` parameter for GqlAlchemyClient

String-matching on class names is fragile. Adding an explicit `backend=`
parameter that defaults to auto-detection but can be overridden.

**Rationale:** Testability, robustness against GQLAlchemy API changes,
explicit over implicit.

### Decision: MemgraphQueries intentionally does NOT implement QueryStrategy

The Memgraph schema procedures return all metadata in single calls (not
per-label), so the API shape genuinely differs from Neo4j's. This is
documented, not fixed.

**Rationale:** Forcing API alignment would either waste queries (calling
per-label when Memgraph gives all-at-once) or break the protocol contract
(accepting parameters it ignores). Documentation is the correct solution.

### Decision: Progressive disclosure structure for `.agentic/`

Restructured `.agentic/` to separate:
- `reviews/` -- timestamped code review records
- `planning/` -- epics and tasks derived from reviews
- `archive/` -- superseded documents
- Root files -- current-state documents (index, progress, decisions, roadmap)

**Rationale:** A developer or agent should be able to answer "where are we?"
(progress), "where are we going?" (planning/), "why was this decided?"
(decisions), and "what was found?" (reviews/) without reading everything.

### Actions

- Epic/task breakdown: see `planning/overview.md`
- Detailed specs: see `planning/epics/E1-E4`
