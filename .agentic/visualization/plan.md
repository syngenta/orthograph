# Visualization -- Requirements, Decisions, and Implementation Plan

## Context

Visualization in orthograph currently consists of a single function (`to_mermaid`)
inside `extensions/visualization/mermaid.py`. It generates a Mermaid diagram from
a `GraphDataModel` -- showing node types, their properties, and relationships.

This is useful but limited: it only visualizes the **model** (the schema definition),
not the **data** (an actual graph or an inspection profile). It also lives inside
`extensions/`, which creates an odd dependency: visualization is not an "extension"
in the same sense as neo4j or networkx -- it does not inspect or validate anything.
It is a **consumer** of orthograph's data structures.

## Requirements

### R1: Separate visualization from extensions

Visualization should be a **top-level subpackage** (`src/orthograph/visualization/`),
not nested inside `extensions/`. Rationale:

- Extensions follow the inspect/validate pattern. Visualization does neither.
- Visualization consumes both `GraphDataModel` (schema) and `GraphProfile` (data).
  Extensions produce profiles; visualization renders them. Different concern.
- Future visualization backends (HTML reports, matplotlib, D3 export) should not
  clutter the extensions package.
- Dependency isolation: visualization may depend on optional packages (mermaid
  renderers, Jinja2 for HTML, matplotlib) that are unrelated to neo4j/networkx.

### R2: Visualize a GraphDataModel (schema)

Generate a visual representation of the schema definition:

- Node types as boxes with their properties (name: type, required/optional)
- Relationship types as labeled edges with direction
- Cardinality annotations on edges
- UID fields highlighted

This is what the current `to_mermaid()` does (partially -- no cardinality, no
required/optional distinction). It needs to be enriched.

### R3: Visualize a GraphProfile (data)

Generate a visual representation of an inspection profile:

- Node types with instance counts and property completeness heatmap
- Relationship types with counts, source/target labels, cardinality stats
- Property-level detail: completeness percentage, observed types, missing count
- Highlight anomalies: low completeness, type mismatches, unexpected types

This is new functionality. The `GraphProfile` Pydantic model is already
serialisable -- visualization renders it for human consumption.

### R4: Visualize a ValidationResult

Generate a visual summary of validation results:

- Pass/fail status per node type and relationship type
- List of errors, warnings, info grouped by entity
- Severity-coded (red/yellow/blue)

This is also new. The `ValidationResult` already has structured data (`issues`,
`errors`, `warnings`); visualization formats it for reports.

### R5: Multiple output formats

| Format | Use case | Dependency |
|--------|----------|------------|
| Mermaid text | Embeddable in markdown, notebooks, docs | None |
| HTML report | Standalone file, CI artifacts, email | Jinja2 (optional) |
| Plain text table | Terminal output, logs | None |

Future formats (not in first implementation):
- matplotlib/graphviz (for publication-quality figures)
- D3/JSON (for interactive web dashboards)
- PDF (for formal reports)

### R6: Composable renderers

Each visualization target (model, profile, result) should have a **renderer**
interface. Each output format implements that interface. Users choose the format;
the library chooses what to render based on the input type.

```python
# Desired API
from orthograph.visualization import render

# Render a schema as Mermaid
mermaid_text = render(model, format="mermaid")

# Render a profile as a text table
table_text = render(profile, format="text")

# Render a validation result as HTML
html = render(result, format="html")
```

Or, for explicit control:

```python
from orthograph.visualization.mermaid import model_to_mermaid, profile_to_mermaid
from orthograph.visualization.text import profile_to_text, result_to_text
```

## Separation of Concerns: Decision

### What stays in `extensions/`

- `extensions/networkx/conversion.py` (`schema_to_networkx`) -- this converts a
  model to a NetworkX graph object for programmatic use (topology analysis, graph
  algorithms). It is a **data conversion**, not a visualization. It stays in the
  networkx extension because the output is a `nx.MultiDiGraph`, not a visual format.

### What moves to `visualization/`

- `extensions/visualization/mermaid.py` (`to_mermaid`) -- moves to
  `visualization/mermaid.py`. Becomes one of several renderers.

### New top-level package

```
src/orthograph/
├── visualization/              # NEW: top-level subpackage
│   ├── __init__.py             # render() dispatcher + re-exports
│   ├── mermaid.py              # Mermaid renderers (model, profile, result)
│   └── text.py                 # Plain text renderers (tables for terminal)
```

Tests:
```
tests/visualization/
├── __init__.py
├── test_mermaid.py             # Moved from tests/extensions/visualization/
└── test_text.py                # New
```

### What gets deleted

- `src/orthograph/extensions/visualization/` (entire directory)
- `tests/extensions/visualization/` (entire directory)

### Import path changes

| Old | New |
|-----|-----|
| `from orthograph.extensions.visualization import to_mermaid` | `from orthograph.visualization import render` or `from orthograph.visualization.mermaid import model_to_mermaid` |

## Implementation Plan

### Phase 1: Move and restructure (foundation)

| # | Task | Description |
|---|------|-------------|
| V1 | Create `src/orthograph/visualization/` package | `__init__.py`, `mermaid.py` |
| V2 | Move `to_mermaid` to new location | Rename to `model_to_mermaid` for clarity |
| V3 | Delete `extensions/visualization/` | Clean break |
| V4 | Update all imports | Notebooks, integration tests, `extensions/__init__.py` |
| V5 | Tests | Move and update `test_mermaid.py` |

### Phase 2: Schema visualization enrichment

| # | Task | Description |
|---|------|-------------|
| V6 | `model_to_mermaid` improvements | Add cardinality labels on edges, required/optional markers on properties, UID field highlighting |
| V7 | `model_to_text` | Plain text table of the model: node types with properties, relationship types with endpoints and cardinality |

### Phase 3: Profile visualization (new)

| # | Task | Description |
|---|------|-------------|
| V8 | `profile_to_text` | Text table of a `GraphProfile`: node types with counts, property completeness, observed types. Relationship types with counts, endpoint labels, cardinality stats. |
| V9 | `profile_to_mermaid` | Mermaid diagram with node counts as labels, completeness-coded edges |

### Phase 4: Validation result visualization (new)

| # | Task | Description |
|---|------|-------------|
| V10 | `result_to_text` | Text summary of `ValidationResult`: grouped by entity, severity-coded |

### Phase 5: Unified API (optional)

| # | Task | Description |
|---|------|-------------|
| V11 | `render()` dispatcher | Single entry point that dispatches based on input type and format parameter |

### Phase 6: HTML reports (future, not in first pass)

| # | Task | Description |
|---|------|-------------|
| V12 | `model_to_html`, `profile_to_html`, `result_to_html` | Jinja2-based HTML reports |

## Input Types and Renderers Matrix

| Input type | `mermaid` | `text` | `html` (future) |
|------------|-----------|--------|------------------|
| `GraphDataModel` | `model_to_mermaid` (exists, enrich) | `model_to_text` (new) | `model_to_html` |
| `GraphProfile` | `profile_to_mermaid` (new) | `profile_to_text` (new) | `profile_to_html` |
| `ValidationResult` | -- | `result_to_text` (new) | `result_to_html` |

## Dependencies

| Renderer | External dependency | When |
|----------|-------------------|------|
| Mermaid text | None | Always available |
| Text table | None | Always available |
| HTML report | Jinja2 (optional) | Future |

## Notebook Plan

| # | Notebook | Content |
|---|----------|---------|
| NB06 | Update: Graph Inspection and Visualization | Update imports to `orthograph.visualization`. Show `model_to_mermaid`, `profile_to_text`, `result_to_text`. |
| NB08 | New: Visualization Showcase | All renderers side by side. Define a model, inspect a graph, validate, then render each artifact in every available format. |

## Implementation Notes for Agents

### Key files to read before implementing

1. `.agentic/index.md` -- overall package layout
2. `.agentic/extensions/overview.md` -- two-phase architecture (visualization consumes its outputs)
3. `src/orthograph/extensions/models.py` -- `GraphProfile` and sub-models (input for profile renderers)
4. `src/orthograph/core/errors.py` -- `ValidationResult`, `ValidationIssue` (input for result renderers)
5. `src/orthograph/core/graph_data_model.py` -- `GraphDataModel` (input for model renderers)
6. `src/orthograph/extensions/visualization/mermaid.py` -- current implementation (to be moved)
7. `tests/extensions/visualization/test_mermaid.py` -- current tests (to be moved)

### Naming convention

- Module names: `mermaid.py`, `text.py`, `html.py` (by output format)
- Function names: `{input_type}_to_{format}` -- e.g., `model_to_mermaid`, `profile_to_text`
- The `render()` dispatcher is a convenience; direct function calls are the primary API

### Testing strategy

- Shared fixtures from `tests/extensions/conftest.py` (model definitions)
- For profile rendering tests: construct `GraphProfile` instances directly (no inspector needed)
- For result rendering tests: construct `ValidationResult` with pre-built `ValidationIssue` list
- Assert on content presence (labels, counts, codes) not exact string matching (formatting may change)

### Strict typing requirements

- All renderer functions take a single typed input and return `str`
- No `Any` in renderer signatures (inputs are always concrete types)
- Frozen Pydantic models throughout (profiles, issues)

### Branch

Implement on a dedicated branch (e.g., `feat/visualization-package`).
The current branch (`CAST-1213-reimplement-extensions-architecture`) should
be merged first to avoid conflicts.
