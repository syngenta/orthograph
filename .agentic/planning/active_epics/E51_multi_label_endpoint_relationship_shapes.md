# Epic E51: Multi-Label Endpoint Relationship Shapes

> **Priority:** Medium (correctness hardening; addresses asymmetry between declared and observed sides on multi-label nodes)
> **Status:** Planned (not started)
> **Type:** Decision + scope + implementation (phased)
> **Depends on:** E50 (endpoint-aware relationship identity must be stable before addressing multi-label refinements)
> **Related:** ADR-037 (relationship identity), ADR-034 §8 (out-of-scope boundary), ADR-009 (inspector parity)

---

## Why This Epic Exists

**The Problem:**

The observed side (`graph_profile/inspection.py:_discover_endpoint_pairs`) emits a Cypher query that returns endpoint nodes' label *lists*. When computing the distinct `(source_label, target_label)` pairs for a relationship type, the code takes the cross-product of these lists (lines 101–103):

```python
for src in erow.source_labels:
    for tgt in erow.target_labels:
        pairs.add((src, tgt))
```

For a real edge `(a:Person:Actor)-[:KNOWS]->(b:Person)`, this yields **both** `(Person, Person)` and `(Actor, Person)` shapes. The downstream per-shape cardinality and count scans then match the **same physical edge** against both shapes, causing the same instance to be counted in multiple `RelationshipTypeProfile`s — total counts no longer sum to the true edge count.

**The Asymmetry:**

The declared side has **no mechanism to declare a multi-labeled node at all**:
- `NodeModel.__label__` is a single scalar class variable (`graph_definition/models.py:178`).
- Backend result adapters collapse multi-label nodes to a *primary* label on ingest (`neo4j/result_adapter.py:125`, `gqlalchemy/result_adapter.py:90`).
- Current backends do not emit multi-label endpoints (ADR-034 §8: "Backend-specific multi-label endpoint constraints — no current backend emits them — Out of Scope").

So the observed and declared sides are asymmetric: the observed side can *discover* multi-label nodes (and miscount edges), but the declared side cannot *declare* them or model them meaningfully.

**The Decision Needed:**

This epic frames and resolves the decision:

1. Should multi-labeled endpoint nodes become a **first-class declarable concept** in `GraphDefinition` (extending `NodeModel` to allow multiple labels), or should they remain out of scope and the **observed side be hardened** to detect and warn/error on multi-label nodes?
2. If detection/hardening: warning vs. hard error, and at what point (inspection time, comparison time, or both)?
3. If first-class declaration: how does `RelTypeKey` identity handle edges with multi-label endpoints? Does an edge `(A:Person:Actor)-KNOWS->(B)` contribute to the `Person-KNOWS-*` shape, the `Actor-KNOWS-*` shape, both, or a composite identity?
4. What is the fate of the "primary label" selection in the result adapters?

**Out of Scope (unless explicitly decided in this epic):**
- Backward compatibility with YAML definitions that have multi-label nodes (no existing definitions have them).
- Migration of any existing backend integrations (none currently declare multi-label nodes).

---

## Open Questions (to be resolved in E51.0 scoping session)

1. **Multi-label as first-class concept?** Should `NodeModel` allow declaring multiple labels per node (e.g., `__labels__: ClassVar[set[str]]`), or should multi-label nodes be unsupported and detected as an error on the observed side?
2. **Detection strategy:** If unsupported, where should the check live? At inspection time (when building profiles), at comparison time (when cross-checking observed vs. declared), or both?
3. **Error vs. warning:** Should a multi-label endpoint node raise an error (stopping inspection) or emit a warning and skip the edge? Implications for inspection robustness.
4. **Identity semantics:** If multi-label becomes first-class, how does `RelTypeKey` encode or disambiguate edges touching a multi-label node? Examples:
   - `(Person:Actor)-KNOWS->(Company)` — which shape(s) is this edge? Single or multiple identities?
   - Can a declared `Person-KNOWS-Company` edge coexist with an observed `Actor-KNOWS-Company` edge on the same nodes?
5. **Result adapter primary-label selection:** Is the current "pick the first label" approach correct, or should it be deterministic (alphabetical), or context-dependent?

---

## Decisions Already Made (do not re-litigate)

- E50 and ADR-037 are stable; relationship identity = `(source_label, label, target_label)` triple via `RelTypeKey`.
- ADR-034 §8 explicitly notes multi-label backend constraints as out-of-scope; this epic decides *how* (harden, extend, or defer further).
- Backend result adapters exist and currently collapse multi-label nodes; any change affects all backends.

---

## Existing Code to Touch / Reference

| Concept | Location |
|---------|----------|
| Multi-label detection | `graph_profile/inspection.py:_discover_endpoint_pairs` (lines 79–104; docstring now notes the limitation) |
| Node declaration (single label) | `graph_definition/models.py:178` (`NodeModel.__label__: ClassVar[str]`) |
| Result adapter selection | `backends/neo4j/result_adapter.py:125` (`_select_primary_label`); `backends/gqlalchemy/result_adapter.py:90` (same logic) |
| Out-of-scope boundary | `decisions/034-graphprofile-statistical-model-and-comparison-contract.md` §8 |
| Identity encoding | `graph_definition/identity.py` (`RelTypeKey`) and `decisions/037-relationship-identity-includes-endpoints.md` |

---

## Per-Task Guardrails

```
pwsh> python -m pytest <task's test path> -q
pwsh> python -m mypy src/orthograph
pwsh> python -m pre_commit run --files <files you changed>
```

---

## Tasks (execute in order; each ends green)

### E51.0 — Scoping session + decision ADR

> **Model: Opus.** Decision-only, no production code. The open questions above must be resolved in a grilling/scoping session before any implementation.

**Goal:** ADR-038 exists and is Accepted, capturing the decision on multi-label endpoint handling (first-class declaration vs. detect-and-harden-warn vs. detect-and-harden-error), the chosen identity semantics, and amendments to ADR-034 §8 and ADR-037 §6 if applicable.

**Operation:**
1. Conduct a scoping/grilling session against the open questions above.
2. Resolve the decision tree (decision branches may lead to separate follow-on epics if multi-label becomes first-class).
3. Write `.agentic/decisions/038-multi-label-endpoint-relationship-shapes.md` per ADR format: problem, constraints, decision, consequences, cross-references.
4. Amend ADR-034 §8 and ADR-037 §6 to reference ADR-038.
5. Update `.agentic/CONTEXT.md` with the ADR-038 routing row.

**Done when:** ADR-038 is Accepted; amendments cross-linked; `.agentic/planning/overview.md` updated (E51 status marked as complete if decision is "defer further" or "hardening only", or updated with follow-on epic numbers if new tasks emerge).

---

## Success Criteria (E51.0 only)

- [ ] **ADR-038** written and Accepted; captures the decision on multi-label endpoint handling.
- [ ] **ADR-034 §8** and **ADR-037 §6** cross-linked to ADR-038.
- [ ] **Open questions** (1–5 above) are resolved with clear rationale.
- [ ] **CONTEXT.md** updated with ADR-038 routing.
- [ ] **overview.md** updated with E51 status and any follow-on epic dependencies.

---

## Out of Scope (unless escalated by the scoping session)

- Backward compatibility with pre-ADR-038 YAML definitions.
- Retroactive re-analysis of existing inspections (only apply new rules prospectively).
- Performance optimization of multi-label detection (first task is scope, not optimization).

---

## Notes

- This epic is **deliberately deferred** pending the scoping session. It does not block E50 completion.
- If the decision is "harden the observed side with a warning," the epic may close after E51.0 (decision + comment in code, no new tasks).
- If the decision is "multi-label becomes first-class," follow-on tasks (E51.1–E51.N) will reshape `NodeModel`, the comparison engine, YAML format, inspectors, and tests — similar in scope to E50 but focused on nodes instead of relationship endpoints.
- The multi-label cross-product limitation is now documented in `graph_profile/inspection.py:_discover_endpoint_pairs` (added in the immediate E50 review fixes).
