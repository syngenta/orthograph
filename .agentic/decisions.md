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
