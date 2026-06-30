# Tutorials

Learn Orthograph by working through it. Every page below is an executable
notebook — read top to bottom, run the cells, and you will have built a graph
definition, validated data against it, generated and governed queries, talked to
real backends, and profiled a live database to detect drift.

The tutorials are organised as a **learning path** across five pillars. Each
pillar builds on the previous one, so the fastest route to fluency is to follow
them in order. If you only need to accomplish a specific task, jump to the
[How-To guides](../how-to/index.md) instead; if you want to understand *why*
Orthograph is shaped the way it is, read the [Explanation](../explanation/index.md).

---

## 1. Graph declaration

Start here. You declare what a valid graph looks like — node and relationship
types, properties, and cardinality — as Pydantic-native models, then validate
data against that declaration. This is the foundation every other pillar depends
on. Cardinality (how many relationships are allowed, and when) gets three
notebooks because it is where most real-world modelling decisions live. See the
[three-layer stack](../explanation/architecture.md) for how a declaration sits between
an ontology and a database schema.

```{toctree}
:maxdepth: 1

../notebooks/01.01_create_a_graph_definition.ipynb
../notebooks/01.02_validating_graph_data.ipynb
../notebooks/01.03_what_is_cardinality.ipynb
../notebooks/01.04_optionality_and_cardinality.ipynb
../notebooks/01.05_conditional_cardinality.ipynb
../notebooks/02.01_yaml_configuration.ipynb
```

## 2. Visualization

A declaration you can see is a declaration you can reason about. This pillar
renders a `GraphDefinition` as a schema diagram so you can sanity-check the model
you wrote in pillar 1 before you build anything on top of it.

```{toctree}
:maxdepth: 1

../notebooks/02.02_visualization.ipynb
```

(query-management-validation)=
## 3. Query management & validation

With a definition in hand, you generate Cypher from it, register hand-written
queries into a typed catalogue, and validate that those queries are consistent
with the definition — the second of Orthograph's two validation engines (data
against a definition; queries against a definition). The later notebooks
introduce typed query contracts, where parameters and result shapes are Pydantic
models. See the [architecture overview](../explanation/architecture.md) for where the
query-set layer fits.

```{toctree}
:maxdepth: 1

../notebooks/03.01_cypher_generation.ipynb
../notebooks/03.02_cypher_query_definitions.ipynb
../notebooks/03.03_cypher_query_usage.ipynb
../notebooks/03.04_typed_query_contracts.ipynb
../notebooks/03.05_typed_query_result_shapes_and_materialization.ipynb
```

## 4. Backends

Now connect to a real graph. The same definition and the same queries run against
NetworkX (in-memory, zero setup), Neo4j, and GQLAlchemy/Memgraph. This pillar also
covers multi-shape relationships — the same label between different endpoint types.
The Neo4j, GQLAlchemy, and multi-shape notebooks require a live database, so they
render from saved outputs in the docs; run them yourself with a database to follow
along.

```{toctree}
:maxdepth: 1

../notebooks/04.01_networkx_backend.ipynb
../notebooks/04.02_neo4j_backend.ipynb
../notebooks/04.03_gqlalchemy_backend.ipynb
../notebooks/04.04_multi_shape_relationships.ipynb
```

(profiling-comparison)=
## 5. Profiling & comparison

The payoff. You inspect a live database into a vendor-free `GraphProfile`, then
compare: profile against definition (does the database match what I declared?),
profile against profile (did two databases drift apart?), and definition against
definition (did my schema change between versions?). The final notebooks cover
profiling conditional cardinality and enum-property coverage. This is drift
detection end to end — see [Explanation](../explanation/architecture.md) for the
declared/observed mirror that makes the comparisons symmetric.

```{toctree}
:maxdepth: 1

../notebooks/05.01_introducing_the_graph_profile.ipynb
../notebooks/05.02_profile_vs_definition.ipynb
../notebooks/05.03_profile_vs_profile.ipynb
../notebooks/05.04_definition_vs_definition.ipynb
../notebooks/05.05_conditional_cardinality_profiling.ipynb
../notebooks/05.06_enum_properties.ipynb
```

---

## Beyond the learning path

The integration notebooks — embedding Orthograph in a **FastAPI** service, a
**Dash** profile explorer, and an **async query runner** — are task-shaped rather
than lesson-shaped, so they live under [How-To](../how-to/index.md) rather than
in this learning path.
