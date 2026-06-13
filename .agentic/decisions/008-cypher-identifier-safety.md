# ADR-008: Cypher Identifier Safety — Validate-and-Reject Policy

**Date:** 2026-06-10
**Status:** Accepted
**Category:** extensions / security

---

## Context

Cypher (the query language used by Neo4j and Memgraph) distinguishes two kinds
of dynamic content in a query:

- **Values** — substituted safely via `$param` placeholders; the driver handles
  escaping.  Values are never an injection risk.
- **Identifiers** — labels (`Person`), relationship types (`ACTED_IN`), and
  property keys (`name`).  Cypher has no parameterisation mechanism for
  identifiers; they must be inlined into the query string as text.

Because identifiers must be inlined, any generator that builds Cypher from
runtime data has an unavoidable identifier-interpolation step.  The risk is
**conditional**: it exists only when an identifier originates from an untrusted
or unvalidated source.

### The finding in `CypherGenerator` (trigger)

Before E17, `CypherGenerator` read labels and property keys directly from
caller-supplied `dict` keys and embedded them via f-strings:

```python
# Before T1/T2 — unsafe
query = f"MERGE (n:{label} {{{uid_field}: ${uid_field}}})"
set_clauses = ", ".join(f"n.{k} = ${k}" for k in set_props)
```

Property keys were **not validated** — a key such as
`x} ) DETACH DELETE n //` would be embedded verbatim, producing a
structurally valid but destructive Cypher statement.  The label had a model
lookup (`get_node_type`) but the lookup ran *after* the string was already
assembled in some paths, and the check itself was not an identifier-grammar
guard.

---

## Decision: Validate-and-Reject by Default

Every identifier that is to be interpolated into a Cypher string **must pass
two consecutive checks** before the interpolation occurs:

1. **Model guard** — the key or label must be declared on the `NodeModel` or
   `RelationshipModel`.  An undeclared key raises `CypherUnknownPropertyError`;
   an unknown label raises `CypherUnknownLabelError`.

2. **Grammar guard** — the key or label must match the Cypher safe-identifier
   grammar (`^[A-Za-z_][A-Za-z0-9_]*$`).  A string that fails this check
   raises `CypherIdentifierError` from `identifiers.validate_identifier`.

If either check fails the generator raises **before assembling any Cypher
string**.  No partial or malformed query is ever returned.

This policy is enforced by:

- `src/orthograph/extensions/cypher/identifiers.py` — `validate_identifier(name, kind)`
  (T1, E17).
- `CypherGenerator._check_model_properties()` — intersects incoming keys with
  the model's declared property names (T3, E17).
- Every interpolation site in `CypherGenerator` wraps the identifier in a
  `validate_identifier(...)` call (T2, E17).
- The audit test in `tests/extensions/cypher/test_generator.py` (the
  `# Injection audit (T6)` block) serves as the regression guard: it asserts
  that every string-returning and typed-query-returning method rejects injection
  attempts in label, relationship type, and property key positions.

---

## Alternatives Considered

### Backtick-escaping by default

Cypher allows any identifier to be quoted with backticks (`` `Foo Bar` ``);
internal backticks are doubled (`` `Fo``o` ``).  A generator could escape every
identifier unconditionally and never reject.

**Rejected for the pilot.** Silently accepting attacker-named identifiers and
embedding them in a query (even quoted) is worse than failing loudly:

- It widens the accepted identifier surface to arbitrary strings, including
  Unicode, whitespace, and control characters — maximising unexpected
  interactions with Cypher parsers and downstream tools.
- It hides the root cause: the caller supplied an undeclared or garbage key.
  A loud error is far more actionable.
- It requires every downstream consumer to assume identifiers may be exotic,
  complicating logging, EXPLAIN output, and index/constraint matching.

`escape_identifier` is implemented in `identifiers.py` for completeness and as
an explicit opt-in for future use cases (e.g. graph schemas that deliberately
allow spaces in labels), but it is **not wired** into the generator.

### Validate-then-escape (defence-in-depth with escaping)

Run `validate_identifier` first; if it fails, try `escape_identifier` as a
fallback.

**Rejected.** Escaping after a grammar failure means accepting identifiers the
grammar rejects — undoing the grammar check's purpose.  Defence-in-depth is
achieved by *layering two rejection guards* (model then grammar), not by
accepting-and-transforming.

---

## Consequences

- **Safe:** all generator output contains only model-declared, grammar-safe
  identifiers embedded literally.  Values are parameterised (`$name`).
- **Strict:** callers whose `dict` keys contain undeclared or syntactically
  invalid strings receive a structured exception, not a silently malformed query.
- **Tested:** the injection audit block is the durable regression guard.  A
  green audit block is necessary (though not sufficient) proof that the risk
  is closed.
- **Extensible:** `escape_identifier` is available if a future use case
  requires identifier quoting; the decision to wire it in must be explicit and
  documented.

---

## Cross-References

- E17 epic: `.agentic/planning/active_epics/E17_cypher_generator_hardening.md`
- PRD Capability: `Query Governance — Cypher` (CypherGenerator bullet)
- `src/orthograph/cypher/identifiers.py` — T1
- `src/orthograph/cypher/generator.py` — T2, T3, T4
- `tests/cypher/test_generator.py` — injection audit block (T6)

> **Path note (E25 / ADR-011, 2026-06-11):** the Cypher tool moved from
> `extensions/cypher/` to the top-level `cypher/` package (and its tests from
> `tests/extensions/cypher/` to `tests/cypher/`). The validate-and-reject policy and the
> injection-audit regression guard are unchanged; only the import paths moved.
