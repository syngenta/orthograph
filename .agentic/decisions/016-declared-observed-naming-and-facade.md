# ADR-016: Declared/Observed Naming and the Deferred Database-Facing Facade

**Date:** 2026-06-12
**Status:** Accepted
**Category:** ubiquitous language / domain model

> Companion to ADR-015 (The Declared/Observed Mirror). ADR-015 established the
> mirror *principle* and the comparison architecture. This ADR names the two
> mirror objects and places — without yet naming — the future database-facing
> facade in the landscape.

---

## Context

The declared/observed mirror (ADR-015) has two top-level objects:

- the **declared truth** — currently `GraphDataModel`
- the **observed structure** — currently `GraphProfile`

Two problems with the current names:

1. **`GraphDataModel` carries the `Model` suffix collision.** It shares a
   suffix with `NodeModel` / `RelationshipModel`, which are Pydantic *base
   classes you subclass*, whereas `GraphDataModel` is a plain *container you
   instantiate*. Same suffix, opposite nature (see ADR-013 open work).

2. **"Data Model" is a PRD *layer* name, not an object name.** The PRD uses
   "Data Model" for the middle layer of the Ontology → Data Model → Schema
   stack ("the single declared truth"). Baking the layer name into the class
   makes the object sound like the whole layer — which is the name the future
   database-facing facade will want.

There is also a **third object**, described but never defined: a
database-facing object that would hold a declared model together with a query
catalogue, host inspection, and talk to a database through a caller-supplied
driver or ORM. Naming the declared object without accounting for this facade
risks the declared object grabbing a graph-level name the facade will need.

---

## Decision

### 1. Rename the declared truth: `GraphDataModel` → `GraphDefinition`

`GraphDefinition` names the object by its role — *the declared structure of a
graph* — without:

- the `Model` suffix collision (it is not a Pydantic base class to subclass),
- claiming the PRD layer name "Data Model",
- claiming a graph-level name (`GraphModel`, `GraphSchema`) the facade will
  want.

It pairs with `GraphProfile` as a readable mirror: **definition (what should be
true) vs profile (what is true).**

### 2. Keep `GraphProfile`

`GraphProfile` is accurate and idiomatic — "profile" is the standard word for a
point-in-time empirical measurement of structure (cf. SODA / data-quality
tooling), and the PRD already uses the verb "profile." It is the observed twin
of `GraphDefinition` and needs no rename. Its docstring now names that twin.

### 3. `GraphSchema` is rejected for the declared object

Re-confirmed from ADR-015 §5, now reinforced: "schema" is the PRD's *bottom*
layer ("what the database or datapackage enforces: indexes, constraints") and
is the natural home for the facade or DB-schema concerns. Using `GraphSchema`
for the declared object would collide with that layer and with the facade. Out.

### 4. The database-facing facade is acknowledged but **unnamed**

A future object will:

- **hold** a `GraphDefinition` and a query catalogue,
- **host / trigger** inspection (producing a `GraphProfile`),
- **talk to a database** through a driver or ORM,
- and — per the standing PRD constraint — **never own a database connection**:
  the connection/driver/session is always passed in by the caller.

Its name is **deliberately deferred**. It is recorded here so that:

- the declared object (`GraphDefinition`) deliberately avoids graph-level names
  (`GraphModel`, `GraphSchema`, `GraphSession`) so they remain available, and
- a later ADR can name the facade without re-litigating the mirror pair.

Candidate names noted (not chosen): `GraphModel`, `GraphSession`,
`GraphWorkspace`, `GraphContext`. The constraint "must not imply connection
ownership" argues against `GraphConnection`.

---

## The landscape

```
            «facade»  (DB-facing; unnamed -- future ADR)
              holds / drives (caller supplies the driver/ORM; never owns it)
        ┌───────┼───────────────────────────────┐
        │       │                                │
   GraphDefinition   QueryCatalogue        triggers inspection ─► GraphProfile
   (declared truth)  (query set)                                  (observed)
        └───────────────── compared by ──────────► validate_profile
                       (declared vs observed)
```

---

## Implementation note (this ADR)

`GraphDataModel` is renamed to `GraphDefinition` in
`src/orthograph/core/graph_data_model.py`. To keep the ~635 existing references
compiling during the stepwise rename, a backward-compatible alias
`GraphDataModel = GraphDefinition` is retained in the same module. `GraphProfile`
gains a docstring naming its declared twin. The full propagation of the new
name across the codebase (and removal of the alias) is carried out by the
stepwise plan in `.opencode/plans/declared-observed-mirror/`.

---

## Consequences

### Positive

- The mirror pair reads as a mirror: `GraphDefinition` vs `GraphProfile`.
- The `Model` suffix collision is removed for the declared container.
- Graph-level names stay free for the future facade.
- The facade is on the record, with its connection-ownership constraint, before
  it is built.

### Negative / risks

- **Large rename surface** (~635 references). Mitigated by the alias and the
  stepwise plan; the full suite stays green at each step.
- **Temporary dual naming** while the alias exists — `GraphDataModel` and
  `GraphDefinition` both resolve to the same class until the refactor removes
  the alias. Accepted as transitional.
