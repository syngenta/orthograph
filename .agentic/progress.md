# Orthograph - Implementation Progress

## Milestones

| # | Milestone | Status | Date |
|---|-----------|--------|------|
| M0 | Project setup | done | 2026-04-10 |
| M1 | Core types (Cardinality, type utils) | done | 2026-04-10 |
| M2 | NodeModel & RelationshipModel | done | 2026-04-10 |
| M3 | GraphDataModel container | done | 2026-04-10 |
| M4 | GraphValidator engine | done | 2026-04-10 |
| M5 | Structured error reporting | done | 2026-04-10 |
| M6 | YAML I/O | done | 2026-04-10 |
| M7 | Cypher query generation | done | 2026-04-10 |
| M8 | NetworkX extension | done | 2026-04-10 |
| M9 | Depiction (Mermaid) | done | 2026-04-10 |
| M10 | Public API + integration tests | done | 2026-04-10 |
| E1 | Shared DB introspection types + compare_schema | done | 2026-04-12 |
| E4 | Cypher query parser (graphglot strategy) | done | 2026-04-12 |
| E5 | Neo4j driver result validator | done | 2026-04-12 |
| E2 | Neo4j database schema introspector | done | 2026-04-12 |
| E3 | Memgraph database schema introspector | done | 2026-04-12 |

## Test Coverage: 205 tests

| Module | Tests |
|--------|-------|
| core/types | 26 |
| core/errors | 11 |
| core/node_model | 13 |
| core/relationship_model | 15 |
| core/graph_data_model | 19 |
| core/validator | 28 |
| io/yaml | 13 |
| extensions/cypher | 9 |
| extensions/networkx | 6 |
| extensions/neo4j_common | 13 |
| extensions/cypher_parser | 18 |
| extensions/result_validator | 10 |
| extensions/neo4j_introspector | 7 |
| extensions/memgraph_introspector | 4 |
| depiction | 4 |
| integration | 9 |

## Architecture

```
orthograph/
├── __init__.py               # Public API: core classes exported
├── core/
│   ├── types.py              # CardinalitySpec, Cardinality, EntityType, Severity, TypeInfo
│   ├── errors.py             # ValidationIssue, ValidationResult, GraphValidationError
│   ├── node_model.py         # NodeModel base class
│   ├── relationship_model.py # RelationshipModel base class
│   ├── graph_data_model.py   # GraphDataModel container
│   └── validator.py          # GraphValidator engine
├── io/
│   └── yaml.py               # YAML loading/saving with dynamic class generation
├── extensions/
│   ├── _shared/              # Shared DB introspection types (no external deps)
│   │   ├── schema_types.py   # IntrospectedSchema, PropertyInfo, ConstraintInfo
│   │   └── schema_compare.py # compare_schema(), db_type_to_python()
│   ├── cypher/               # Cypher language (depends: graphglot)
│   │   ├── generator.py      # CypherGenerator (MERGE, CREATE, MATCH)
│   │   └── parser.py         # CypherParserStrategy, GraphglotParser, validate_cypher
│   ├── neo4j/                # Neo4j specific (depends: neo4j driver at runtime)
│   │   ├── introspector.py   # Neo4jSchemaIntrospector (APOC + fallback)
│   │   └── result_adapter.py # node_to_dict, rel_to_dict, validate_result
│   ├── memgraph/             # Memgraph specific (depends: neo4j driver at runtime)
│   │   └── introspector.py   # MemgraphSchemaIntrospector
│   └── networkx/             # NetworkX (depends: networkx)
│       └── adapter.py        # schema_to_networkx, validate_networkx_graph
└── depiction.py              # Mermaid diagram generation
```

## Key Design Decisions

- **__optional__ defaults to True**: Model defines what CAN exist. Set `__optional__ = False` to require presence.
- **Sequence over list for inputs**: Validator uses covariant `Sequence` for parameters.
- **Cypher parser strategy pattern**: `CypherParserStrategy` protocol with `GraphglotParser` default. Swappable.
- **Duck-typed neo4j objects**: Result validator uses structural checks (`_is_node`, `_is_relationship`) instead of importing `neo4j.graph.Node` directly. Works with any driver-compatible objects.
- **Neo4j APOC fallback**: Tries APOC procedures first for rich metadata (types, mandatory), falls back to pure Cypher per-label scanning.
- **Separate Neo4j/Memgraph extensions**: Different Cypher dialects require separate introspection queries, but both produce the shared `IntrospectedSchema` type.
- **Multi-label resolution**: Picks the model-matching label from multi-label nodes. Falls back to first alphabetically.
