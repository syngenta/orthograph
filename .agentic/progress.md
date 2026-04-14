# Orthograph -- Implementation Progress

## Current Status

**221 tests passing** | All pre-commit hooks green | 7 notebooks

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

## Test Coverage: 221 tests

| Module | Tests |
|--------|-------|
| core/types | 26 |
| core/errors | 11 |
| core/node_model | 13 |
| core/relationship_model | 15 |
| core/graph_data_model | 19 |
| core/validator | 28 |
| io/yaml | 13 |
| extensions/models + validation | 27 |
| extensions/cypher/generator | 9 |
| extensions/cypher/parser | 18 |
| extensions/neo4j/inspector | 5 |
| extensions/neo4j/result_adapter | 10 |
| extensions/memgraph/inspector | 2 |
| extensions/networkx/inspector | 9 |
| extensions/networkx/conversion | 3 |
| extensions/visualization/mermaid | 4 |
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
