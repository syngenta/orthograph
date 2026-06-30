# The Three-Layer Stack

Orthograph is a **contract and governance layer** for property-graph
applications. It does not store data, execute persistence, or manage a schema —
it sits *above* graph databases, drivers, and ORMs and adds the one thing none
of those layers provide: a single declared contract for the graph, plus the
machinery to keep the queries and the live database honest against it.

This page explains *where* that contract sits, *why* it is the centre of
gravity, and *how* Orthograph detects drift in both directions around it. It is
a positioning page — for the module map and the dependency rules, see the
[architecture overview](architecture.md).

---

## Three layers, one declared truth

A property-graph application spans three conceptual layers. They already exist
in every team's head; Orthograph's job is to make the **middle** one explicit
and machine-readable, then bind the layers on either side of it to that
declaration.

```{mermaid}
flowchart TD
    ONT["**Ontology**\nDomain experts describe what entities\nand relationships exist in the domain"]
    DEF["**Graph Definition**\n*(ORTHOGRAPH)*\nThe declared contract, in Python or YAML:\nnodes · relationships · properties · cardinalities"]
    SCH["**Schema / Database**\nWhat the live database enforces and holds:\nindexes · constraints · observed structure"]

    ONT -->|"consumed informally —\ndomain experts inform contract decisions"| DEF

    DEF -->|"drift detection →\nvalidate the query catalogue"| QS["**Query Set**\nTyped Cypher catalogue"]
    QS -->|"← drift detection"| DEF

    DEF -->|"drift detection →\ninspect, then compare"| SCH
    SCH -->|"← drift detection"| DEF
```

- **Ontology** — *what entities and relationships exist in this domain.* This is
  human knowledge held by domain experts. Orthograph does **not** manage or
  import ontologies (no OWL/RDF runtime integration). The ontology is consumed
  informally: experts inform the contract, and that intent is then encoded by
  hand.
- **Graph Definition** — *the contract Orthograph owns.* This is the single
  declared truth: the node types, relationship types, typed properties,
  cardinalities, and endpoints the application expects. It is authored once, in
  Python or YAML, and lives where the application can read it.
- **Schema / Database** — *what the store actually enforces and holds.* Indexes,
  uniqueness and existence constraints, and the structure that has accumulated in
  production. This layer is real but partial: it describes only what is enforced
  or currently observed, which is not the same as the application's intended
  contract.

The graph definition is the centre. Everything else is checked **against** it.

---

## Why the middle layer is missing today

Graph databases are powerful because they are schema-flexible — a team can add a
label, a relationship type, or a property without a migration. That flexibility
is valuable during exploration but compounds into three problems once the graph
becomes part of a production system. The three-layer stack exists to close all
three.

| Problem | Symptom | What the declared layer adds |
|---|---|---|
| **No declared contract** | The intended model — which labels and relationships are expected, which properties are required, what types and cardinalities hold — lives only in developers' heads. Several services write to the same graph with no shared authority. | A single source of truth the application can read, distinct from the database's own constraints (which enforce only a subset and live *below* the application). |
| **Raw query strings** | Cypher is scattered through the codebase as untyped strings. The dangerous failure is silent: rename a label and a hand-written query keeps parsing, keeps executing, and quietly returns wrong or empty results. | Typed, named queries that are validated against the contract before they ever reach the database. |
| **Silent drift** | New properties appear directly in production; a script adds a relationship type nobody updated the model for; staging and production diverge. There is no automated way to compare *should* against *is*. | Point-in-time profiling of the live database, reconciled against the declared contract and reported by severity. |

---

## Bidirectional drift detection

The contract is only useful if the layers around it cannot drift away from it
unnoticed. Orthograph checks **both** neighbours of the graph definition, in
both directions, and — crucially — **without executing any query against a live
database for the static checks**.

### Query Set ↔ Graph Definition

Every registered query is checked against the contract: its node labels,
relationship types, property accesses, endpoints, and parameter shapes. A query
that has drifted — a renamed label, a removed property, a changed endpoint — is
caught at **build time**, statically, before it can return a wrong result at
runtime.

This closes the silent-mismatch failure mode on four axes, none of which require
running the query:

| Axis | What is checked | Failure surfaced as |
|---|---|---|
| **Parameter validation** | A parametric query's parameters are typed and validated. | A parameter-binding error *before* any database call. |
| **Output declaration** | The result shape is declared and validated at materialisation. | A typed result list; a mismatch raises loudly instead of propagating bad data. |
| **Language correctness** | The query is parsed for Cypher syntactic validity. | A parse failure. |
| **Domain match** | Labels, relationship types, property accesses, and endpoints exist in the contract. | An unknown-label / unknown-rel-type / unknown-property / invalid-endpoint finding. |

Queries that cannot be inspected statically (imperative builder-only queries, or
non-Cypher backends) are reported **explicitly as unverifiable** rather than
silently treated as valid — so you always know precisely what was and was not
checked.

### Database Schema ↔ Graph Definition

A live database is inspected into a **vendor-free snapshot** — a profile of its
type distributions, property completeness, and cardinality measurements — and
that snapshot is reconciled against the declaration. Drift between what the
contract says and what the database actually holds is surfaced as structured,
categorised findings classified by severity:

- **breaking** — a schema violation that will cause runtime failures;
- **warning** — likely drift or degraded quality;
- **informational** — an observable difference that does not block runtime.

The result is structured data intended for CI pipelines, release gates, and
developer tooling. A build can fail automatically on breaking drift while
warnings are reviewed without blocking a release. Surfacing and orchestration —
when to run the check, how to report it — remain the consuming application's
responsibility.

### All three together

The same machinery can reconcile the query set, the contract, and the live
database **in one pass**, so contract evolution never silently desynchronises
the queries and the database from the declared truth at the same time.

---

## Governance, not replacement

It is easy to mistake a graph-contract library for an ORM or a migration tool.
Orthograph is neither, and the distinction is a hard boundary.

| Orthograph **is** | Orthograph **is not** |
|---|---|
| A declared contract the application owns and reads. | A database schema or ontology manager — it encodes intent, it does not own the layers around it. |
| A validator and drift detector. | A migration tool — it **detects** drift, it never **applies** changes to a database. |
| A query-governance layer that validates parameters, outputs, syntax, and domain match. | A query optimizer — it does not plan execution, cache results, or pool connections. |
| A producer of point-in-time profiles and comparisons. | A monitoring platform — historical storage, trend analysis, scheduling, and alerting belong in consuming infrastructure. |
| A library invoked by the application. | An owner of database connections — drivers and sessions are always passed in by the caller; inspectors are stateless. |

The positioning is deliberately *governance*: Orthograph keeps the three layers
honest with respect to a declared truth. The database still enforces its
constraints, the driver still executes, and an ORM (if used) still maps objects.
Orthograph adds the declared contract, the typed query IO, and the drift
detection that none of those layers provide — and nothing else.

---

## Where to go next

- **[Architecture overview](architecture.md)** — the seven-module public
  surface, the two validation engines, and the internal package map.
- **[How comparison works](comparison.md)** — the address space and rules behind
  database-schema-vs-definition drift detection.
- **[How query validation works](query-validation.md)** — the static checks that
  keep the query set aligned with the contract.
