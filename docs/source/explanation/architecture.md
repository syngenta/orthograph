# Architecture Overview

Orthograph is a **contract and governance layer** for property-graph
applications. It sits *above* graph databases, drivers, and ORMs — it does not
replace any of them. The database still enforces its constraints, the driver
still executes, an ORM (if used) still maps objects. Orthograph adds the one
thing none of those layers provide: a single declared contract for the graph,
and the machinery to keep the queries and the live database honest against it.

This page is the high-level map. It explains *where* Orthograph lives in a
stack, *how* its public surface is organised, and *what* each internal area is
responsible for — at the level of modules, not functions. For a deeper
file-by-file map of the source tree, see the project's `.agentic/CONTEXT.md`.

---

## The three-layer stack

Orthograph owns the middle layer of a three-layer governance stack:

```{mermaid}
flowchart TD
    ONT["**Ontology**\nDomain experts describe what entities\nand relationships exist"]
    DEF["**Graph Definition**\n*(ORTHOGRAPH)*\nDeclares the contract in Python or YAML:\nnodes · relationships · properties · cardinalities"]
    SCH["**Schema / Database**\nWhat the live database enforces:\nindexes · constraints · observed structure"]

    ONT -->|"consumed informally —\ndomain experts inform contract decisions"| DEF

    DEF -->|"drift detection →\nvalidate the query catalogue"| QS["**Query Set**\nTyped Cypher catalogue"]
    QS -->|"← drift detection"| DEF

    DEF -->|"drift detection →\ninspect, then compare"| SCH
    SCH -->|"← drift detection"| DEF
```

The graph definition is the **single declared truth**. Orthograph continuously
checks the two layers around it *against* that truth, in both directions:

- **Query set ↔ Graph definition.** Every registered query is checked — its
  labels, relationship types, property accesses, and parameter shapes — so a
  query that has drifted away from the contract (a renamed label, a removed
  property, a changed endpoint) is caught at build time, **without executing the
  query**.
- **Database schema ↔ Graph definition.** A live database is profiled into a
  vendor-free snapshot, and that snapshot is reconciled against the declaration,
  surfacing drift between what the contract says and what the database actually
  holds.

Orthograph never manages ontologies or database schemas directly. It encodes
the ontological intent it receives from domain experts and produces schema
artefacts — validated queries, typed catalogues, constraint statements — for the
layers below. It is **not a migration tool**: it detects drift, it never applies
changes to a database.

---

## Two validation engines

A recurring source of confusion is that Orthograph validates in two genuinely
different ways, and they must not be merged. They serve different use cases and
surface as two distinct verbs.

| Engine | Subject | Question it answers | Public verb |
|---|---|---|---|
| **Data validation** | raw, in-memory records | "Does *this data I hold in hand* conform to the contract?" | `orthograph.definition.validate_data` |
| **Comparison** | aggregated database profiles | "Does *the live database* (a profile) match the contract?" | `orthograph.compare.profile_to_definition` |

The first engine works **record by record** — it is the pre-write / post-read
gate that stops invalid data reaching persistence. The second engine works on a
**point-in-time profile** of an entire database — type distributions,
completeness statistics, cardinality measurements — and reports drift classified
by severity (breaking, warning, informational).

They share the same result currency (a categorised result object) but answer
different questions on different inputs, so they remain two separate engines
rather than one overloaded one.

---

## The seven-module public surface

The consumer-facing surface is seven root capability modules plus a Cypher
language tool. Every name a consumer imports comes from one of these; nothing
below them is part of the public contract. Both import styles are fully
type-safe:

```python
# attribute access — notebooks / interactive
import orthograph
orthograph.definition.GraphDefinition

# direct from-import — library code / type checkers
from orthograph.definition import GraphDefinition, NodeModel
```

| Module | Capability |
|---|---|
| `orthograph.definition` | Declare the contract: `NodeModel`, `RelationshipModel`, `GraphDefinition`, and in-memory data validation. |
| `orthograph.profile` | Inspect a live database or in-memory graph into a vendor-free `GraphProfile`. |
| `orthograph.compare` | Reconcile any two artefacts of the mirror: profile vs definition, definition vs definition, profile vs profile. |
| `orthograph.queries` | Author, register, and validate a typed Cypher query catalogue against the contract. |
| `orthograph.execution` | Run typed queries against a backend under a caller-owned transaction. |
| `orthograph.discovery` | Detect which backends are installed and available. |
| `orthograph.rendering` | Render a definition, profile, or result for humans (text tables, Mermaid diagrams). |
| `orthograph.cypher` | The Cypher language tool: parse, validate, and generate Cypher — no live connection required. |

The dependency direction between these is strictly downward and acyclic:

```{mermaid}
flowchart TD
    DEF["**definition**\nDeclare the contract"]
    PRF["**profile**\nInspect → GraphProfile"]
    CMP["**compare**\nReconcile definition ↔ profile"]
    QRY["**queries**\nCatalogue CRUD & validation"]
    EXC["**execution**\nRun typed queries"]
    DIS["**discovery**\nDetect backends"]
    RND["**rendering**\nRender diagrams & tables"]
    CYP["**cypher**\nParse · validate · generate"]
    DIAG["**diagnostics** *(internal)*\nShared result currency"]

    DEF --> DIAG
    PRF --> DEF
    PRF --> DIAG
    CMP --> DEF
    CMP --> PRF
    CMP --> DIAG
    QRY --> DEF
    QRY --> CYP
    QRY --> DIAG
    EXC --> QRY
    DIS --> PRF
    RND --> DEF
    CYP --> DEF
    CYP --> DIAG
```

**How to read this diagram:**

- An arrow `A → B` means module A depends on module B (A imports from B).
- `diagnostics` is the dependency-free foundation — every check emits its
  findings (issues and results) from there.
- `definition` sits one level above: every other module depends on the declared
  contract, never the other way round.
- `cypher` is the standalone language tool; the profiling and comparison modules
  do not depend on it.

### One importable name per capability

Each root module is a **shallow re-export**: it gathers the public symbols from
the deeper internal areas and exposes them under a single importable name.
Nothing but import wiring lives in these root modules — no logic, no classes.

This has two consequences for consumers:

1. **One import site per capability.** You write `from orthograph.definition
   import NodeModel, GraphDefinition, validate_data` and never reach into the
   internal package layout.
2. **Internals can move without breaking you.** Symbols can be reorganised below
   the surface; the root re-export is the stable public name.

---

## The declared/observed mirror

The central organising idea is that Orthograph holds **two parallel descriptions
of the same graph**:

- the **declared side** — *what should be true* — authored by hand or loaded
  from YAML; store-independent;
- the **observed side** — *what is measured* — produced by inspecting a live
  database or an in-memory graph; empirical and dataset-specific.

Every comparable aspect of a graph has a **declared face** (a constraint) and an
**observed face** (a measurement), and both faces are reached by the **same
address** in the structure:

| Aspect | Address | Declared face | Observed face |
|---|---|---|---|
| node label | `(label)` | exists in the definition | a node-type profile |
| relationship type | `(source, label, target)` | exists in the definition | a relationship-type profile |
| property | `(label, property)` | a declared type/required flag | a measured completeness & type distribution |
| cardinality | `(label, rel_type)` | a declared cardinality | measured cardinality statistics |

Because both sides agree on the address, comparison is a **structural walk over
a shared key space**, not bespoke per-aspect matching code. Two payoffs follow:

- **Observed-side growth is free.** A new measurement with no declared twin (a
  histogram, a percentile, a distinct count) rides along, is serialised and
  displayed, but does not change the comparison — the walk only engages aspects
  that have a declared constraint to test against.
- **A new comparable aspect costs one rule, not one pipeline.** When an observed
  measurement gains a declared twin, it is expressed as a single rule and slots
  into the same walk.

This mirror is why the package topology below has a clean *declared side*,
*observed side*, and *bridge between them*.

---

## Internal areas (the contributor map)

The seven root modules are thin re-exports over the internal domain areas. This
is the layer contributors navigate; consumers do not import from it directly.
Each area is described at the level of its **responsibility**, not its internal
functions — for line-level detail, read the code and its docstrings, guided by
`.agentic/CONTEXT.md`.

| Internal area | Side of the mirror | Responsibility |
|---|---|---|
| `graph_definition/` | declared | The models you subclass, the container you instantiate, the declared property-type and cardinality system, and the in-memory data validator. |
| `graph_profile/` | observed | The vendor-free profile snapshot and the inspector interface that produces it; the vendor-neutral query fragments inspectors share. |
| `comparison/` | the bridge | The three comparison functions that reconcile any two artefacts drawn from the mirror, plus the rule set they walk. |
| `cypher/` | language tool | Query authoring, generation, syntax parsing, and semantic catalogue validation — everything Cypher-shaped that needs no live connection. |
| `diagnostics/` | foundation | The dependency-free result currency every check emits: issues, results, severities, and the project-wide error and logging entry points. |
| `backends/` | vendor adapters | Per-vendor inspector implementations (Neo4j, Memgraph, NetworkX, GQLAlchemy), each self-contained and guarded by its own optional dependency. |
| `io/` | support | YAML load/save for definitions and queries. |
| `visualization/` | support | The text-table and Mermaid renderers behind `orthograph.rendering`. |

### Backend isolation

Each vendor backend is independently installable through its own pip extra
(`neo4j`, `memgraph`, `networkx`, `gqlalchemy`). Importing one backend never
pulls in another's dependencies, and no backend imports another backend. The
Cypher language tool is a **core** dependency — it is always present, because
query authoring and validation are part of the public surface and not tied to
any one database. Connections are never owned: a driver or session is passed in
by the caller on every call, and inspectors are stateless.

---

## The dependency rule

The whole tree obeys one rule — **dependencies point strictly downward and never
form a cycle**:

```
backends/ ──► graph_profile/ ──► graph_definition/ ──► diagnostics/
cypher/  ─────────────────────► graph_definition/       ▲
comparison/ ─► graph_profile/                           │
               graph_definition/                        │
                    └──────────────────────────────────►┘
io/      ──► graph_definition/
visualization/ ──► graph_definition/
```

Four invariants hold, and are enforced by the test suite:

1. No upward imports — a deep internal area never imports from a root module.
2. No cross-backend edges — one vendor adapter never imports another.
3. `diagnostics/` has no internal dependencies — it is the foundation.
4. The package root only wires together the seven sibling capability modules.

The top-level layout *is* the domain model: a declared side, an observed side,
a comparison that bridges them, and a shared currency of findings they all
produce.
