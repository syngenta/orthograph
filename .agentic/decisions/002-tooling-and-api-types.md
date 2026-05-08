# ADR-002: Tooling and API Type Refinements

**Date:** 2026-04-10
**Status:** Accepted
**Category:** tooling

## Context

Pre-commit review revealed several type system and tooling issues that required
immediate design decisions. These are distinct from the core architecture decisions
(ADR-001) and relate to how the codebase is maintained.

## Decisions

### Validator API: `list` -> `Sequence` (covariant input types)

Pre-commit mypy revealed that `list[dict[str, Any] | NodeModel]` is invariant.
Users passing `list[dict[str, Any]]` (the common case) would get type errors.
Changed all public validator input parameters from `list[...]` to
`Sequence[...]` (from `collections.abc`). `Sequence` is covariant, so
`list[dict]` satisfies `Sequence[dict | NodeModel]`. Return types stay concrete.

### Test Style: pytest functions over unittest classes

All tests refactored from `class TestX:` with `self` to plain `def test_x():`
functions. Imports moved to module level. Prefixed names for uniqueness
(e.g. `test_cardinality_spec_create_with_min_and_max`).

### mypy Config: single source in mypy.ini

Removed duplicate `[tool.mypy]` from pyproject.toml. All mypy config lives
in mypy.ini exclusively. Added pydantic.mypy plugin, per-module overrides
for tests (relaxed), networkx extension (allow unimported Any), and
legacy code (ignored).

### Pre-commit Dependencies

Added pytest, networkx, pyyaml, types-PyYAML to the mypy pre-commit
hook's additional_dependencies. Without these, mypy cannot resolve
`@pytest.fixture()` return types or networkx/yaml types.

### Ruff Exclusions

Excluded `src/orthograph_legacy`, `notebooks`, `build` from ruff linting.
These are not active code and should not block the pre-commit pipeline.

### Removed Stale `type: ignore` Comments

The pydantic mypy plugin makes dynamic class creation in `io/yaml.py`
type-safe. Removed 4 unnecessary `# type: ignore` comments that were
suppressing non-existent errors.
