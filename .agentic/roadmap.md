# Orthograph -- Roadmap

> What is not yet implemented. Use this to plan future work.

## Identified Gaps (from most to least impactful)

### High Priority

| Feature | Description | Effort | Plan |
|---------|-------------|--------|------|
| Visualization package | Move to top-level `visualization/`. Add profile and result renderers (text, mermaid). Enrich model renderer with cardinality and optionality. | Medium | `visualization/plan.md` |
| Schema / Projection hierarchy | Formal distinction between `GraphSchema` (DB truth) and `GraphProjection` (usage subset). A projection can only relax constraints from the schema. Enables "does this query result model make sense given the DB schema?" | Large | -- |
| Custom validators / checks | User-defined validation rules beyond type + structure (like Pandera's `Check`). E.g., regex on property values, range constraints, cross-property rules. | Medium | -- |
| Property value constraints | min/max/regex/enum constraints on property values, beyond Pydantic's built-in `Field` validators. Could leverage Pydantic `Field` directly. | Medium | -- |
| Schema composition / inheritance | Compose schemas from reusable parts. E.g., a chemistry schema that `include`s a generic molecule schema. Conflict resolution model needed. | Medium | -- |

### Medium Priority

| Feature | Description | Effort |
|---------|-------------|--------|
| JSON I/O | JSON configuration loading/saving alongside YAML. Publish a JSON Schema for `.schema.yaml` / `.schema.json` files. | Small |
| Multi-label node support | Neo4j nodes can have multiple labels. Current: pick-the-matching-one. Future: `__labels__` set on NodeModel. | Medium |
| Schema migration / diffing | Compare two `GraphDataModel` versions, generate migration descriptions. Useful for data governance. | Medium |
| Profile export / reporting | Export `GraphProfile` to tabular formats (CSV, HTML, PDF). Integration with reporting tools. Soda-style data quality dashboards. | Medium |
| Async neo4j driver support | Only sync `driver.execute_query()` is used. Async introspection for web applications. | Small |

### Low Priority (future exploration)

| Feature | Description |
|---------|-------------|
| RDF / SHACL extension | Import OWL ontologies, generate SHACL shapes from `GraphDataModel`, validate RDF graphs. |
| GQL / openGQL extension | Support the emerging ISO GQL standard alongside Cypher. |
| CLI tool | Command-line interface for inspection and validation. |
| Additional graph backends | TinkerPop/Gremlin, Amazon Neptune, ArangoDB. |
| Plugin system | Entry-point based backend discovery (like Soda's architecture). |

## Open Technical Questions

| # | Question | Options |
|---|----------|---------|
| T1 | Should `GraphDataModel` be split into `GraphSchema` + `GraphProjection`? | Probably yes -- enables governance workflows. |
| T2 | How should custom checks be declared? Pandera-style `Check` class or Pydantic `Field` + `validator`? | `Check` class is more flexible for graph-specific rules. |
| T3 | Should property value constraints use Pydantic `Field` descriptors or a separate constraint model? | Pydantic `Field` for simple cases, separate model for complex. |
| T4 | Should `GraphProfile` support incremental construction (builder pattern)? | Not yet needed -- inspectors build internally, freeze on return. |
| T5 | For NetworkX inspector, should `observed_types` use Python type names or standardized names? | Currently uses Python names (`str`, `int`). Consider standardizing. |
| T6 | Should the Cypher generator be made dialect-aware (Neo4j vs Memgraph differences)? | Yes, eventually. Current syntax is Neo4j-specific. |

## Open Strategic Questions

| # | Question |
|---|----------|
| S1 | Which projects should adopt orthograph first as a pilot? |
| S2 | Should schema definitions live in project repos or a central registry? |
| S3 | Who owns the schema definition for data governance purposes? |
| S4 | Should `GraphDataModel` become the standard graph schema documentation format? |
| S5 | Are there existing OWL/RDF ontologies that need importers? |
| S6 | What maturity level is required before production use? |
