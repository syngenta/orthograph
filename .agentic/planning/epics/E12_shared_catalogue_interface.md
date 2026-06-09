# Epic E12: Shared Catalogue Interface Extraction

> **STATUS: RETIRED — superseded by [E16](E16_query_catalogue_unified.md)**
> The shared `DescribableCatalogue` Protocol and `QueryDescription` dataclass are defined in E16
> as T8. The "extract from E6+E8" framing is replaced: E16 defines the shared surface up front.
> Do not pick up new work from this file.

---

> **Priority:** Medium
> **Phase:** v0.1.0 — Pilot Readiness
> **Goal:** Extract a common QueryCatalogue ABC/Protocol from the Cypher and GQLAlchemy implementations to ensure future backends plug in via the same contract
> **Blocked by:** E6 + E8 (both must exist to extract commonality)

---

## Context

After E6 (Cypher) and E8 (GQLAlchemy) are both implemented, a shared pattern
will emerge: both catalogues register named queries, validate them against a
model, execute with a passed-in connection, and validate results. Extracting
this into a shared interface ensures:

1. Future graph ORM backends plug in without rearchitecting
2. Consuming projects can program against the abstract interface
3. Mixed catalogues (future) have a defined contract to implement

This epic is intentionally **after** both concrete implementations exist —
extracting abstractions prematurely leads to wrong interfaces.

---

## Tasks

### E12.1: Extract Shared `QueryCatalogue` Protocol

Define a Protocol (or ABC) that both `CypherQueryCatalogue` and `GqlAlchemyQueryCatalogue` satisfy.

**Minimal interface:**
```python
class QueryCatalogue(Protocol):
    def register(self, name: str, ...) -> None: ...
    def get_definition(self, name: str) -> QueryDefinition: ...
    def query_names(self) -> list[str]: ...
    def execute(self, name: str, params: dict, connection: Any, ...) -> Any: ...
    def validate_query(self, name: str) -> ValidationResult: ...
```

**Acceptance criteria:**
- [ ] Protocol defined in `src/orthograph/catalogue/base.py`
- [ ] Both concrete catalogues satisfy the Protocol (verified by type checker)
- [ ] No behavioral changes to existing catalogues
- [ ] Tests: `isinstance` or structural subtyping checks pass

---

### E12.2: Update Public API to Export Protocol

Ensure consuming projects can type-annotate with the shared interface.

**Acceptance criteria:**
- [ ] `from orthograph.catalogue import QueryCatalogue` imports the Protocol
- [ ] Consuming projects can write `def process(cat: QueryCatalogue)` for backend-agnostic code
- [ ] Docstring explains when to use the Protocol vs concrete classes

---

## Future Considerations

- A `MixedQueryCatalogue` that wraps both Cypher and GQLAlchemy entries under one interface (deferred — requires scoping)
- New backend catalogues (e.g., Gremlin, SPARQL) would implement this Protocol
