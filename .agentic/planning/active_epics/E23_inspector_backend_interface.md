# Epic E23: Inspector Backend-Behaviour Injection Interface

> **Priority:** Medium
> **Phase:** v0.1.0 — Pilot Readiness (scoping); implementation likely post-pilot
> **Origin:** E17 T7/T8 review session 2026-06-10 (typed-Cypher inspector migration; surfaced
> the duplication between the Neo4j and Memgraph inspectors and the one remaining raw-string probe).
> **Blocked by:** None to start scoping. Touches the same files as E4 (Extension Robustness) and
> E18.1 (cardinality/endpoint-labels parity) — coordinate edits.
> **Relates to:** [knowledge/extension-contract.md](../../knowledge/extension-contract.md)
> (`GraphInspector` ABC, `GraphProfile`), ADR-003 (two-phase extension architecture),
> ADR-009 (inspector query alignment), and the `src/orthograph/extensions/{neo4j,memgraph}/inspector.py`
> pair.
>
> **SCOPE NOTE:** This epic is a **finding record only** — no tasks are defined yet. It captures the
> structural duplication between the two Cypher inspectors and the open question of whether a shared
> inspection interface that *injects* per-backend behaviour earns its keep. A scoping/decision
> session (producing an ADR) should precede any task breakdown.

---

## Context

E17 T7/T8 migrated both Cypher inspectors (`Neo4jInspector`, `MemgraphInspector`) from the retired
`QueryStrategy` Protocol to typed `CypherReadQuery` subclasses executed through an internal
`QueryCatalogue`. After the migration the two inspectors are **structurally near-identical**:

- Both hold a driver, build an internal catalogue, and expose the same `GraphInspector.inspect()`
  contract.
- Both share the same private execution seam: `_run(cypher_string)` (the single driver I/O point)
  and `_run_query(QueryClass, identifiers)` (build → render → execute → materialize). These two
  methods are duplicated almost verbatim across `neo4j/inspector.py` and `memgraph/inspector.py`.
- Both assemble a `GraphProfile` from the same building blocks: node profiles, rel profiles,
  endpoint labels (E18.1), cardinality stats, and constraints — differing only in **which typed
  queries** they run and **a few per-backend quirks** (APOC vs pure-Cypher property introspection;
  Memgraph's `count`/`mandatory` parity gaps).

The differences between backends are narrow and well-localised. The current design expresses them
by **copying the orchestration and varying the query classes**, rather than by injecting the
backend-specific pieces into one shared orchestrator.

---

## The Findings

### Finding 1 — One raw-string query remains outside the typed path

`src/orthograph/extensions/neo4j/inspector.py` `_detect_apoc()` issues a raw
`SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'apoc.meta' RETURN count(name) AS cnt` string
directly through `_run()`. ADR-009's stated intent is that the library "eats its own cooking" — all
introspection flows through typed `CypherReadQuery` + catalogue. The APOC-detection probe is the
**one remaining raw, non-typed query** in the Neo4j path.

It is **low risk** (static string, no interpolated identifiers) — not a correctness or injection
bug — but it is an inconsistency with the "only the typed path" intent and a candidate to fold into
a typed `InspectApocAvailableQuery`.

### Finding 2 — Backend behaviour is varied by duplication, not injection

`_run` / `_run_query` and the profile-assembly orchestration are duplicated across the two
inspectors. Each new Cypher-speaking backend (and any future variation) re-implements the same
scaffold. There is no shared abstraction for "a Cypher inspector that is parameterised by its query
set and a handful of backend quirks." This is the same cross-cutting redundancy E2 and E20 target,
but for the inspector layer specifically.

---

## Why This Matters

- **Drift risk.** The two inspectors must stay behaviourally aligned (same `GraphProfile` shape,
  same endpoint-labels/cardinality semantics from E18.1). Duplicated orchestration means a fix
  applied to one (e.g. the cardinality source-label selection) can silently miss the other — which
  is exactly the asymmetry recorded as the Open Question below.
- **Eating our own cooking.** Finding 1 leaves a visible exception to ADR-009's "only the typed
  path" claim. Closing it keeps the architectural story honest.
- **Cost of the next backend.** A SQLAlchemy or remote-GQLAlchemy inspector (E14, future) would
  re-copy the scaffold again unless a shared interface exists.

---

## Open Question — Cardinality label selection + APOC presence policy (for scoping)

> **Origin:** E17 T7/T8 review 2026-06-10. Recorded for scoping; **no decision made now.**

Two related, deliberately-deferred questions about how the inspectors choose a label for cardinality
and how they react to backend capability detection:

1. **Cardinality source-label selection differs between backends.**
   - Neo4j (`neo4j/inspector.py`, `_build_rel_profile`) iterates the confirmed `source_labels` from
     `InspectEndpointLabelsQuery`, **falling back to all node labels** when none are found
     (`candidates = sorted(source_labels) if source_labels else sorted(labels)`).
   - Memgraph (`memgraph/inspector.py`, `_enrich_rel_profile`) iterates `sorted(source_labels)`
     only, with **no fallback** — if endpoint labels are empty, `card_stats` stays `None`.

   These should be aligned, but the **direction is undecided**: drop the Neo4j fallback (the
   endpoint-labels query is authoritative; an empty result means no relationships to measure, and
   the fallback can only produce the misleading `min=0/max=0` result the Neo4j code comment itself
   warns against — and no current test exercises it), *or* add the fallback to Memgraph for
   symmetry. Resolve in the scoping session.

2. **APOC presence detection and the fallback policy.** The Neo4j inspector detects APOC via
   `_detect_apoc()` and silently selects the APOC catalogue when present, the pure-Cypher catalogue
   otherwise. The intent to record: there should be a **deliberate, documented policy** for what
   happens around capability detection — e.g. when APOC is absent, or when a probe is inconclusive.
   Candidate behaviours to weigh (not decisions): **silent fallback** to pure-Cypher (current),
   an **error**, a **warning/log line**, or a configurable strictness flag. This ties into E20
   (error hierarchy + logging). Scope the policy before changing the detection code.

---

## Out of Scope (this epic, until scoped)

- Implementing a shared inspector base / behaviour-injection interface (decision-first; needs an
  ADR weighing the abstraction against the current two-backend count).
- Converting `_detect_apoc` to a typed query (do it as part of, or after, the interface decision so
  the probe lands in the right place).
- Changing the cardinality fallback or APOC-presence policy — both are explicitly deferred to the
  Open Question scoping session above.
- The e2e test **activation/configuration** harness — that is E21. The **coverage** of the shared
  inspector contract is E22. This epic concerns the inspector **production interface** only.
