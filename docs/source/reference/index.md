# Reference

API reference for the public surface (the seven root modules and the vendor-free Cypher tooling).

## definition

Author, persist, and validate graph definitions.

```{autosummary}
:toctree: generated

orthograph.definition.NodeModel
orthograph.definition.RelationshipModel
orthograph.definition.GraphDefinition
orthograph.definition.CardinalitySpec
orthograph.definition.ConditionalCardinality
orthograph.definition.ConditionalRule
orthograph.definition.PropMatch
orthograph.definition.validate_definition
orthograph.definition.validate_data
orthograph.definition.load_from_file
orthograph.definition.save_to_file
orthograph.definition.load_yaml_string
```

## profile

Inspect backends into a vendor-free graph profile.

```{autosummary}
:toctree: generated

orthograph.profile.inspect_neo4j
orthograph.profile.inspect_memgraph
orthograph.profile.inspect_networkx
orthograph.profile.check_connection
orthograph.profile.GraphProfile
orthograph.profile.NodeTypeProfile
orthograph.profile.RelationshipTypeProfile
orthograph.profile.PropertyProfile
orthograph.profile.CardinalityStats
orthograph.profile.BoundedDistribution
orthograph.profile.PartitionKey
orthograph.profile.PartitionedCardinalityRow
orthograph.profile.ConstraintInfo
orthograph.profile.BoltDriver
orthograph.profile.MultiDiGraph
orthograph.profile.Neo4jInspectionStrategy
```

## compare

Compare profiles and definitions for validation.

```{autosummary}
:toctree: generated

orthograph.compare.profile_to_definition
orthograph.compare.profiles
orthograph.compare.definitions
orthograph.compare.Rule
```

## queries

Author, build, catalogue, validate, and generate Cypher queries.

```{autosummary}
:toctree: generated

orthograph.queries.QueryCatalogue
orthograph.queries.CypherQuery
orthograph.queries.TypedCypherReadQueryModel
orthograph.queries.TypedCypherWriteQueryModel
orthograph.queries.NoParams
orthograph.queries.NoIdentifiers
orthograph.queries.new_catalogue
orthograph.queries.load_catalogue
orthograph.queries.simple_query
orthograph.queries.generate_crud
orthograph.queries.parse_cypher
orthograph.queries.check_syntax
orthograph.queries.validate
orthograph.queries.validate_catalogue
orthograph.queries.validate_catalogue_against_profile
orthograph.queries.check_cypher_spec
orthograph.queries.validate_cypher_spec
orthograph.queries.CypherGenerator
orthograph.queries.CypherQueryError
orthograph.queries.CypherCatalogueLoadError
orthograph.queries.CypherQueryDefinitionError
```

## execution

Run typed read/write queries against backends.

```{autosummary}
:toctree: generated

orthograph.execution.run_read
orthograph.execution.run_write
orthograph.execution.run_read_async
orthograph.execution.run_write_async
orthograph.execution.run_cypher_fetch
orthograph.execution.run_cypher_execute
orthograph.execution.run_cypher_fetch_async
orthograph.execution.run_cypher_execute_async
orthograph.execution.ReadQueryModel
orthograph.execution.WriteQueryModel
orthograph.execution.CypherExecutor
orthograph.execution.CypherQueryExecutor
orthograph.execution.AsyncCypherQueryExecutor
orthograph.execution.CypherWriteResultSummary
orthograph.execution.ReadPort
orthograph.execution.QueryBackedReadPort
orthograph.execution.AsyncExecutor
orthograph.execution.AsyncReadPort
orthograph.execution.AsyncQueryBackedReadPort
orthograph.execution.Backend
```

## discovery

Discover installed backends and their capabilities.

```{autosummary}
:toctree: generated

orthograph.discovery.available
orthograph.discovery.is_available
orthograph.discovery.can_inspect
orthograph.discovery.can_execute
```

## rendering

Render definitions, profiles, and validation results.

```{autosummary}
:toctree: generated

orthograph.rendering.render_model
orthograph.rendering.render_profile
orthograph.rendering.render_result
orthograph.rendering.display
orthograph.rendering.RenderFormat
```

## cypher

Vendor-free Cypher query-language tooling.

```{autosummary}
:toctree: generated

orthograph.cypher.base_models.TypedCypherReadQueryModel
orthograph.cypher.base_models.TypedCypherWriteQueryModel
orthograph.cypher.bindings.NoParams
orthograph.cypher.bindings.NoIdentifiers
orthograph.cypher.query.CypherQuery
orthograph.cypher.exceptions.CypherQueryError
orthograph.cypher.exceptions.CypherCatalogueLoadError
orthograph.cypher.exceptions.CypherQueryDefinitionError
```
