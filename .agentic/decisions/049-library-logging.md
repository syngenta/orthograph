# ADR-049: Library Logging Discipline — NullHandler, Named Loggers, `get_logger`

> **Status:** Accepted
> **Date:** 2026-06-30
> **Relates to:** PRD Constraint 13 (Orthograph is a library, not an application),
>   ADR-017 (package topology — `diagnostics/` is the dependency-free shared layer),
>   ADR-041 (root capability modules — `orthograph/logging.py` mirrors this pattern),
>   ADR-048 (error hierarchy — `OrthographError.__init__` uses `get_logger`)
> **Implements:** E20.1, E20.2, E20.9, E20.10 (Error Hierarchy & Logging sub-epic of E20)

---

## Context

Before this ADR, Orthograph had one ad-hoc logger in
`backends/networkx/inspector.py` obtained via `logging.getLogger(__name__)` at
module level — the Python stdlib convention, but undocumented as a project pattern
and without the `NullHandler` that a library must attach to avoid polluting the
consuming application's logging output.

The Python docs (PEP 3110, `logging.config` howto) are explicit: **a library must
never configure logging**. It must attach a `NullHandler` to its top-level logger so
that if the application has not configured any handler, the library emits nothing.
Without this, Python's "last resort" handler prints WARNING+ to stderr for every
`getLogger` call that escapes unhandled — exactly the "fail silently" / "surprise
output" failure modes the PRD exists to prevent.

The E20 sub-epic introduces the self-logging bridge (`OrthographError.__init__` logs
on construct, ADR-048 §D6), making a clear, documented logging convention a
prerequisite rather than a cosmetic nice-to-have.

---

## Decision

### D1 — `get_logger` is the single library entry point for obtaining loggers

`src/orthograph/diagnostics/logging.py` provides one function:

```python
def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
```

All library code calls `get_logger(__name__)`. Direct `logging.getLogger(...)` calls
in library source are migrated to `get_logger`. This is a thin wrapper — no framework
dependency, no custom class — whose value is documentation and discoverability: a
single grep for `get_logger` finds every logger the library creates.

### D2 — `NullHandler` on the top-level `orthograph` logger

`src/orthograph/__init__.py` attaches a `NullHandler` to the `orthograph` logger
immediately on import:

```python
import logging as _logging
_logging.getLogger("orthograph").addHandler(_logging.NullHandler())
```

The `_logging` alias avoids any name clash with the `orthograph.logging` submodule
(E20.9 / D4). The handler is attached in `__init__.py` so it is in place before any
submodule logger fires.

**Effect:** importing `orthograph` and logging at any level under `orthograph.*` produces
no output unless the consuming application opts in by configuring the `orthograph` logger.

### D3 — Library hygiene rules (never configure, never print)

Library source (`src/orthograph/**`) must never:
- call `logging.basicConfig()`
- add a non-`NullHandler` handler to any logger
- call `logger.setLevel()` or `logging.disable()`
- use `print()` for diagnostics

Loggers are named by module `__name__` so they sit under the `orthograph.*` hierarchy.
The consuming application retains full control of sinks, levels, and formatting.

### D4 — Root shim `orthograph/logging.py` (ADR-041 mirror)

`src/orthograph/logging.py` is a thin re-export shim that:
1. Re-exports `get_logger` from `orthograph.diagnostics.logging`.
2. Documents the consumer integration contract (how to opt in to library logs).
3. Documents the level convention used across the library.

It does **not** import `logging` (stdlib) at top level to avoid self-shadowing; it
only imports from `orthograph.diagnostics.logging`.

Consumer opt-in example (from the shim's module docstring):

```python
import logging
logging.getLogger("orthograph").setLevel(logging.DEBUG)
```

### D5 — Level convention

| Level | Library usage |
|---|---|
| `DEBUG` | Internal steps: query compiled, backend round-trip, cache hit; and every raised `OrthographError` by default (ADR-048 §D6) |
| `INFO` | User-meaningful milestones: profile inspected, catalogue loaded |
| `WARNING` | Library-level concerns: deprecated argument, fallback path taken |
| `ERROR` | Backend/driver failures: raised `OrthographBackendError` logs here (ADR-048 §D6) |

### D6 — raise-vs-warn-vs-log boundary

Three mechanisms, each for a distinct purpose:

| Mechanism | When | Examples |
|---|---|---|
| `raise` (hierarchy) | Caller error the caller must handle | Wrong argument, bad template, missing field |
| `warnings.warn` | Authoring advisory a developer should see once | Deprecated argument, imperative-query escape hatch |
| `logging` | Operational event the application may want to observe | Skipped record, fallback chosen, retry |

Two `warnings.warn` sites are explicitly preserved and not migrated:
- `cypher/base_models.py`: `UserWarning` for the imperative-query escape hatch.
- `backends/neo4j/inspector.py`: `DeprecationWarning` for a legacy inspection path.

---

## Consequences

**Positive**
- Importing `orthograph` is silent by default; no surprise stderr output.
- A single `logging.getLogger("orthograph").setLevel(logging.DEBUG)` in the application
  reveals all library internals, including the self-logging error trace (ADR-048 §D6).
- `get_logger` is grepable: one command finds every logger in the library.
- The shim (`orthograph.logging.get_logger`) is the documented integration point for
  library extensions that want to stay under the `orthograph.*` tree.

**Negative / costs**
- `orthograph/logging.py` shadows the stdlib `logging` module for code that does
  `import orthograph.logging`. Internal library code must continue to use
  `from orthograph.diagnostics.logging import get_logger` or plain `import logging`
  for stdlib access — not `import orthograph.logging`.
- A `get_logger` indirection over `logging.getLogger` adds one call frame that
  appears in stack traces (trivial; inline-optimised at the CPython level).

**Neutral**
- The library does not adopt structlog, loguru, or any other structured-logging
  framework. The stdlib name tree (`orthograph.*`) is the universal contract that works
  with every application framework without adding a dependency.

---

## Alternatives considered

1. **Ad-hoc `logging.getLogger(__name__)` per module, no `NullHandler`.**
   Rejected: produces surprise WARNING+ output on stderr in applications that have not
   configured a handler; no discoverability guarantee; the self-logging bridge (ADR-048)
   requires a well-defined convention.

2. **Structured-logging dependency (structlog / loguru).**
   Rejected: adds a mandatory runtime dependency to a library that is explicitly
   dependency-light (ADR-017 `diagnostics/` is dependency-free). Consumers that want
   structlog can route the stdlib `orthograph.*` logger through their own structlog
   processor chain.

3. **Application-owned logger injection (pass a logger into every function).**
   Rejected: leaks logging as a parameter across the entire API surface; the `orthograph.*`
   name tree is the stable public contract and requires no injection.
