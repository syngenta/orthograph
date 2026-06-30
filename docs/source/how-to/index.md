# How-To

Task-oriented guides. Each page states a single goal and the steps to reach it.
For learning-path material, see [Tutorials](../tutorials/index.md). For symbol
lookup, see [Reference](../reference/index.md).

```{toctree}
:hidden:

validate-data
detect-drift
govern-query-catalogue
compare-definitions
../notebooks/06.01_fastapi_integration.ipynb
../notebooks/06.02_dash_profile_explorer.ipynb
```

## Validation

- [Validate in-memory data](validate-data.md) — check nodes and relationships against a `GraphDefinition` before writing to a database.

## Drift detection

- [Profile a live Neo4j database and detect drift](detect-drift.md) — inspect a running database and compare the result against a declared contract.
- [Compare two definitions (version drift)](compare-definitions.md) — diff two `GraphDefinition` versions to surface structural divergence.

## Query governance

- [Register and validate a typed query catalogue](govern-query-catalogue.md) — register Cypher queries and verify the entire set against a `GraphDefinition` without executing them.

## Integrations

Wire Orthograph's typed query contracts and `GraphProfile` into an application framework.

- {doc}`Embed Orthograph in a FastAPI service <../notebooks/06.01_fastapi_integration>` — route validated Cypher and typed result shapes through FastAPI endpoints using `TestClient`.
- {doc}`Build a Dash profile explorer <../notebooks/06.02_dash_profile_explorer>` — surface a `GraphProfile` (counts, completeness, cardinality distributions) as an interactive Dash dashboard.
