# ADR-046: Documentation Architecture — Diátaxis × Three Audiences, Single-Source Notebooks

> **Status:** Accepted
> **Date:** 2026-06-29
> **Relates to:** PRD §Users (the three audiences), ADR-041 (root capability
>   modules — the public surface the Reference quadrant documents), ADR-017
>   (package topology — the spine of the Explanation quadrant), E3 (the original
>   thin documentation epic, superseded by E61), E61 (the implementation epic
>   this ADR governs)
> **Supersedes:** the documentation scope of E3 (README + notebook titles +
>   diagram). E3's three tasks are folded into E61 P1.

---

## Context

Orthograph is being prepared for public release on GitHub + Read the Docs. The
current `docs/` is a stale Sphinx skeleton (RST, `bizstyle`, placeholder
`reference/index.rst` naming a non-existent `my_module`, wrong author/copyright).
The `README.rst` references removed `orthograph.api.*` paths and carries ~240
lines of *testing* documentation that belongs in `CONTRIBUTING.md`.

Against that, the asset base is strong:

- **26 prose-rich notebooks** in `notebooks/`, already numbered by pillar and
  already using the *current* API (`orthograph.definition`, …). They are
  tutorial-grade and CI-tested via `nbval`.
- A complete **PRD** and **45+ ADRs** in `.agentic/` that already contain the
  "why" — the raw material for the Explanation quadrant.
- A stable **public surface**: seven root capability modules
  (`definition`, `profile`, `compare`, `queries`, `execution`, `discovery`,
  `rendering`) plus `cypher/` (ADR-041).

This ADR fixes the documentation **architecture, guardrails, and toolchain** so
that low-reasoning agents can build it progressively without re-deciding
structure per task. It does not write content; E61 does.

The scaffolding takes inspiration from Pandera's `docs/` (flat MyST source,
notebooks compiled in place, `reference/` autosummary, `conf.py` +
`Makefile`/`make.bat`) and the content discipline from the Diátaxis framework.

---

## Decision

### D1 — Diátaxis is the top-level architecture; audiences are cross-cutting entry points

The four Diátaxis quadrants are the **primary** structure (one each):
`tutorials/`, `how-to/`, `reference/`, `explanation/`. We do **not** build three
separate per-audience trees — that would triple maintenance and fracture nav.

Instead the landing page (`index.md`) offers **three audience entry points** that
route into the quadrants:

| Audience (PRD) | Enters via | Reads mostly |
|---|---|---|
| **(3) Direct user** — validate an idea, check a DB | Tutorials | tutorials → how-to |
| **(2) Third-party developer** — Orthograph as a dependency, extend without forking | How-to + Reference | how-to → reference → explanation |
| **(1) Contributor** — navigate/modify the code | Explanation + `CONTRIBUTING.md` | explanation (high-level) → docstrings → code |

**Clarity beats purity.** Some repetition and overlap between quadrants is
accepted. The preferred tool for overlap is a **cross-reference**, not a copy:
how-to pages link down to Reference; tutorials link sideways to Explanation;
Explanation links into the relevant ADR in `.agentic/decisions/`.

### D2 — The Diátaxis compass governs where content goes

When an author (human or agent) is unsure which quadrant a page belongs to, apply
the compass:

| If the content… | …and serves… | …it is a… |
|---|---|---|
| informs action | study (learning) | tutorial |
| informs action | work (a goal) | how-to guide |
| informs cognition | work (lookup) | reference |
| informs cognition | study (understanding) | explanation |

A page that needs two quadrants is **split**, and the halves cross-link.

### D3 — Notebooks are the single source for Tutorials; compiled in place

The 26 notebooks remain canonical and live in `notebooks/`. The docs build
renders them in place via **`myst-nb`** (toctree globs into `notebooks/`). No
copy is made into `docs/source/`. This keeps one source of truth and keeps the
existing `nbval` CI coverage authoritative.

- **Build execution policy:** CI-safe notebooks execute at build time
  (`nb_execution_mode = "auto"`), surfacing code rot in the doc build itself.
  Live-DB notebooks (the `_DB_NOTEBOOKS` set in `notebooks/conftest.py`) are
  excluded from build execution and rendered from their **saved outputs**
  (`nb_execution_excludepatterns`). They remain executed in the test job under
  `--neo4j` / `--memgraph`.
- A handful of notebooks are *task-shaped* rather than *lesson-shaped* (the
  `06.x` integration notebooks). These may be surfaced under **How-to** instead
  of Tutorials. This is an editorial call inside E61, not a structural change.

### D4 — Reference documents the public surface, not the whole tree

Autosummary covers **the seven root capability modules** plus `cypher/`, and **the
most important non-private elements of each module** — not the full
`src/orthograph` tree. Rationale: internals churn; documenting them produces
obsolescence (a stated constraint). Two binding rules:

1. **Reference-or-it-doesn't-exist:** any symbol referenced from a docstring or
   from a prose doc page **must** appear in the autodoc output. If we point at
   it, it is public enough to document.
2. Internal helpers stay documented **in their docstrings and in the code**, not
   in a generated Reference page. Contributor guidance points at high-level
   modules (per CONTEXT.md routing), never at line-level internals.

### D5 — Docstrings are executable where they carry examples

`sphinx.ext.doctest` is enabled and public-surface docstrings with usage examples
are made runnable (`pytest --doctest-modules` in CI). Conversion is incremental
(an E61 task), prioritising the symbols the Quick Start and how-to pages
reference. This makes Reference examples non-rotting without bloating prose.

### D6 — Contributor documentation is deliberately thin and high-level

To avoid obsolescence, the contributor-facing material:

- lives primarily in `CONTRIBUTING.md` (setup, test matrix moved here from the
  README) and one **high-level** Explanation page (`explanation/architecture.md`)
  that points at modules and the relevant ADRs, **not** at internal functions;
- treats `.agentic/CONTEXT.md` as the canonical deep-navigation map and links to
  it rather than restating it;
- prefers "the code speaks for itself, here is the map" over narrating internals.

### D7 — Toolchain

| Concern | Choice |
|---|---|
| Page format | **MyST Markdown** (`.md`) — convert the existing RST stubs |
| Notebooks | **`myst-nb`**, compiled in place from `notebooks/` |
| Theme | **`pydata-sphinx-theme`** (replaces `bizstyle`) — supports landing-page audience nav + version switcher |
| API reference | `sphinx.ext.autodoc` + `autosummary` (already present) |
| Executable docstrings | `sphinx.ext.doctest` |
| Cross-refs to source | `sphinx.ext.viewcode` (already present) |
| Hosting | **Read the Docs** (`.readthedocs.yaml` at repo root) |
| Build entry | existing `docs/Makefile` + `docs/make.bat` |
| Doc deps | a `docs` extra in `pyproject.toml` (sphinx, myst-nb, pydata-sphinx-theme, …) |

`README` stays **`.rst`** (rewrite content; relocate the testing section to
`CONTRIBUTING.md`). It is not converted to Markdown.

### D8 — Progressive delivery with placeholders

The build must stay green at every step. Sections not yet written ship as
**placeholder pages** (a stub with a one-line scope statement and a
`.. todo::`-style note), so the toctree is complete and the site is navigable
from the walking-skeleton milestone onward. Advanced topics (detailed algorithmic
behaviour, e.g. the partitioned-cardinality internals) are explicitly allowed to
remain placeholders this round and link to the governing ADR.

---

## Target structure

```
docs/
├── Makefile / make.bat            (exist)
└── source/
    ├── conf.py                    (rewritten: theme, MyST, myst-nb, doctest, metadata)
    ├── index.md                   (landing: project pitch + 3 audience entry points)
    ├── installation.md            (from Installation.rst; aligned to pyproject extras)
    ├── tutorials/
    │   └── index.md               (learning path; toctree-globs notebooks/ via myst-nb)
    ├── how-to/
    │   └── index.md               (+ task pages; some 06.x notebooks land here)
    ├── reference/
    │   └── index.md               (autosummary over the 7 root modules + cypher/)
    ├── explanation/
    │   ├── index.md
    │   ├── architecture.md         (topology per ADR-017; links to ADRs + CONTEXT.md)
    │   ├── the-three-layer-stack.md (definition ↔ query-set ↔ DB; drift; from PRD)
    │   └── ...                      (placeholders for advanced topics)
    ├── _static/                    (rename of static/)
    └── _templates/                 (rename of templates/)

.readthedocs.yaml                   (repo root)
README.rst                          (rewritten; testing section removed)
CONTRIBUTING.md                     (absorbs the testing matrix)
```

### Pillar → notebook → quadrant map (authoritative for E61)

The six existing notebook pillars are the spine of the Tutorials learning path.
Note the known title/filename drift to repair (E61 P2):

| Pillar | Notebooks | Quadrant |
|---|---|---|
| **Graph declaration** | `01.01`–`01.05`, `02.01` (YAML) | Tutorials |
| **Visualization / rendering** | `02.02` | Tutorials |
| **Query management & validation** | `03.01`–`03.05` | Tutorials (+ how-to links) |
| **Backends (NetworkX/Neo4j/GQLAlchemy)** | `04.01`–`04.04` | Tutorials |
| **Profiling & comparison** | `05.01`–`05.06` | Tutorials |
| **Integrations (FastAPI/Dash)** | `06.01`–`06.02` | How-to (editorial) |

Known fix-ups (E61 P2): `03.01_cypher_generation` heading reads "03.02";
`03.02_cypher_query_definitions` heading reads "03.01"; `03.03_cypher_query_usage`
heading reads "04.06". README references notebook names (`03.02_neo4j_end_to_end`,
`06.01_profile_neo4j_example`, …) that no longer exist.

---

## Consequences

**Positive**
- One nav, four quadrants, three labelled doors — low maintenance, clear routing.
- Zero tutorial duplication; notebooks stay the single tested source.
- Reference cannot drift silently: the reference-or-it-doesn't-exist rule + doctest.
- Contributor docs cannot rot into line-level lies: they point at modules + ADRs.
- The "why" is harvested from existing PRD/ADRs, not re-authored.

**Negative / costs**
- Build is slower (notebook execution) and needs the `docs` extra installed in CI/RTD.
- The RST→MyST conversion + theme swap is upfront churn before any content lands.
- Keeping the reference-or-it-doesn't-exist rule honest requires review discipline.

**Neutral**
- README stays RST (one project file remains a different syntax from docs).

---

## Alternatives considered

1. **Three separate audience trees.** Rejected: triples maintenance, fractures
   search/nav, guarantees drift between trees.
2. **Copy a curated notebook subset into `docs/source/tutorials/`.** Rejected:
   duplicates the single tested source; the in-place compile (D3) keeps `nbval`
   authoritative.
3. **Full-tree autodoc.** Rejected by D4: documents churning internals and
   manufactures obsolescence against an explicit constraint.
4. **Convert README to Markdown.** Rejected this round: low value, and the RST
   README already renders on the package index; the testing-relocation is the
   real fix.
5. **Keep `bizstyle`.** Rejected: weak landing-page / multi-audience nav and no
   version switcher for RTD.
