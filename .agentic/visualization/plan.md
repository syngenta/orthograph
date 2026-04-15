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
from orthograph.visualization.mermaid import model_to_mermaid
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

### New top-level package (IMPLEMENTED)

```
src/orthograph/
├── visualization/              # Top-level subpackage
│   ├── __init__.py             # render() dispatcher + re-exports
│   ├── mermaid.py              # model_to_mermaid, display_mermaid
│   └── text.py                 # model_to_text, profile_to_text, result_to_text
```

Tests:
```
tests/visualization/
├── __init__.py
├── test_mermaid.py             # model mermaid renderers, display_mermaid, URL builder
├── test_text.py                # 23 tests (model, profile, result text renderers)
└── test_render.py              # dispatcher tests
```

### What gets deleted

- `src/orthograph/extensions/visualization/` (entire directory)
- `tests/extensions/visualization/` (entire directory)

### Import path changes

| Old | New |
|-----|-----|
| `from orthograph.extensions.visualization import to_mermaid` | `from orthograph.visualization import render` or `from orthograph.visualization.mermaid import model_to_mermaid` |

## Implementation Plan

> **Status: Phases 1-5 IMPLEMENTED** (2026-04-14, branch CAST-1224)

### Phase 1: Move and restructure (foundation) -- DONE

| # | Task | Description | Status |
|---|------|-------------|--------|
| V1 | Create `src/orthograph/visualization/` package | `__init__.py`, `mermaid.py`, `text.py` | done |
| V2 | Move `to_mermaid` to new location | Renamed to `model_to_mermaid` | done |
| V3 | Delete `extensions/visualization/` | Clean break | done |
| V4 | Update all imports | Notebooks, integration tests | done |
| V5 | Tests | Moved to `tests/visualization/` | done |

### Phase 2: Schema visualization enrichment -- DONE

| # | Task | Description | Status |
|---|------|-------------|--------|
| V6 | `model_to_mermaid` improvements | Cardinality labels, required/optional markers, UID highlighting | done |
| V7 | `model_to_text` | Plain text table of model | done |

### Phase 3: Profile visualization (new) -- DONE

| # | Task | Description | Status |
|---|------|-------------|--------|
| V8 | `profile_to_text` | Text table with counts, completeness, cardinality stats | done |
| V9 | `profile_to_mermaid` | Not implemented -- profile is statistical, Mermaid is for schema structure | removed |

### Phase 4: Validation result visualization (new) -- DONE

| # | Task | Description | Status |
|---|------|-------------|--------|
| V9 | `result_to_text` | Severity-coded text summary grouped by entity | done |

### Phase 5: Unified API -- DONE

| # | Task | Description | Status |
|---|------|-------------|--------|
| V10 | `render()` dispatcher | Single entry point dispatching on input type and format | done |
| V11 | `display_mermaid()` | Inline Mermaid image in Jupyter via mermaid.ink; soft IPython import | done |

### Phase 6: HTML reports (future, not yet implemented)

| # | Task | Description | Status |
|---|------|-------------|--------|
| V12 | `model_to_html`, `profile_to_html`, `result_to_html` | Jinja2-based HTML reports | pending |

## Input Types and Renderers Matrix

| Input type | `mermaid` | `text` | `html` (future) |
|------------|-----------|--------|------------------|
| `GraphDataModel` | `model_to_mermaid` (exists, enrich) | `model_to_text` (new) | `model_to_html` |
| `GraphProfile` | -- | `profile_to_text` (new) | `profile_to_html` |
| `ValidationResult` | -- | `result_to_text` (new) | `result_to_html` |

## Dependencies

| Renderer | External dependency | When |
|----------|-------------------|------|
| Mermaid text | None | Always available |
| Text table | None | Always available |
| HTML report | Jinja2 (optional) | Future |

## Notebook Plan

| # | Notebook | Content | Status |
|---|----------|---------|--------|
| NB06 | NetworkX Graph Inspection and Validation | Filmography domain. NetworkxInspector, GraphProfile exploration, validate_profile, schema_to_networkx, profile serialisation. | done |
| NB07 | Neo4j End-to-End (Reference) | Filmography domain. Full Neo4j workflow (unchanged). | done |
| NB08 | Visualization | Filmography domain. All renderers: model_to_mermaid, model_to_text, profile_to_text, result_to_text, display_mermaid, render() dispatcher, schema-vs-observed comparison. | done |

## Implementation Notes

### Key design decisions made

- `profile_to_mermaid` was not implemented: Mermaid diagrams represent schema structure; profiles are statistical summaries best rendered as text tables
- `[UID]` marker in `model_to_mermaid` uses plain `UID` text (no square brackets) -- square brackets inside Mermaid `["..."]` quoted labels break the parser and cause mermaid.ink to return a broken image
- `_mermaid_ink_url` uses `base64.urlsafe_b64encode` (RFC 4648) -- standard base64 `+`/`/` characters are not URL-safe
- `display_mermaid` soft-imports IPython at call time and raises a clear `ImportError` if not in a notebook environment
- `render(profile, format="mermaid")` raises `ValueError` -- mermaid format is only meaningful for `GraphDataModel`

### Naming convention

- Module names: `mermaid.py`, `text.py` (by output format)
- Function names: `{input_type}_to_{format}` -- e.g., `model_to_mermaid`, `profile_to_text`
- The `render()` dispatcher is a convenience; direct function calls are the primary API

### Branch

Implemented on branch `CAST-1224-change-architecture-of-visualization-module`.
