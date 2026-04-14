# Orthograph -- Implementation Progress

## Current Status

**257 tests passing** | All pre-commit hooks green | 7 notebooks

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
| P10 | visualization/mermaid.py | done |
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

## Test Coverage: 257 tests

| Module | Tests |
|--------|-------|
| core/types | 26 |
| core/errors | 11 |
| core/node_model | 13 |
| core/relationship_model | 15 |
| core/graph_data_model | 27 (+8) |
| core/validator | 40 (+12) |
| io/yaml | 13 |
| extensions/models + validation | 30 (+3) |
| extensions/cypher/generator | 17 (+8) |
| extensions/cypher/parser | 26 (+8) |
| extensions/neo4j/inspector | 5 |
| extensions/neo4j/result_adapter | 10 |
| extensions/memgraph/inspector | 2 |
| extensions/networkx/inspector | 9 |
| extensions/networkx/conversion | 6 (+3) |
| extensions/visualization/mermaid | 6 (+2) |
| integration | 9 |

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
