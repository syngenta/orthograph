# Orthograph -- Agent & Developer Documentation Index

> Read this file first. It tells you what exists and where to find it.

## What Is Orthograph?

Pydantic-native graph data model definition and validation.
Like Pandera for DataFrames, but for graph data structures.

**Version:** 0.1.0-alpha | **Python:** >= 3.10 | **Tests:** 257 | **License:** Private

## Quick Reference

| What you need | Where to look |
|---------------|---------------|
| Project status, milestones, test counts | `progress.md` |
| Why a decision was made | `decisions.md` |
| How extensions work (inspect/validate pattern) | `extensions/overview.md` |
| Neo4j-specific details (queries, APOC, driver) | `extensions/neo4j.md` |
| Memgraph-specific details | `extensions/memgraph.md` |
| Cypher parser and generator details | `extensions/cypher.md` |
| Visualization requirements and plan | `visualization/plan.md` |
| What's not yet implemented, future plans | `roadmap.md` |
| Superseded plans (historical reference only) | `archive/` |

## Documentation Structure

```
.agentic/
├── index.md                 # THIS FILE -- start here
├── decisions.md             # Tier 1: architectural decisions log
├── progress.md              # Tier 1: milestones, test counts, status
├── roadmap.md               # Tier 1: future work, open questions
├── extensions/              # Tier 2: extensions area
│   ├── overview.md          #   Architecture, abstractions, validation codes
│   ├── neo4j.md             #   Tier 3: Neo4j inspector, queries, result adapter
│   ├── memgraph.md          #   Tier 3: Memgraph inspector, differences
│   └── cypher.md            #   Tier 3: Cypher generator + parser
├── visualization/           # Tier 2: visualization area
│   └── plan.md              #   Requirements, decisions, implementation plan
└── archive/                 # Historical reference only
    └── extensions_plan_v1.md
```

**For agents:** Read `index.md` -> read the relevant area doc -> drill into tier 3 only if needed. Maximum 3 files for any question.

## Package Layout (current)

```
src/orthograph/
├── __init__.py                        # Public API: core classes
├── core/
│   ├── types.py                       # CardinalitySpec, Cardinality, EntityType, Severity
│   ├── errors.py                      # ValidationIssue, ValidationResult, GraphValidationError
│   ├── node_model.py                  # NodeModel (Pydantic BaseModel)
│   ├── relationship_model.py          # RelationshipModel (Pydantic BaseModel)
│   ├── graph_data_model.py            # GraphDataModel container
│   └── validator.py                   # GraphValidator engine (data-level validation)
├── io/
│   └── yaml.py                        # YAML load/save with dynamic class generation
└── extensions/
    ├── models.py                      # GraphProfile + sub-models (inspection output)
    ├── base.py                        # GraphInspector ABC
    ├── validation.py                  # validate_profile() (profile-vs-model comparison)
    ├── cypher/
    │   ├── generator.py               # CypherGenerator (MERGE, CREATE, MATCH)
    │   └── parser.py                  # parse_cypher, validate_cypher (graphglot)
    ├── neo4j/
    │   ├── inspector.py               # Neo4jInspector (APOC + fallback)
    │   ├── queries.py                 # QueryStrategy protocol + implementations
    │   └── result_adapter.py          # validate_result() for driver output
    ├── memgraph/
    │   ├── inspector.py               # MemgraphInspector
    │   └── queries.py                 # Memgraph-specific query strings
    ├── networkx/
    │   ├── inspector.py               # NetworkxInspector
    │   └── conversion.py              # schema_to_networkx()
    └── visualization/                 # PLANNED MOVE: -> src/orthograph/visualization/
        └── mermaid.py                 # to_mermaid() (see visualization/plan.md)
```

**Planned change:** `extensions/visualization/` will move to a top-level
`src/orthograph/visualization/` package. See `visualization/plan.md` for
the requirements, decisions, and implementation plan.

## Core Concepts (one-paragraph each)

**GraphDataModel** -- The schema definition. Declares node types, relationship types, their properties, cardinality, and constraints. Validates its own structural consistency on creation. Defined via Python classes (Pydantic) or YAML files.

**GraphValidator** -- Validates actual graph data (dicts or model instances) against a `GraphDataModel`. Checks: labels, property types, required fields, extra properties, referential integrity, cardinality, entity presence. This is the core data-level validator.

**GraphProfile** -- The output of graph inspection. A frozen Pydantic model describing what a graph actually contains: node/relationship types, property completeness, observed types, cardinality stats. Backend-agnostic, serialisable, injectable.

**GraphInspector** -- ABC with one method: `inspect() -> GraphProfile`. Implemented by `NetworkxInspector`, `Neo4jInspector`, `MemgraphInspector`. Produces a `GraphProfile` from the respective backend.

**validate_profile()** -- Compares a `GraphProfile` against a `GraphDataModel`. Reports missing/unexpected types, property mismatches, completeness issues, endpoint violations, cardinality violations. Returns `ValidationResult`.

## Two-Phase Architecture (extensions)

```
Phase 1: INSPECTION                     Phase 2: VALIDATION
GraphInspector.inspect()  ──>  GraphProfile  +  GraphDataModel  ──>  ValidationResult
                                    │                                       │
                              VISUALIZATION                          VISUALIZATION
                              (profile renderers)                    (result renderers)
```

Phase 1 produces data. Phase 2 compares it against a model. Visualization is a
**consumer** of both phases -- it renders models, profiles, and results for humans.

## Notebooks

| # | Title | Executable? |
|---|-------|-------------|
| 01 | Defining a Graph Data Model | Yes |
| 02 | Validating Graph Data | Yes |
| 03 | Optionality and Cardinality | Yes |
| 04 | YAML Configuration | Yes |
| 05 | Cypher Query Generation | Yes |
| 06 | Graph Inspection and Visualization | Yes |
| 07 | Neo4j End-to-End (Reference) | No (requires Neo4j) |
