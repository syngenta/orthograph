# Epic E61: Documentation — Read the Docs Site (Diátaxis × Three Audiences)

> **Priority:** High (release gate — public GitHub + Read the Docs)
> **Phase:** v0.1.0 / pre-pilot
> **Type:** Additive + scaffolding refactor of `docs/`; no `src/` behaviour change
>   (one exception: docstring-only edits for doctest in P3)
> **Decisions:** **ADR-046** (read it first — it is the spec) · PRD §Users (the
>   three audiences) · ADR-041 (the public surface) · ADR-017 (topology — the
>   Explanation spine). **Supersedes E3** (its 3 tasks fold into P1).
> **Inspiration:** Pandera `docs/` scaffolding · Diátaxis framework
> **Rubric (every task judged against this):**
>   - build stays **green** at the end of every task (`make html` no errors; warnings tracked)
>   - **single source** — never copy a notebook into `docs/source/`
>   - **reference-or-it-doesn't-exist** — anything named in a docstring or prose page is in autodoc (ADR-046 D4)
>   - **placeholders are valid output** — an unwritten section ships as a stub with a scope line, toctree stays complete (ADR-046 D8)
>   - **cross-reference, don't duplicate** — overlap between quadrants is a link
>   - **contributor docs point at modules + ADRs, never at internal functions** (ADR-046 D6)

---

## Why This Epic Exists

Orthograph is going public. The current `docs/` is a stale Sphinx skeleton (RST,
`bizstyle`, a placeholder `reference/index.rst` naming a non-existent `my_module`,
wrong copyright/author). The README references removed `orthograph.api.*` paths
and carries ~240 lines of testing prose that belongs in `CONTRIBUTING.md`.

The asset base is strong: 26 prose-rich, `nbval`-tested notebooks already
organised by pillar and using the current API; a complete PRD; 45+ ADRs carrying
the "why". ADR-046 fixes the architecture (Diátaxis quadrants as the tree, three
audiences as labelled doors, notebooks compiled in place, public-surface-only
reference, thin contributor docs). This epic **builds** it, progressively, so each
phase produces a navigable site and can be corrected before the next runs.

---

## Decisions Already Made (do not re-litigate — see ADR-046)

- Four Diátaxis quadrants are the tree; three audiences are entry points on `index.md`.
- Notebooks stay in `notebooks/`, compiled in place via `myst-nb`. No copies.
- CI-safe notebooks execute at build; live-DB notebooks render from saved outputs.
- Reference = the **7 root modules + `cypher/`** and their important non-private symbols only.
- Page format is **MyST Markdown**; **README stays `.rst`**.
- Theme is **`pydata-sphinx-theme`**; hosting is **Read the Docs**.
- Doctest is enabled and adopted incrementally on the public surface.
- Build must stay green at every step; unwritten sections are placeholders.

---

## Phases

P0 is the walking skeleton and **STOPS for review** before any content phase runs.
Phases are sequential (P0 → P1 → … ); tasks **within** a phase that touch different
files may run in parallel.

```
P0  Walking skeleton ......... scaffolding compiles, empty quadrants, 1 notebook wired   ← REVIEW GATE
P1  Front door + reference ... index landing, README/CONTRIBUTING, installation, autodoc
P2  Tutorials ................ wire all notebooks, fix title/number drift, learning path
P3  How-to + doctest ......... task pages, 06.x integrations, executable docstrings
P4  Explanation .............. architecture + three-layer-stack + advanced-topic placeholders
```

---

## Model tag legend

`[haiku]` mechanical, fully-specified, no design. `[sonnet]` structured authoring
or wiring with light judgement. `[opus]` cross-cutting judgement, prose that must
be correct against PRD/ADRs, or editorial mapping. `[qwen]` acceptable substitute
for `[haiku]` mechanical tasks where a local model is preferred.

---

## P0 — Walking Skeleton  *(REVIEW GATE: stop and show the built site overview)*

> Goal: `make html` builds a navigable Diátaxis site with empty placeholder
> sections and exactly one notebook rendered, on the new theme. No real content.

### E61.0.1 — Add the `docs` extra and `.readthedocs.yaml`  `[sonnet]`
Add a `docs` optional-dependency group to `pyproject.toml`
(`sphinx`, `myst-nb`, `pydata-sphinx-theme`, `sphinx-design` optional) and create
`.readthedocs.yaml` at repo root (Python 3.12, install `.[docs]`, build
`docs/source/conf.py`).
**Acceptance:**
- [ ] `pip install -e ".[docs]"` succeeds
- [ ] `.readthedocs.yaml` validates (RTD schema) and points at `docs/source/conf.py`
- [ ] no change to existing runtime extras

### E61.0.2 — Rewrite `conf.py`  `[sonnet]`
Replace `docs/source/conf.py`: extensions `myst_nb`, `sphinx.ext.autodoc`,
`sphinx.ext.autosummary`, `sphinx.ext.viewcode`, `sphinx.ext.doctest`,
`sphinx.ext.intersphinx`; `html_theme = "pydata_sphinx_theme"`; rename static
paths to `_static`/`_templates`; set `nb_execution_mode="auto"` and
`nb_execution_excludepatterns` for the live-DB notebooks (the `_DB_NOTEBOOKS` set
in `notebooks/conftest.py`); fix `copyright`/`author`; keep `version` from
`orthograph.__version__`. Remove the `bizstyle`-specific `html_sidebars`.
**Acceptance:**
- [ ] `make html` runs with the new extensions, no config errors
- [ ] theme renders as pydata
- [ ] live-DB notebooks are listed in `nb_execution_excludepatterns`

### E61.0.3 — Create the Diátaxis skeleton with placeholders  `[haiku]`
Create `index.md` (minimal pitch + a toctree to the four quadrants),
`tutorials/index.md`, `how-to/index.md`, `reference/index.md`,
`explanation/index.md`, and `installation.md` — each a **placeholder** (one-line
scope statement + a "content coming in E61.Px" note). Delete/convert the obsolete
`index.rst` and `reference/index.rst` (`my_module`). Move `static/`→`_static/`,
`templates/`→`_templates/`.
**Acceptance:**
- [ ] every page is in a toctree; no orphan-page warnings
- [ ] obsolete RST stubs removed
- [ ] build green

### E61.0.4 — Wire exactly one notebook (proof of myst-nb)  `[haiku]`
In `tutorials/index.md`, add a toctree entry rendering
`../../notebooks/01.01_create_a_graph_definition.ipynb` (relative include; no
copy). Confirm it executes at build (it is CI-safe).
**Acceptance:**
- [ ] `01.01` renders in the built site with executed outputs
- [ ] the source notebook is unchanged
- [ ] build green

### E61.0.5 — Build-overview report for review  `[haiku]`
Run `make html`, capture the warning list, and write
`.agentic/reviews/E61_P0_build_overview.md` listing: pages built, the rendered
notebook, theme in use, and any warnings. **This is the review-gate artifact.**
**Acceptance:**
- [ ] report lists the full toctree as built
- [ ] warnings enumerated (or "none")
- [ ] **STOP — await human review before P1**

---

## P1 — Front Door + Reference  *(absorbs E3.1)*

### E61.1.1 — Author `index.md` landing with three audience doors  `[opus]`
Write the landing page: the Pandera-style one-liner ("Pydantic-native graph
definition, validation, and query governance — Pandera for property graphs"), the
three-capability summary (from PRD §Solution), and **three audience entry blocks**
(User → Tutorials; Developer → How-to/Reference; Contributor → Explanation +
CONTRIBUTING) each linking into the quadrants. Governance framing, not
"replacement" framing (PRD).
**Acceptance:**
- [ ] three labelled audience doors, each linking a quadrant
- [ ] positioning matches PRD §Vision; no stale `api.*` references
- [ ] build green, links resolve

### E61.1.2 — Author `installation.md`  `[sonnet]`
Port `Installation.rst` to MyST; align extras to `pyproject.toml`
(`neo4j`, `memgraph`, `networkx`, `cypher`, `gqlalchemy`, `all`, `dev`, `docs`);
correct Python version; venv guidance from README.
**Acceptance:**
- [ ] extras table matches `pyproject.toml`
- [ ] no Python 3.9 / conda / Nexus references
- [ ] `Installation.rst` removed (replaced)

### E61.1.3 — Reference autosummary over the public surface  `[opus]`
Rewrite `reference/index.md`: `autosummary` (with `:toctree: generated`) over the
seven root modules (`definition`, `profile`, `compare`, `queries`, `execution`,
`discovery`, `rendering`) and `cypher/`, listing the **important non-private
symbols** of each (the names a consumer imports). Group by module with a
one-line description each. Enforce ADR-046 D4.
**Acceptance:**
- [ ] all seven root modules + `cypher/` present
- [ ] every symbol named in the README Quick Start appears here
- [ ] `autosummary_generate` produces stub pages; build green; no autodoc import errors

### E61.1.4 — Rewrite `README.rst`  `[opus]`  *(was E3.1)*
Rewrite content: accurate "what is this" in the first 3 lines, Pandera-for-graphs
positioning, install matching `pyproject.toml`, a **valid** Quick Start using
current root-module imports (`from orthograph.definition import …`, not
`orthograph.api.*`), both validation capabilities, and a link to the RTD site.
**Remove the entire testing/notebook-running section** (moves to E61.1.5). Keep
`.rst`.
**Acceptance:**
- [ ] Quick Start imports resolve against current `src/`
- [ ] no `orthograph.api.*`, no stale notebook names, no Python 3.9
- [ ] testing section gone; link to CONTRIBUTING added

### E61.1.5 — Relocate testing matrix into `CONTRIBUTING.md`  `[sonnet]`
Move the README testing content (categories, `--neo4j`/`--memgraph` flags,
credential management, notebook running, adding live-DB tests, full matrix) into
`CONTRIBUTING.md` under a "Running the tests" section. Fix the stale notebook
names while moving (the `_DB_NOTEBOOKS` source of truth is
`notebooks/conftest.py`).
**Acceptance:**
- [x] full test matrix present in CONTRIBUTING
- [x] live-DB notebook list matches `notebooks/conftest.py`
- [x] no duplication left in README

---

## P2 — Tutorials  *(absorbs E3.2, E3.3)*

### E61.2.1 — Fix notebook title/number drift  `[haiku]`  *(was E3.2)*
Correct the first-heading vs filename mismatches: `03.01_cypher_generation`
(heading says 03.02), `03.02_cypher_query_definitions` (says 03.01),
`03.03_cypher_query_usage` (says 04.06). Enforce format `"XX.YY — Title"` across
all 24+ notebooks.
**Acceptance:**
- [ ] every notebook's first H1 matches its filename number
- [ ] consistent `"XX.YY — Title"` format
- [ ] `pytest notebooks/ --nbval-lax` still passes

### E61.2.2 — Author the Tutorials learning path  `[opus]`
Write `tutorials/index.md` as a guided path grouping the notebooks by the six
pillars (ADR-046 map): declaration → visualization → query management → backends
→ profiling & comparison. Decide which `06.x` notebooks stay here vs move to
How-to (editorial). Each pillar gets a 2–3 line lead-in linking the relevant
Explanation page.
**Acceptance:**
- [x] all tutorial notebooks reachable via toctree (single source, no copies)
- [x] pillars ordered as a learning progression
- [x] CI-safe notebooks execute at build; live-DB ones render saved outputs

> **Editorial call (ADR-046 D3):** the `06.x` integration notebooks
> (`06.01_fastapi_integration`, `06.02_dash_profile_explorer`,
> `06.03_async_query_runner`) are task-shaped, so they go under **How-to** (wired
> in E61.3.2), not the Tutorials learning path. The five tutorial pillars are
> ordered declaration → visualization → query management → backends → profiling &
> comparison.
>
> **Wiring fix (conf.py):** the P0 Windows copy-fallback exposed only one
> notebook and broke the notebooks' `from shared.filmography import …` imports and
> `data/*.json` reads (they execute with CWD inside `docs/source/notebooks/`).
> Replaced with a link-first strategy: POSIX symlink → Windows directory junction
> (`mklink /J`, no Developer Mode needed) → copy-of-notebooks-plus-support-dirs as
> last resort. The junction keeps a single source and lets all CI-safe notebooks
> execute at build (18 prior `CellExecutionError`s cleared; warnings 63 → 43, the
> remainder pre-existing autodoc/lexer issues outside this task).

### E61.2.3 — Architecture diagram  `[sonnet]`  *(was E3.3)*
Add a Mermaid diagram of the three-layer stack (definition ↔ query-set ↔ DB
schema) and the seven-module surface, placed in `explanation/architecture.md`
(stub created here, fleshed out in P4) and linked from `index.md`. Use the PRD
stack diagram as the source.
**Acceptance:**
- [x] valid Mermaid, renders in build
- [x] matches ADR-017 topology + PRD stack
- [x] discoverable from the landing page

---

## P3 — How-To + Doctest

### E61.3.1 — Author core how-to pages  `[opus]`
Write goal-oriented how-to pages for the developer/user audiences, each short and
linking down to Reference (compass D2). Minimum set: "Validate in-memory data",
"Profile a live Neo4j database and detect drift", "Register and validate a typed
query catalogue", "Compare two definitions (version drift)". Each is a task, not a
lesson; reuse notebook snippets by reference where possible.
**Acceptance:**
- [ ] each page states a single goal and the steps to reach it
- [ ] each links to the relevant Reference symbols (which therefore exist — D4)
- [ ] no lesson-style narration (that belongs in Tutorials)

### E61.3.2 — Place integration notebooks as how-to  `[sonnet]`
Surface `06.01_fastapi_integration` and `06.02_dash_profile_explorer` under
How-to (per ADR-046 D3 editorial call), with a one-line task framing each.
**Acceptance:**
- [x] both integration notebooks reachable under How-to, single source
- [x] build green

### E61.3.3 — Enable doctest and convert priority docstrings  `[opus]`
Wire `pytest --doctest-modules` into the test config; convert the public-surface
docstrings referenced by the Quick Start and the P3 how-to pages into runnable
doctests. Incremental — prioritise the most-referenced symbols.
**Acceptance:**
- [x] `pytest --doctest-modules src/orthograph` passes
- [x] Quick Start example exists as a doctest somewhere on the public surface
- [x] `make doctest` (sphinx) passes for converted pages

---

## P4 — Explanation

### E61.4.1 — Author `explanation/architecture.md`  `[opus]`
High-level only (ADR-046 D6): the package topology (ADR-017), the seven-module
surface (ADR-041), the declared/observed mirror (ADR-015). Point at modules and
ADRs; **no internal-function narration**. Link to `.agentic/CONTEXT.md` as the
deep map for contributors.
**Acceptance:**
- [ ] explains topology + the two validation engines (PRD Implementation Decision 1)
- [ ] every "why" claim links a PRD section or ADR
- [ ] no references to private/internal functions

### E61.4.2 — Author `explanation/the-three-layer-stack.md`  `[opus]`
Explain the governance positioning: ontology → graph definition → schema, and
bidirectional drift detection (query-set vs definition; DB schema vs definition).
Source: PRD §Vision + §Capability 3. Governance framing, not replacement.
**Acceptance:**
- [x] reproduces the three-layer stack with drift arrows (Mermaid from E61.2.3)
- [x] distinguishes Orthograph from ORMs/migration tools (PRD Constraints)

### E61.4.3 — Advanced-topic placeholders  `[haiku]`
Create stub Explanation pages for advanced/algorithmic topics that will rot if
written too early — each a scope line + a link to the governing ADR. Minimum:
conditional cardinality partitioning (ADR-032/039), Neo4j inspection strategies
(ADR-033), endpoint-aware relationship identity (ADR-037).
**Acceptance:**
- [ ] each placeholder names its scope and links its ADR
- [ ] toctree complete; build green
- [ ] explicitly marked as "expansion after this round" (ADR-046 D8)

---

## Definition of Done (epic)

- [ ] `make html` builds clean on the new theme; `.readthedocs.yaml` builds on RTD
- [ ] all four quadrants populated or placeholdered; landing page routes the three audiences
- [ ] all notebooks rendered in place (single source); titles/numbers consistent
- [ ] Reference covers the 7 root modules + `cypher/`; reference-or-it-doesn't-exist holds
- [ ] README rewritten (accurate, valid Quick Start); testing matrix lives in CONTRIBUTING
- [ ] doctest runs in CI; Quick Start is a runnable doctest
- [ ] Explanation points at modules + ADRs only; advanced topics are placeholders
- [ ] CONTEXT.md + planning/overview.md cross-link ADR-046 and E61
