# ADR-018: Rename `catalogue/` → `query/` and `typed.py` → `base_models.py`

**Date:** 2026-06-12
**Status:** Accepted
**Category:** naming / package topology

> Resolves the open-work item in ADR-013 ("the `catalogue`/contract-module naming
> requires a broader holistic decision — deferred").
> Supersedes the "catalogue — unchanged" note in ADR-017's decision tree.

---

## Context

`orthograph.catalogue` contains two modules with distinct, independently-changing
natures:

| Module | Nature | Primary importers |
|---|---|---|
| `typed.py` | Abstract contracts (ABCs + Enum + TypeVars): `ReadQuery`, `WriteQuery`, `Executor`, `ReadPort`, `QueryBackedReadPort`, `Backend`, `P`/`D`/`R` | 10 src files across `api/`, `backends/`, `cypher/` |
| `registry.py` | Stateful service + value object: `QueryCatalogue`, `QueryDescription` | 5 src files |

Three problems accumulate:

1. **Adjective module name.** `typed.py` is named after a property ("it is
   typed"), not its domain role. ADR-013 rule: "explicit, self-describing names;
   one word per concept." ADR-017 rule: "activity modules inside a package keep
   verb/noun names." `typed` is neither.

2. **Folder named after one of its two modules.** `catalogue/` picks up the name
   of the registry (the less-imported half) and imposes it on the contracts (the
   more-imported half). A reader navigating to the package to find the query
   seams has to guess which module holds them.

3. **Breaks the existing `base_models.py` convention.** Both `cypher/` and
   `backends/gqlalchemy/` use a file named `base_models.py` to house abstract
   query bases — exactly what `typed.py` provides for the layer below them.
   The contracts that those files depend on should use the same filename
   convention they themselves follow.

### Why ADR-013 deferred this

ADR-013 §open-work wrote: "the `catalogue`/contract-module naming requires a
broader holistic decision." The "broader" decision is now made: ADR-017
canonised the five-package topology and its naming rubric (noun packages,
activity-noun modules). This ADR is the downstream application of that rubric to
`catalogue/`.

---

## Decision

Rename the package and its modules:

| Old path | New path | Role |
|---|---|---|
| `src/orthograph/catalogue/` | `src/orthograph/query/` | the query subsystem |
| `catalogue/typed.py` | `query/base_models.py` | abstract contracts (the seam layer) |
| `catalogue/registry.py` | `query/catalogue.py` | the registry service |
| `catalogue/__init__.py` | `query/__init__.py` | (docstring updated) |
| `tests/catalogue/` | `tests/query/` | test mirror |
| `tests/catalogue/test_typed_queries.py` | `tests/query/test_base_models.py` | |
| `tests/catalogue/test_registry.py` | `tests/query/test_catalogue.py` | |

No public symbols change — only the import paths.

### Why `query/` (singular)

Mirrors the ADR-017 convention: noun packages name the domain object
(`graph_profile`, `graph_definition`, `comparison`, `diagnostics`). The package
holds the query *machinery* (both the abstract seam and the registry), not a
list of queries; singular is accurate. It also avoids a naming collision with the
backend-local `queries.py` files which live at a different package depth.

### Why `base_models.py`

Matches the established convention:
- `cypher/base_models.py` — abstract Cypher query bases you subclass
- `backends/gqlalchemy/base_models.py` — abstract GQLAlchemy query bases

`query/base_models.py` is the layer those files depend on: the root abstract
contracts (`ReadQuery`, `WriteQuery`, `Executor`, `ReadPort`). Using the same
filename makes the three-level hierarchy legible: `query/base_models` →
`cypher/base_models` → concrete query class.

### Known tradeoff

`query/base_models.py` is slightly broader than the purely-abstract
`cypher/base_models.py` and `gqlalchemy/base_models.py` files: it also carries
`Backend` (enum), `QueryBackedReadPort` (concrete adapter), and the `P`/`D`/`R`
TypeVars. These are inseparable from the seam contracts and have no better home.
Convention consistency is accepted over perfect purity.

### Why `catalogue.py` for the registry

ADR-013 reserved `catalogue` as the canonical word for the named-query registry
(`QueryCatalogue` class, `query_catalogue` variable). Naming the module
`catalogue.py` restores that 1:1 mapping: the word "catalogue" now refers
exclusively to the registry, not to the package that houses both the contracts
and the registry.

---

## Rationale (ADR-017 rubric)

- **Readability / one-word-per-concept.** Import sites read as sentences:
  `from orthograph.query.base_models import ReadQuery`,
  `from orthograph.query.catalogue import QueryCatalogue`.
- **SRP / change-in-one-place.** Contracts (`base_models.py`) and the registry
  (`catalogue.py`) change for independent reasons; the module boundary now
  matches the change boundary.
- **DIP.** Everything depends on `query.base_models` (the abstraction layer),
  which carries no DB imports. The dependency direction is honest and the name
  advertises it.
- **Convention fit.** `query/` is a noun package; its modules are role-named
  (`base_models` = seam contracts, `catalogue` = registry service). Follows
  ADR-017 exactly.

---

## Dependency DAG (unchanged by this rename)

The rename does not change any dependency direction. `query/base_models.py` has
no intra-package imports (same as `catalogue/typed.py`). `query/catalogue.py`
imports only from `query/base_models.py` (same as before).

---

## Path translation table

| Old reference | New reference |
|---|---|
| `orthograph.catalogue` (package) | `orthograph.query` |
| `orthograph.catalogue.typed` | `orthograph.query.base_models` |
| `orthograph.catalogue.registry` | `orthograph.query.catalogue` |
| `from orthograph.catalogue.typed import ReadQuery, WriteQuery, …` | `from orthograph.query.base_models import ReadQuery, WriteQuery, …` |
| `from orthograph.catalogue.registry import QueryCatalogue` | `from orthograph.query.catalogue import QueryCatalogue` |
| `tests/catalogue/test_typed_queries.py` | `tests/query/test_base_models.py` |
| `tests/catalogue/test_registry.py` | `tests/query/test_catalogue.py` |

---

## Consequences

### Positive

- The three-level abstract-query hierarchy is now visible in filenames:
  `query/base_models` → `cypher/base_models` / `gqlalchemy/base_models` → concrete query.
- "catalogue" means exactly one thing everywhere: the registry service.
- `typed` (an adjective with no domain content) is retired from the codebase.

### Negative / risks

- **Blast radius:** ~12 source files + ~5 test files require import-path
  updates. Changes are purely mechanical (string replacements in import lines);
  no semantic changes.
- **Stale references in older records:** ADR-017 lists `catalogue/` as
  "unchanged." That note is superseded by this ADR. ADR-001/003/007/009/011
  reference `catalogue` in prose without citing the module path; those remain
  historically accurate and are not rewritten.
