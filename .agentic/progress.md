# Orthograph -- Implementation Progress

## Current Status

**307 tests passing** | All pre-commit hooks green | 8 notebooks

## Milestones

### Core (2026-04-10)

| # | Milestone | Status |
|---|-----------|--------|
| M0 | Project setup | done |
| M1 | Core types (Cardinality, type utils) | done |
| M2 | NodeModel & RelationshipModel | done |
| M3 | GraphDataModel container | done |
| M4 | GraphValidator engine | done |
| M5 | Structured error reporting | done |
| M6 | YAML I/O | done |
| M7 | Cypher query generation | done |
| M8 | Cypher query parser (graphglot) | done |
| M9 | Public API + integration tests | done |

### Extensions Redesign (2026-04-14)

| # | Milestone | Status |
|---|-----------|--------|
| P0 | Shared test fixtures (conftest.py) | done |
| P1 | models.py -- GraphProfile + sub-models | done |
| P2 | base.py -- GraphInspector ABC | done |
| P3 | validation.py -- validate_profile() | done |
| P4 | networkx/inspector.py | done |
| P5 | networkx/conversion.py | done |
| P6 | neo4j/queries.py -- QueryStrategy protocol | done |
| P7 | neo4j/inspector.py | done |
| P8 | neo4j/result_adapter.py | done |
| P9 | memgraph/queries.py + inspector.py | done |
| P10 | visualization/mermaid.py (since moved to top-level) | done |
| P11 | Cypher carry-forward | done |
| P12 | Cleanup + integration tests | done |
| P13 | Notebooks (NB06 rewrite, NB07 new) | done |

### Undirected Relationship Semantics (2026-04-14)

| # | Milestone | Status |
|---|-----------|--------|
| U1 | Audit `__directed__` behavior across all subsystems | done |
| U2 | Fix `GraphDataModel` outgoing/incoming lookups for undirected | done |
| U3 | Fix `GraphValidator` referential integrity for undirected | done |
| U4 | Fix `GraphValidator` cardinality to combine both directions | done |
| U5 | Fix `CypherGenerator` CREATE/MERGE to use `-` for undirected | done |
| U6 | Fix Cypher parser endpoint check to accept reversed endpoints | done |
| U7 | Fix `validate_profile()` endpoint check for undirected | done |
| U8 | Expand tests (+36 tests across all affected modules) | done |
| U9 | Expand notebooks (NB01, NB02, NB05) | done |

### Documentation: Cardinality Semantics (2026-04-14)

| # | Milestone | Status |
|---|-----------|--------|
| D1 | Expand Cardinality docstrings in core/types.py | done |
| D2 | Document cardinality defaults in relationship_model.py | done |
| D3 | Expand notebook 03 with ZERO_OR_MORE vs ONE_OR_MORE examples | done |
| D4 | Add decision entry to decisions.md | done |
| D5 | Add cardinality semantic tests (contains, validator, target cardinality) | done |

### Visualization Package Refactoring (2026-04-15)

| # | Milestone | Status |
|---|-----------|--------|
| V1 | Create `src/orthograph/visualization/` package | done |
| V2 | Move `to_mermaid` to new location, rename to `model_to_mermaid` | done |
| V3 | Delete `extensions/visualization/` | done |
| V4 | Update all imports (tests, integration, notebooks) | done |
| V5 | Move and update tests to `tests/visualization/` | done |
| V6 | Enrich `model_to_mermaid` (cardinality, required/optional, UID) | done |
| V7 | Implement `model_to_text` (plain text schema table) | done |
| V8 | Implement `profile_to_text` (profile with counts, completeness) | done |
| V9 | Implement `result_to_text` (severity-coded validation summary) | done |
| V10 | Implement `render()` dispatcher | done |
| V11 | Implement `display_mermaid()` (inline Jupyter rendering via mermaid.ink) | done |
| V12 | Reorganise notebooks: NB06 (NetworkX inspect/validate), NB08 (Visualization) | done |

## Test Coverage: 307 tests

| Module | Tests |
|--------|-------|
| core/types | 29 |
| core/errors | 11 |
| core/node_model | 13 |
| core/relationship_model | 15 |
| core/graph_data_model | 27 |
| core/validator | 44 |
| io/yaml | 13 |
| extensions/models + validation | 30 |
| extensions/cypher/generator | 17 |
| extensions/cypher/parser | 26 |
| extensions/neo4j/inspector | 5 |
| extensions/neo4j/result_adapter | 10 |
| extensions/memgraph/inspector | 2 |
| extensions/networkx/inspector | 9 |
| extensions/networkx/conversion | 6 |
| visualization/mermaid | 16 |
| visualization/text | 23 |
| visualization/render | 8 |
| integration | 10 |

## Key Design Decisions

See `decisions.md` for the full log. Summary of active decisions:

- `__optional__` defaults to `True` -- model defines what CAN exist
- `Sequence` over `list` for validator input parameters (covariant)
- Cypher parser: strategy pattern with `GraphglotParser` as default
- Two-phase extension architecture: inspect -> `GraphProfile` -> validate
- `QueryStrategy` protocol for Neo4j APOC vs pure-Cypher switching
- Duck-typed neo4j driver objects (no hard import of `neo4j` package)
- Pydantic frozen models for all profile/report data classes
- Shared test fixtures in `conftest.py` (no model duplication across tests)
- Undirected relationships: either endpoint direction is semantically valid; cardinality counts both directions combined; Cypher uses `-` (no arrow)
- `ZERO_OR_MORE` (0..*) is a valid cardinality distinct from `ONE_OR_MORE` (1..*); cardinality constrains per-node instance counts, not relationship type existence (which is controlled by `__optional__`)
- `display_mermaid()` soft-imports IPython at call time; `profile_to_mermaid` was not implemented -- profiles are statistical summaries, Mermaid diagrams represent schema structure only
