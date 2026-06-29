# Epic E20: Technical Debt

> **Priority:** Medium
> **Phase:** v0.1.0 — Pilot Readiness
> **Origin:** E17 refactor session 2026-06-10. General tech-debt bucket — each sub-section
> records a distinct finding with its own origin date and scope note.
> **Blocked by:** None — tasks here are independent unless noted. Coordinate with epics
> actively editing the same modules.

---

## T0: `from __future__ import annotations` — normalise across the codebase

> **Origin:** E8.1 session 2026-06-11
> **Priority:** Low — cosmetic; no runtime impact on py3.10+
> **Scope:** `src/` + `tests/`

**Finding.** The import is used inconsistently across the project:

- 8 source files and 7 test files carry it (all in the `gqlalchemy`, `networkx`, and
  `cypher/exceptions` modules).
- `cypher/base_models.py` — the primary mirror target — does **not** have it.
- Only one file (`cypher/exceptions.py`) **strictly requires** it: it imports `ValidationIssue`
  under `TYPE_CHECKING`, and without deferred evaluation that name would fail at runtime.
- All other files compile and run fine on py3.10+ without it (PEP 604 `X | Y` unions evaluate
  at runtime since py3.10; no forward-reference annotations were found).
- The ruff ruleset (`E,W,F,I`) does not include `UP010` (unnecessary `__future__` import), so
  tooling neither enforces nor forbids the import today.

**Decision surface.** Three coherent positions:

1. **Remove everywhere except `cypher/exceptions.py`** — matches the `cypher/base_models.py`
   precedent; rely on py3.10 runtime union support. Enable `ruff UP010` to enforce going forward.
2. **Add everywhere** — consistent with the majority of `gqlalchemy/` files; costs nothing.
3. **Leave as-is** — do nothing; inconsistency is a cosmetic annoyance but causes no failures.

**Recommended action (when picked up):**
1. Decide option 1, 2, or 3 and record the rationale here.
2. If option 1: run `sed`/ruff-fix to strip the import from all files except
   `cypher/exceptions.py`; enable `ruff UP010` (add `"UP010"` to `select` in `pyproject.toml`).
3. If option 2: add the import to the remaining files without it.
4. Run `pytest` + `mypy src/` + `ruff check` green before closing.

**Acceptance criteria:**
- [ ] Decision recorded (option 1/2/3) with rationale.
- [ ] If option 1 or 2: all files consistent; ruff clean; pytest + mypy green.
- [ ] `cypher/exceptions.py` retains the import regardless of chosen option.

---

## T7: Cypher validation does not distinguish a `$param` from a backtick-escaped identifier

> **Origin:** Notebook review session 2026-06-16 (`notebooks/05.01_openapi_ergonomics_assessment.ipynb`)
> **Priority:** Medium — silent correctness gap; affects definition-time *and* runtime Cypher validation.
> **Scope:** `src/orthograph/cypher/parser.py`, `src/orthograph/cypher/bindings.py`, `src/orthograph/cypher/base_models.py`
> **Relates to:** Epic E18 (validation correctness).

**Finding.** A `cypher_template` that wraps a parameter in backticks — e.g.
`` MATCH (m:Movie {released: `$released`}) `` — passes **every** validation layer Orthograph
currently has, yet is semantically wrong: in Cypher a backtick-quoted token is an *escaped
identifier*, not a parameter, so the driver never binds `$released` and the query silently
fails to filter (returns nothing / errors against a live driver).

Verified empirically (graphglot 2026-06 build, neo4j dialect):

- **graphglot parse** (`parse_cypher`) accepts both forms without error. The tokenizer reveals
  why: `` `$released` `` lexes to a **single `VAR` token** `'$released'` (an escaped identifier
  literally named `$released`), whereas the correct `$released` lexes to two tokens
  `DOLLAR_SIGN` + `VAR`. Both produce structurally identical lineage graphs, so the
  definition-time dialect parse in `_validate_declarative_cypher` cannot tell them apart.
- **Alignment checker** (`check_placeholder_alignment` → `extract_cypher_params`,
  `bindings.py:52`) uses the regex `\$([A-Za-z_][A-Za-z0-9_]*)`, which matches `$released`
  regardless of surrounding backticks. So the `$param` ↔ `Params`-field 1:1 check also goes
  green on the broken form.
- **Runtime check** (`CypherExecutor._validate_cypher`) reuses `parse_cypher`, so it inherits
  the same blind spot.

**Net effect.** The only thing that catches the mistake is a real driver returning wrong
results — exactly the "fail silently" failure mode the PRD exists to prevent. A consumer
copying a backtick template from documentation gets a green definition-time validation and a
silently broken query.

**Decision surface.**

1. **Lint in `_validate_declarative_cypher`** — after extracting `$param` names, scan the
   template for the pattern `` `\$NAME` `` (a parameter immediately wrapped in backticks) and
   raise `CypherQueryDefinitionError` with a fix hint ("remove the backticks around `$NAME`;
   parameters must not be backtick-quoted"). Cheap, regex-only, no graphglot dependency.
2. **Push upstream to graphglot** — ask graphglot to expose recognised parameter bindings on
   the lineage graph (`lg.parameters` is currently `None`) so Orthograph can assert that each
   regex-extracted `$param` corresponds to a real parameter node, not a `VAR`. More robust but
   depends on an external roadmap.
3. **Both** — ship the regex lint now (option 1) as a guard; track option 2 as the principled
   fix once graphglot surfaces parameter lineage.

**Recommended action (when picked up):** option 3. Land the regex lint immediately; file the
graphglot feature request and link it here.

**Related graphglot gap — `LIMIT $param` does not parse.** While fixing the backtick templates
in the §05.01 notebook, the bundled graphglot (neo4j dialect) was found to **reject a
parameterised `LIMIT`**: `RETURN m LIMIT $limit` raises `ParseError: Expected parameter name or
number after $`. `SKIP $skip` parses; `LIMIT $limit`, `LIMIT toInteger($limit)`, and
`SKIP $skip LIMIT $limit` all fail. Only a literal `LIMIT 100` parses. Consequences:

- A declarative paginated `CypherReadQuery` (the natural use of `PaginatedParams`) **cannot be
  defined** — `_validate_declarative_cypher` raises at class-definition time. The gap also bites
  at **runtime**: `CypherExecutor.read` re-parses the built Cypher via `_validate_cypher`, so even
  an imperative `build()` that emits `LIMIT $limit` raises `CypherSyntaxError` on every request.
- The §05.01 notebook works around this with the **imperative `build()` escape hatch** (no
  `cypher_template`) that **inlines `skip`/`limit` as integer literals** (`SKIP 0 LIMIT 100`),
  which graphglot parses. This is injection-safe because `PaginatedParams` validates them as
  bounded ints; the year filter stays a real `$released` parameter.
- This is an upstream graphglot parser limitation, not an Orthograph bug, but it directly blocks
  the headline pagination ergonomic. File a graphglot issue for `LIMIT <parameter>` support and
  link it here; until then, document the imperative-`build()` workaround in the pagination guide.

**Acceptance criteria:**
- [ ] A `cypher_template` containing `` `$param` `` raises `CypherQueryDefinitionError` at
      class-definition time with an actionable message.
- [ ] The lint does **not** false-positive on legitimate backtick-escaped *identifiers* that
      are not parameters (e.g. `` (n:`My Label`) ``) or on `<<name>>` identifier placeholders.
- [ ] Regression test covers: backtick-wrapped `$param` (rejected), clean `$param` (accepted),
      backtick-escaped label with no param (accepted).
- [ ] `pytest` + `mypy src/` + `ruff check` green.

---

## Error Hierarchy & Library Logging Discipline (tasks E20.1 – E20.11)

> **Origin:** E17 refactor session 2026-06-10 (Cypher exception hierarchy introduced; surfaced
> the absence of a project-wide exception root and any logging convention). Re-pathed onto the
> post-ADR-017 / post-ADR-041 topology and re-cut into context-free, model-tagged tasks on
> 2026-06-29.
>
> **Relates to:** PRD Problem Statement ("applications fail silently"), PRD Constraint 13
> (Orthograph never owns a connection — it is a library, not an application), ADR-017 (package
> topology — `diagnostics/` is the dependency-free shared layer), ADR-041 (root capability
> modules; the `api/` layer was removed; root modules are thin re-export shims over subpackages).
>
> **SCOPE NOTE:** Establishes two cross-cutting foundations and migrates existing code onto them.
> Does NOT invent diagnostics features, metrics, structured-event emission, or application-level
> observability. The library emits diagnostics through the stdlib `logging` module and raises a
> coherent exception hierarchy; configuring sinks, levels, and formatting remains the consuming
> application's responsibility.

### Standing decisions (do not re-litigate — they are inputs to the tasks below)

- **D1. Single root.** Every error Orthograph raises derives from `OrthographError`, directly or
  via a mid-tier base. A consumer can `except OrthographError` to isolate all library errors.
- **D2. Three mid-tier groups by *kind*** (not by subpackage):
  - `OrthographUsageError` — the caller misused the API / definitions / queries.
  - `OrthographValidationError` — a graph or data set failed validation.
  - `OrthographBackendError` — a live-DB / driver / optional-dependency problem.
  Concrete and subpackage-base exceptions reparent under the appropriate *kind*.
- **D3. Real code lives in `diagnostics/`** (the dependency-free shared layer, ADR-017):
  `diagnostics/errors.py` and `diagnostics/logging.py`. The root modules `orthograph/errors.py`
  and `orthograph/logging.py` are **thin re-export shims** mirroring the capability-module
  pattern (ADR-041).
- **D4. Differentiation is by subclass + message**, never by docstring "possible causes" lists
  (the E17 anti-stale-docstring rule, project-wide).
- **D5. Library logging hygiene.** Attach a `logging.NullHandler` to the top-level `orthograph`
  logger. Never call `basicConfig`, never add non-null handlers, never set levels on any logger,
  never `print` for diagnostics. Loggers are named by module `__name__` under the `orthograph.*`
  tree, obtained via `get_logger`.
- **D6. Self-logging error→log bridge.** `OrthographError.__init__` logs itself once, at a
  per-class `log_level` (default `logging.DEBUG`). `OrthographBackendError` raises that to
  `logging.ERROR`; `MissingDependencyError` overrides back to `logging.DEBUG` (it is expected
  during backend probing). Rationale: every raised error leaves a trace without the noise/
  double-logging that an unconditional ERROR-on-construct would cause. (Decided in ADR-047.)
- **D7. raise vs warn vs log.** *raise* (hierarchy) for caller errors the caller must handle;
  `warnings.warn` for authoring advisories a developer should see once (the existing imperative-
  query `UserWarning` in `cypher/base_models.py` and the `DeprecationWarning` in
  `backends/neo4j/inspector.py` stay as-is); `logging` for operational events (skipped record,
  fallback chosen, retry).
- **D8. ADR numbers.** Allocate **ADR-047** (error hierarchy) and **ADR-048** (library logging).
  The numbers 011/012 cited in older notes are stale (already taken).
- **D9. Builtin boundary.** Prefer the hierarchy over `TypeError`/`ValueError` for *library-domain*
  errors; leave genuinely generic type/value misuse as builtins where that is the honest signal.

### Execution order & dependencies

```
E20.1  diagnostics/logging.py   (real logging helper)        ── independent
E20.2  __init__.py NullHandler  (depends on E20.1)
E20.3  diagnostics/errors.py    (root + mid-tier + self-log)  (depends on E20.1)
E20.4  reparent GraphValidationError       (depends on E20.3)
E20.5  reparent CypherError                (depends on E20.3)
E20.6  reparent ModelDefinitionError       (depends on E20.3)
E20.7  reparent MissingDependencyError     (depends on E20.3)
E20.8  orthograph/errors.py shim           (depends on E20.4–E20.7)
E20.9  orthograph/logging.py shim          (depends on E20.1)
E20.10 migrate networkx inspector logger   (depends on E20.1)
E20.11 ADR-047 + ADR-048 + CONTEXT links   (depends on E20.3, E20.1; do last)
```

Each task below is self-contained: it states exactly which file to touch, the current content,
the new content, and how to verify. An executing agent needs no context beyond its own task.

---

### E20.1 — Create `diagnostics/logging.py` logging helper  · model: **haiku**

**File to CREATE:** `src/orthograph/diagnostics/logging.py`

**Why:** Give the library one entry point for obtaining a logger, named under the `orthograph.*`
tree. Pure stdlib wrapper, no dependencies.

**Exact content to write:**

```python
"""Library logging helper (dependency-free).

Orthograph is a library, not an application: it never configures logging,
sets levels, or adds handlers. It only obtains named loggers under the
``orthograph.*`` tree via :func:`get_logger`. The consuming application owns
all sink/level/format configuration. A ``NullHandler`` is attached to the
top-level ``orthograph`` logger in ``orthograph/__init__.py`` so the library
emits nothing unless the application opts in.
"""

import logging


def get_logger(name: str) -> logging.Logger:
    """Return the stdlib logger named ``name``.

    Call as ``get_logger(__name__)`` so the logger sits under the
    ``orthograph.*`` name tree (e.g. ``orthograph.cypher.validation``).
    """
    return logging.getLogger(name)
```

**Verify:**
- `python -c "from orthograph.diagnostics.logging import get_logger; print(get_logger('orthograph.x').name)"`
  prints `orthograph.x`.
- `ruff check src/orthograph/diagnostics/logging.py` clean.

**Acceptance criteria:**
- [ ] File exists with exactly the content above.
- [ ] Import works; `get_logger("orthograph.x").name == "orthograph.x"`.

---

### E20.2 — Attach a `NullHandler` to the `orthograph` logger  · model: **haiku**

**Depends on:** E20.1.
**File to EDIT:** `src/orthograph/__init__.py`

**Why:** A library must never emit to a handler the application did not opt into. A single
`NullHandler` on the top-level `orthograph` logger guarantees silence by default.

**Current relevant content (around line 42):**

```python
import importlib.metadata

from orthograph import (  # noqa: F401  (re-exported as public surface)
    compare,
    definition,
    discovery,
    execution,
    profile,
    queries,
    rendering,
)
```

**Change:** Immediately AFTER the line `import importlib.metadata`, insert these two lines:

```python
import logging as _logging

_logging.getLogger("orthograph").addHandler(_logging.NullHandler())
```

Use the alias `_logging` to avoid any name clash with the future `orthograph.logging`
submodule (E20.9) and to keep it out of the public namespace.

**Verify (must produce NO output on stderr):**
```
python -W error -c "import logging, sys; logging.disable(logging.NOTSET); import orthograph; logging.getLogger('orthograph.test').warning('should be swallowed')"
```
The warning must NOT appear on stderr (the `NullHandler` plus the default "no configured
handler" rule swallow it).

**Acceptance criteria:**
- [ ] `logging.getLogger("orthograph").handlers` contains exactly one `NullHandler` after
      `import orthograph`.
- [ ] Importing `orthograph` and logging a warning under `orthograph.*` produces no stderr output.
- [ ] `import orthograph` still succeeds; `ruff check` clean.

---

### E20.3 — Create `diagnostics/errors.py`: root + mid-tier groups + self-logging  · model: **sonnet**

**Depends on:** E20.1.
**File to CREATE:** `src/orthograph/diagnostics/errors.py`

**Why:** Establish the single project-wide exception root (`OrthographError`), the three mid-tier
groups by kind, and the self-logging bridge so every raised error leaves a trace (decisions D1,
D2, D6).

**Exact content to write:**

```python
"""Project-wide exception hierarchy (dependency-free).

``OrthographError`` is the single root every Orthograph-raised error derives
from, directly or via one of the three mid-tier groups:

* :class:`OrthographUsageError`      — the caller misused the API/definitions/queries.
* :class:`OrthographValidationError` — a graph or data set failed validation.
* :class:`OrthographBackendError`    — a live-DB / driver / optional-dependency problem.

Self-logging: every error logs itself once on construction, at the class-level
``log_level`` (default ``DEBUG``). This guarantees a trace without the noise of
an unconditional ``ERROR``-on-construct. Subclasses override ``log_level`` to
raise or lower the level (see ``OrthographBackendError``).
"""

import logging

from orthograph.diagnostics.logging import get_logger


class OrthographError(Exception):
    """Root of every error Orthograph raises.

    Differentiation is by subclass and message — never by a docstring list of
    causes. The message carries the specifics.
    """

    #: Level at which this error logs itself on construction.
    log_level: int = logging.DEBUG

    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        get_logger(type(self).__module__).log(
            self.log_level, "%s: %s", type(self).__name__, self
        )


class OrthographUsageError(OrthographError):
    """The caller misused the API, a model definition, or a query."""


class OrthographValidationError(OrthographError):
    """A graph or data set failed validation."""


class OrthographBackendError(OrthographError):
    """A live-database, driver, or optional-dependency problem."""

    log_level = logging.ERROR
```

**Verify:**
```
python -c "from orthograph.diagnostics.errors import OrthographError, OrthographUsageError, OrthographValidationError, OrthographBackendError; assert issubclass(OrthographUsageError, OrthographError); assert OrthographBackendError.log_level==40; assert OrthographError.log_level==10; print('ok')"
```
- `mypy src/orthograph/diagnostics/errors.py` clean; `ruff check` clean.

**Acceptance criteria:**
- [ ] File exists with exactly the content above.
- [ ] The three mid-tier classes subclass `OrthographError`.
- [ ] `OrthographError.log_level == logging.DEBUG` (10); `OrthographBackendError.log_level == logging.ERROR` (40).
- [ ] Constructing `OrthographError("msg")` logs one record at DEBUG to logger
      `orthograph.diagnostics.errors` (capturable via pytest `caplog`); no stderr output by default.

---

### E20.4 — Reparent `GraphValidationError` under `OrthographValidationError`  · model: **sonnet**

**Depends on:** E20.3.
**File to EDIT:** `src/orthograph/diagnostics/result.py`

**Why:** Make graph-validation failures catchable as `OrthographError` / `OrthographValidationError`
(D1, D2) while preserving the existing `.issues` attribute and message.

**Current content (lines 8–12 and 34–40):**

```python
from typing import Any

from pydantic import BaseModel, Field

from orthograph.diagnostics.classification import EntityType, Severity
```
```python
class GraphValidationError(Exception):
    """Raised when graph validation fails."""

    def __init__(self, issues: list["ValidationIssue"]) -> None:
        self.issues = issues
        messages = [str(i) for i in issues]
        super().__init__("\n".join(messages))
```

**Change 1 — imports.** After the line
`from orthograph.diagnostics.classification import EntityType, Severity`, add:

```python
from orthograph.diagnostics.errors import OrthographValidationError
```

**Change 2 — base class.** Change the class declaration line
`class GraphValidationError(Exception):` to:

```python
class GraphValidationError(OrthographValidationError):
```

Leave the `__init__` body unchanged (it still sets `self.issues` and joins messages; the
self-logging happens via the new base's `super().__init__`).

**Verify:**
```
python -c "from orthograph.diagnostics.result import GraphValidationError, ValidationResult; from orthograph.diagnostics.errors import OrthographError; assert issubclass(GraphValidationError, OrthographError); print('ok')"
```
- Existing tests still green: `pytest tests/diagnostics -q`.
- `mypy src/` clean.

**Acceptance criteria:**
- [ ] `GraphValidationError` subclasses `OrthographValidationError` (hence `OrthographError`).
- [ ] `.issues` still populated; message text unchanged.
- [ ] `tests/diagnostics` green; `mypy src/` clean.

---

### E20.5 — Reparent `CypherError` under `OrthographUsageError`  · model: **sonnet**

**Depends on:** E20.3.
**File to EDIT:** `src/orthograph/cypher/exceptions.py`

**Why:** Cypher errors are caller/authoring errors (D2 → Usage). Reparenting the package base
moves every concrete Cypher exception under the root automatically (they already inherit
`CypherError`).

**Current content (lines 3–9):**

```python
from __future__ import annotations

from orthograph.diagnostics.result import ValidationIssue


class CypherError(Exception):
    """Base class for every exception raised by the Cypher extension."""
```

**Change 1 — import.** After the line
`from orthograph.diagnostics.result import ValidationIssue`, add:

```python
from orthograph.diagnostics.errors import OrthographUsageError
```

**Change 2 — base class.** Change `class CypherError(Exception):` to:

```python
class CypherError(OrthographUsageError):
```

Do NOT change any other class in the file — they inherit `CypherError` and are reparented
transitively. Keep `CypherModelValidationError.__init__` exactly as-is.

**Verify:**
```
python -c "from orthograph.cypher.exceptions import CypherError, CypherSyntaxError; from orthograph.diagnostics.errors import OrthographError; assert issubclass(CypherSyntaxError, OrthographError); print('ok')"
```
- `pytest tests/cypher/test_exceptions.py -q` green.
- `mypy src/` clean.

**Acceptance criteria:**
- [ ] `CypherError` subclasses `OrthographUsageError`; `CypherSyntaxError` etc. catchable as
      `OrthographError`.
- [ ] `tests/cypher/test_exceptions.py` green; `mypy src/` clean.

---

### E20.6 — Reparent `ModelDefinitionError` under `OrthographUsageError`  · model: **sonnet**

**Depends on:** E20.3.
**File to EDIT:** `src/orthograph/graph_definition/exceptions.py`

**Why:** Model-definition errors are programmer/authoring errors (D2 → Usage).

**Current content (lines 1–5):**

```python
"""Model-definition exceptions for the graph definition layer."""


class ModelDefinitionError(Exception):
    """Base for model-definition programming errors."""
```

**Change 1 — import.** After the module docstring line
`"""Model-definition exceptions for the graph definition layer."""`, add a blank line then:

```python
from orthograph.diagnostics.errors import OrthographUsageError
```

**Change 2 — base class.** Change `class ModelDefinitionError(Exception):` to:

```python
class ModelDefinitionError(OrthographUsageError):
```

Leave `MissingClassVarError`, `MissingUidFieldError`, `AmbiguousCardinalityError`, and
`CardinalityParseError` unchanged (they inherit `ModelDefinitionError`).

**Verify:**
```
python -c "from orthograph.graph_definition.exceptions import ModelDefinitionError, CardinalityParseError; from orthograph.diagnostics.errors import OrthographError; assert issubclass(CardinalityParseError, OrthographError); print('ok')"
```
- `pytest tests/graph_definition/test_exceptions.py -q` green.
- `mypy src/` clean.

**Note for executor:** This introduces an import from `diagnostics` into `graph_definition`.
That direction is allowed (diagnostics is the dependency-free leaf). If `pytest
tests/test_dependencies.py` or `tests/test_architecture.py` fails on a layering rule, STOP and
report — do not weaken the layering test; flag it in the PR.

**Acceptance criteria:**
- [ ] `ModelDefinitionError` subclasses `OrthographUsageError`; subclasses catchable as `OrthographError`.
- [ ] `tests/graph_definition/test_exceptions.py` green; `mypy src/` clean.
- [ ] `tests/test_architecture.py` and `tests/test_dependencies.py` still green (or blocker reported).

---

### E20.7 — Reparent `MissingDependencyError` under `OrthographBackendError`  · model: **sonnet**

**Depends on:** E20.3.
**File to EDIT:** `src/orthograph/dependencies.py`

**Why:** A missing optional dependency is a backend problem (D2 → Backend). It must remain an
`ImportError` for back-compat, AND join the hierarchy. It is *expected* during backend probing,
so it overrides `log_level` back to DEBUG (D6).

**Current content (lines 7–20):**

```python
from __future__ import annotations

import importlib.util
import sys

from orthograph.backends.registry import BACKENDS, Kind


# Re-export Kind for backward compatibility
__all__ = ["Kind", "MissingDependencyError", "is_available", "require"]


class MissingDependencyError(ImportError):
    """Raised when an optional dependency required for a backend is absent."""
```

**Change 1 — imports.** After the line
`from orthograph.backends.registry import BACKENDS, Kind`, add:

```python
import logging

from orthograph.diagnostics.errors import OrthographBackendError
```
(Put `import logging` with the other stdlib imports — i.e. after `import sys` — and the
`from orthograph...` line after the existing `from orthograph.backends.registry` import, to keep
import groups tidy for ruff/isort.)

**Change 2 — class.** Replace:

```python
class MissingDependencyError(ImportError):
    """Raised when an optional dependency required for a backend is absent."""
```
with:

```python
class MissingDependencyError(OrthographBackendError, ImportError):
    """Raised when an optional dependency required for a backend is absent.

    Multiple-inheritance keeps both ``except OrthographError`` and the
    historical ``except ImportError`` working. It is expected during backend
    probing, so it logs at DEBUG rather than the ``OrthographBackendError``
    default of ERROR.
    """

    log_level = logging.DEBUG
```

The MRO `(OrthographBackendError, ImportError)` makes it an `OrthographError` first while
remaining an `ImportError`.

**Verify:**
```
python -c "from orthograph.dependencies import MissingDependencyError as M; from orthograph.diagnostics.errors import OrthographError; assert issubclass(M, OrthographError) and issubclass(M, ImportError); assert M.log_level==10; print('ok')"
```
- `pytest tests/backends/test_loader.py tests/test_dependencies.py -q` green (adjust if no such
  file — run `pytest -q -k dependenc` ).
- `mypy src/` clean.

**Acceptance criteria:**
- [ ] `MissingDependencyError` is both an `OrthographError` and an `ImportError`.
- [ ] `MissingDependencyError.log_level == logging.DEBUG`.
- [ ] Existing dependency/loader tests green; `mypy src/` clean.

---

### E20.8 — Create the root shim `orthograph/errors.py`  · model: **sonnet**

**Depends on:** E20.4, E20.5, E20.6, E20.7.
**File to CREATE:** `src/orthograph/errors.py`

**Why:** Mirror the capability-module pattern (ADR-041): a thin root module re-exporting the
error surface so consumers write `from orthograph.errors import OrthographError, CypherSyntaxError`.
No logic lives here.

**Exact content to write:**

```python
"""Public error surface for Orthograph.

Thin re-export shim (mirrors the capability-module pattern, ADR-041). The real
hierarchy lives in :mod:`orthograph.diagnostics.errors`; concrete errors live
in their owning subpackages. Catch :class:`OrthographError` to isolate every
error this library raises.
"""

from orthograph.cypher.exceptions import (
    CypherCatalogueLoadError,
    CypherError,
    CypherIdentifierError,
    CypherModelValidationError,
    CypherQueryDefinitionError,
    CypherQueryError,
    CypherSyntaxError,
    CypherUnknownLabelError,
    CypherUnknownPropertyError,
)
from orthograph.dependencies import MissingDependencyError
from orthograph.diagnostics.errors import (
    OrthographBackendError,
    OrthographError,
    OrthographUsageError,
    OrthographValidationError,
)
from orthograph.diagnostics.result import GraphValidationError
from orthograph.graph_definition.exceptions import (
    AmbiguousCardinalityError,
    CardinalityParseError,
    MissingClassVarError,
    MissingUidFieldError,
    ModelDefinitionError,
)


__all__ = [
    # root + mid-tier
    "OrthographError",
    "OrthographUsageError",
    "OrthographValidationError",
    "OrthographBackendError",
    # validation
    "GraphValidationError",
    # cypher
    "CypherError",
    "CypherQueryDefinitionError",
    "CypherSyntaxError",
    "CypherIdentifierError",
    "CypherUnknownLabelError",
    "CypherUnknownPropertyError",
    "CypherModelValidationError",
    "CypherQueryError",
    "CypherCatalogueLoadError",
    # model definition
    "ModelDefinitionError",
    "MissingClassVarError",
    "MissingUidFieldError",
    "AmbiguousCardinalityError",
    "CardinalityParseError",
    # backend / dependency
    "MissingDependencyError",
]
```

**Then EDIT** `src/orthograph/__init__.py` to expose the module on the root, matching the
existing capability-module pattern:
- In the `from orthograph import ( ... )` block, add `errors,` (keep alphabetical-ish order with
  the others; the `# noqa: F401` comment on that import statement already covers it).
- In the `__all__` list, add `"errors",`.

**Verify:**
```
python -c "from orthograph.errors import OrthographError, CypherSyntaxError, GraphValidationError, MissingDependencyError; import orthograph; assert orthograph.errors.OrthographError is OrthographError; print('ok')"
```
- `mypy src/` clean; `ruff check` clean; `pytest -q` green.

**Acceptance criteria:**
- [ ] `from orthograph.errors import <any name in __all__>` works.
- [ ] `import orthograph; orthograph.errors.OrthographError` resolves.
- [ ] `mypy src/`, `ruff check`, full `pytest` green.

---

### E20.9 — Create the root shim `orthograph/logging.py`  · model: **haiku**

**Depends on:** E20.1.
**File to CREATE:** `src/orthograph/logging.py`

**Why:** Public logging surface mirroring the capability-module pattern; documents the
integration contract for consuming applications (they configure the `orthograph` logger).

> **Executor caution:** this module is named `logging` and will shadow the stdlib `logging`
> *for code that imports it as a submodule of `orthograph`*. It must NOT itself do
> `import logging` at top level in a way that re-imports itself. The content below imports only
> from `orthograph.diagnostics.logging`, so there is no self-shadowing. Do not add
> `import logging` to this file.

**Exact content to write:**

```python
"""Public logging surface for Orthograph.

Thin re-export shim (mirrors the capability-module pattern, ADR-041). The real
helper lives in :mod:`orthograph.diagnostics.logging`.

Orthograph is a library, not an application: it attaches a ``NullHandler`` to
the top-level ``orthograph`` logger and never configures levels, handlers, or
formatting. To see Orthograph's operational logs, the consuming application
configures the ``orthograph`` logger, e.g.::

    import logging
    logging.getLogger("orthograph").setLevel(logging.DEBUG)

Level convention used by the library:

* ``DEBUG``   — internal steps (query compiled, backend round-trip, cache hit),
                and every raised :class:`~orthograph.errors.OrthographError` by
                default.
* ``INFO``    — user-meaningful milestones (profile inspected, catalogue loaded).
* ``WARNING`` — library-level concerns (deprecated argument, fallback path taken).
* ``ERROR``   — backend/driver failures (raised ``OrthographBackendError`` logs here).
"""

from orthograph.diagnostics.logging import get_logger


__all__ = ["get_logger"]
```

**Then EDIT** `src/orthograph/__init__.py` to expose the module on the root:
- add `logging,` to the `from orthograph import ( ... )` re-export block (the existing
  `# noqa: F401` covers it); BUT note the `_logging` alias from E20.2 — do NOT remove that alias;
  it stays for the `NullHandler` line. Add the public `logging` submodule re-export separately.
- add `"logging",` to `__all__`.

**Verify:**
```
python -c "import orthograph; from orthograph.logging import get_logger; assert orthograph.logging.get_logger is get_logger; print('ok')"
```
- Confirm stdlib logging still works elsewhere: `python -c "import orthograph; import logging; logging.getLogger('x')"` (no error).
- `mypy src/` clean; `ruff check` clean; `pytest -q` green.

**Acceptance criteria:**
- [ ] `from orthograph.logging import get_logger` works; `orthograph.logging.get_logger` resolves.
- [ ] `import orthograph` followed by stdlib `import logging` still works (no shadowing breakage).
- [ ] `mypy src/`, `ruff check`, full `pytest` green.

---

### E20.10 — Migrate the NetworkX inspector logger to `get_logger`  · model: **haiku**

**Depends on:** E20.1.
**File to EDIT:** `src/orthograph/backends/networkx/inspector.py`

**Why:** Bring the one pre-existing ad-hoc logger onto the convention (D5). Behaviour is
unchanged; this is a sourcing swap.

**Current content (lines 5 and 32):**

```python
import logging
```
```python
logger = logging.getLogger(__name__)
```

**Change 1 — import.** Remove the top-level `import logging` (line 5) ONLY IF `logging` is not
used anywhere else in the file. Run a search for `logging.` in the file first:
- If `logging.` appears elsewhere, KEEP `import logging` and only change the logger line.
- If it does NOT (expected — only the `getLogger` call uses it), remove `import logging`.

**Change 2 — add the helper import.** Add, grouped with the other `from orthograph...` imports:

```python
from orthograph.diagnostics.logging import get_logger
```

**Change 3 — logger line.** Change `logger = logging.getLogger(__name__)` to:

```python
logger = get_logger(__name__)
```

Leave the three `logger.warning(...)` call sites (lines ~91, ~134, ~145) UNCHANGED.

**Verify:**
- `pytest tests/backends/networkx -q` green.
- `python -c "import orthograph.backends.networkx.inspector"` imports without error.
- `ruff check src/orthograph/backends/networkx/inspector.py` clean (no unused `import logging`).
- `mypy src/` clean.

**Acceptance criteria:**
- [ ] `logger = get_logger(__name__)`; the three `logger.warning` calls unchanged.
- [ ] No unused `import logging` remains.
- [ ] `tests/backends/networkx` green; `ruff` + `mypy` clean.

---

### E20.11 — Write ADR-047 + ADR-048 and add CONTEXT cross-links  · model: **opus**

**Depends on:** E20.3 (errors) and E20.1/E20.2 (logging) being implemented, so the ADRs describe
shipped reality. Do this LAST.

**Files to CREATE:**
- `.agentic/decisions/047-error-hierarchy.md`
- `.agentic/decisions/048-library-logging.md`

**File to EDIT:** `.agentic/CONTEXT.md` (add two routing rows).

**ADR-047 (`047-error-hierarchy.md`) must record:**
- The decision: single `OrthographError` root in `diagnostics/errors.py`; three mid-tier groups
  by *kind* (`OrthographUsageError` / `OrthographValidationError` / `OrthographBackendError`);
  concrete/subpackage exceptions reparent under the appropriate kind; root shim
  `orthograph/errors.py` re-exports the surface (mirrors ADR-041).
- The mapping shipped: `CypherError`/`ModelDefinitionError` → Usage; `GraphValidationError` →
  Validation; `MissingDependencyError(OrthographBackendError, ImportError)` → Backend.
- D4 (differentiation by subclass+message, no stale cause-lists) and D9 (builtin boundary:
  library-domain → hierarchy; honest generic misuse → builtins).
- **The self-logging decision (D6)** and its rationale: log-on-construct at per-class
  `log_level`, DEBUG default, Backend→ERROR, MissingDependency→DEBUG; why this avoids the
  double-logging / noise of an unconditional ERROR-on-construct, and that the *catcher* (not the
  raiser) decides whether a handled error is noise.
- Rejected alternatives: (a) no root / bare builtins everywhere; (b) two-level shape
  (root→subpackage-base→concrete) instead of by-kind; (c) unconditional ERROR-on-construct.

**ADR-048 (`048-library-logging.md`) must record:**
- The decision: `get_logger` helper in `diagnostics/logging.py`; `NullHandler` on the top-level
  `orthograph` logger in `__init__.py`; root shim `orthograph/logging.py` re-exports `get_logger`
  and documents the consumer-config contract and level convention.
- Library hygiene rules (D5): never `basicConfig`, never add non-null handlers, never set levels,
  never `print` for diagnostics; loggers named by `__name__` under `orthograph.*`.
- raise-vs-warn-vs-log boundary (D7), explicitly noting the two preserved `warnings.warn` sites
  (`cypher/base_models.py` UserWarning; `backends/neo4j/inspector.py` DeprecationWarning).
- The level convention table (DEBUG/INFO/WARNING/ERROR) as shipped in `orthograph/logging.py`.
- Rejected alternative: ad-hoc `getLogger` per module with no `NullHandler`; a structured-logging
  dependency (structlog/loguru) — rejected, stdlib name tree is the universal contract.

**CONTEXT.md edits** — add two rows to the "Navigate" table (do NOT duplicate ADR content):
- `| What is the project-wide error hierarchy and how do errors self-log? | [decisions/047-error-hierarchy.md](decisions/047-error-hierarchy.md) — public surface is the `orthograph.errors` shim |`
- `| How does the library log, and how does a consuming app capture Orthograph logs? | [decisions/048-library-logging.md](decisions/048-library-logging.md) — public surface is the `orthograph.logging` shim (`get_logger`) |`

**Verify:**
- Both ADR files exist and follow the format of an existing ADR (open
  `.agentic/decisions/046-documentation-architecture.md` as a template for headings/front-matter).
- CONTEXT.md has the two new rows and renders as a valid Markdown table.
- An agent reading CONTEXT.md can reach both ADRs in one hop.

**Acceptance criteria:**
- [ ] ADR-047 and ADR-048 exist, matching the house ADR format, recording the decisions above.
- [ ] CONTEXT.md links both ADRs from the Navigate table.
- [ ] No ADR content duplicated into CONTEXT.md.

---

### Success Criteria (Error Hierarchy & Logging — whole sub-epic)

- [ ] `OrthographError` root exists in `diagnostics/errors.py`; every library-raised domain error
      derives from it via a kind-group (E20.3–E20.7).
- [ ] Every error self-logs once on construction at its `log_level`; DEBUG by default, Backend→ERROR,
      MissingDependency→DEBUG; no stderr output without app config (E20.3, verified per task).
- [ ] `orthograph/errors.py` and `orthograph/logging.py` shims expose the public surface and are
      reachable as `orthograph.errors.*` / `orthograph.logging.*` (E20.8, E20.9).
- [ ] The library attaches a `NullHandler`; `get_logger` is the one logging entry point (E20.1, E20.2).
- [ ] The one pre-existing ad-hoc logger is migrated; no `print(` diagnostics exist in `src/`
      (E20.10; note: the three `print(` hits in `rendering.py`/`__init__.py` are docstring examples,
      not diagnostics — leave them).
- [ ] ADR-047 + ADR-048 record the decisions; CONTEXT.md links both (E20.11).
- [ ] `mypy src/` clean; `ruff check` clean; full `pytest` green.

### Out of Scope (Error Hierarchy & Logging)

- Application-level observability: metrics, tracing, structured-event emission, log shipping.
- Changing `warnings.warn` semantics or removing existing user advisories.
- Async logging, custom handlers/formatters, or any sink configuration (application concern).
- Reworking `ValidationResult` / `ValidationIssue` (value-objects, not exceptions).
- A blanket conversion of every builtin `TypeError`/`ValueError` to custom types — only
  *library-domain* errors migrate (per the ADR-047 builtin boundary).
- Migrating bare `raise TypeError/ValueError` sites across `src/` to the hierarchy — deferred;
  if wanted, add as a follow-up task E20.12 (sonnet) with an explicit audit list.
