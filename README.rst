Orthograph
==========

Pydantic-native graph data model definition, validation, and query governance.

Orthograph is a **library** — not a platform — that provides a single, authoritative
place for a graph schema to live. It is vendor-agnostic and works with Neo4j, Memgraph,
NetworkX, and raw Cypher.

.. contents::
   :local:
   :depth: 2


What it does
------------

The Python ecosystem has strong schema-validation tools for record-shaped data (Pydantic)
and DataFrames (Pandera), but no equivalent for graph data. Orthograph fills that gap.

It provides three capabilities:

**1. Data model definition**
   Declare node types, relationship types, properties, and cardinality constraints once —
   in Python or YAML — and use that declaration as the single source of truth across all
   query and validation paths.

**2. Data and database validation**
   Validate in-memory graph data before it reaches the database, or inspect a live
   database and compare its structure against the declared model. Both paths produce a
   structured ``ValidationResult`` with typed, differentiable error codes.

**3. Query governance and drift detection**
   Register named Cypher queries in a typed ``QueryCatalogue``. Each query declares its
   ``Params`` and ``Output`` models; the catalogue validates parameter alignment at
   class-definition time and provides a uniform ``describe()`` surface for introspection.
   Queries are checked — without executing them — for language correctness and for
   *domain match* against the model (labels, relationship types, properties, endpoints).
   ``validate_query_catalogue()`` detects drift between a whole query set and the data model;
   ``validate_query_catalogue_against_profile()`` extends that to the live database schema,
   so schema evolution never silently desynchronises your queries and your database from
   the declared model.

Orthograph never owns a database connection. When it needs one — to inspect, validate
results, or execute a query — the caller passes it in.


Extensions
----------

The core library (model definition and data validation) has no external dependencies
beyond Pydantic and PyYAML. Database-specific functionality is packaged as optional
backend extras:

===============  ====================================================================
Extension        What it adds
===============  ====================================================================
``neo4j``        ``Neo4jInspector`` — inspects a live Neo4j database and produces a
                 ``GraphProfile``; ``validate_database()`` compares the profile
                 against a declared model. *(See* ``.agentic/notes/`` *for type-
                 detection strategy details.)*
``memgraph``     ``MemgraphInspector`` — same interface as the Neo4j inspector,
                 using Memgraph's schema procedures via the Bolt driver.
``networkx``     ``NetworkxInspector`` — in-process inspection of a
                 ``nx.MultiDiGraph``; ``schema_to_networkx()`` converts a model to a
                 NetworkX graph for visualisation and analysis.
``cypher``       ``CypherGenerator`` (auto-generates CRUD queries from the model),
                 ``CypherExecutor`` (the single graph-driver I/O seam for the typed
                 catalogue), ``validate_cypher()`` (static Cypher validation against
                 the model), and the full ``CypherReadQuery`` / ``CypherWriteQuery``
                 base-class hierarchy.
``gqlalchemy``   ``GqlAlchemyClient`` (schema-validated save/load via the GQLAlchemy
                 ORM), ``ValidatedQueryBuilder`` (Cypher-validated fluent queries),
                 and auto-generated GQLAlchemy ``Node`` / ``Relationship`` classes
                 from the Orthograph model.
===============  ====================================================================


Installation

------------

Create a dedicated Python environment first:

.. code-block:: shell

   python -m venv .venv && source .venv/bin/activate   # or: conda create -n ortho python=3.12

Install the core library:

.. code-block:: shell

   pip install orthograph

Install with a specific extension:

.. code-block:: shell

   pip install "orthograph[neo4j]"
   pip install "orthograph[memgraph]"
   pip install "orthograph[cypher]"
   pip install "orthograph[networkx]"

Install everything:

.. code-block:: shell

   pip install "orthograph[all]"

For development (all extensions + test/lint tooling):

.. code-block:: shell

   git clone <repo-url>
   cd orthograph
   pip install -e ".[dev]"


Quick start
-----------

Define the model:

.. code-block:: python

   from typing import Optional
   from orthograph.graph_definition.graph_definition import GraphDataModel
   from orthograph.graph_definition.node_model import NodeModel
   from orthograph.graph_definition.relationship_model import RelationshipModel

   class Person(NodeModel):
       __label__ = "Person"
       __uid_field__ = "name"
       name: str
       born: Optional[int] = None

   class Movie(NodeModel):
       __label__ = "Movie"
       __uid_field__ = "title"
       title: str
       year: int

   class ActedIn(RelationshipModel):
       __label__ = "ACTED_IN"
       __source_type__ = Person
       __target_type__ = Movie
       role: str

   graph_data_model = GraphDataModel(
        name="Filmography",
        node_types=[Person, Movie],
        relationship_types=[ActedIn],
    )

Validate in-memory data before writing to the database:

.. code-block:: python

   from orthograph.api.model import validate

   nodes = [
       {"__label__": "Person", "name": "Alice", "born": 1985},
       {"__label__": "Movie",  "title": "Inception", "year": 2010},
   ]
   relationships = [
       {"__label__": "ACTED_IN", "source": "Alice", "target": "Inception",
        "role": "Lead"},
   ]

   result = validate(graph_data_model, nodes, relationships)
   print(result.is_valid)      # True / False
   for issue in result.errors:
       print(issue)            # structured ValidationIssue with error code

Inspect a live Neo4j database and validate it against the model:

.. code-block:: python

   from neo4j import GraphDatabase
   from orthograph.api.database import validate

   driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
   result = validate("neo4j", driver, graph_data_model)

   print(result.is_valid)
   for error in result.errors:
       print(error)

Define and register a typed Cypher query:

.. code-block:: python

   from orthograph.cypher.base_models import CypherReadQuery
   from orthograph.cypher.bindings import NoParams
   from orthograph.catalogue.registry import QueryCatalogue

   class PersonByNameParams(BaseModel):
       name: str

   class FindPerson(CypherReadQuery[PersonByNameParams, Person]):
       Params = PersonByNameParams
       Output = Person
       name = "find_person_by_name"
       cypher_template = "MATCH (p:Person {name: $name}) RETURN p"

       def materialize(self, raw):
           return Person.model_validate(raw["p"])

   query_catalogue = QueryCatalogue()
   query_catalogue.register_read(FindPerson())


Running the tests
-----------------

Test categories
~~~~~~~~~~~~~~~

The test suite has three layers:

* **Unit / mock tests** — all source modules are covered; no external dependencies.
  These are what CI runs by default.
* **In-process integration tests** (``tests/test_integration.py``) — exercise the full
  public API against in-memory data (NetworkX, YAML, Python-only workflows). No network.
* **Live-DB end-to-end tests** — require a running database; skipped by default; opt in
  with a CLI flag.

Unit tests (CI default)
~~~~~~~~~~~~~~~~~~~~~~~

No external services required:

.. code-block:: shell

   pytest

All unit and mock-based tests pass. Live-DB tests are silently skipped.

Live Neo4j tests
~~~~~~~~~~~~~~~~

.. code-block:: shell

   pytest --neo4j

With non-default credentials or port:

.. code-block:: shell

   pytest --neo4j \
          --neo4j-uri      bolt://localhost:7687 \
          --neo4j-user     neo4j \
          --neo4j-password secret

What the live Neo4j tests cover:

* APOC auto-detection — the inspector detects whether APOC procedures are installed
  and selects the pure-Cypher fallback when they are not.
* Empty database — ``inspect()`` returns no relationship profiles and empty node
  profiles. (Neo4j retains label tokens after ``DELETE``, so ``node_labels`` may be
  non-empty, but counts and property maps are always empty.)
* Node profiles — counts, property names, mandatory vs optional properties (a property
  absent on at least one node of its label is optional).
* Relationship profiles — type detection, edge counts, property names.
* Endpoint labels — ``source_labels`` / ``target_labels`` are populated via the
  endpoint-labels query, which is required for ``INVALID_ENDPOINT`` validation to fire
  on live databases.
* Cardinality statistics — ``min_degree``, ``max_degree``, ``avg_degree``,
  ``sample_size`` computed against the confirmed source label, not against all node
  labels.
* Cardinality regression — asserts that cardinality is not computed against a
  target-only label, which would produce ``min=0 max=0`` (the pre-fix bug).
* ``validate_database()`` — passes for a matching model; reports
  ``MISSING_NODE_LABEL`` when a declared node type has no instances; reports
  ``INVALID_ENDPOINT`` when a relationship endpoint does not match the database.
* Identifier injection guard — ``CypherIdentifierError`` is raised by ``build()``
  before any Cypher reaches the driver.
* Internal catalogue — after ``inspect()``, the inspector's internal
  ``QueryCatalogue`` holds the expected set of named typed queries.

Each test uses a ``neo4j_clean`` fixture (defined in the root ``conftest.py``) that
runs ``MATCH (n) DETACH DELETE n`` both before and after the test, so tests are fully
independent and leave no residue.

Live Memgraph tests
~~~~~~~~~~~~~~~~~~~

.. code-block:: shell

   pytest --memgraph

With non-default URI:

.. code-block:: shell

   pytest --memgraph \
          --memgraph-uri      bolt://localhost:7688 \
          --memgraph-user     "" \
          --memgraph-password ""

The live Memgraph tests cover the same surface as the Neo4j tests. The following
parity gaps are documented explicitly in the test record (the tests assert the known
values rather than skipping the checks silently):

==================================================  ===========  ================================================
Field                                               Neo4j        Memgraph
==================================================  ===========  ================================================
``NodeTypeProfile.count``                           actual       always 0 — schema procedures yield no counts
``RelationshipTypeProfile.count``                   actual       always 0, same reason
``PropertyProfile.present_count / .total_count``    observation  mandatory heuristic (``int(mandatory)`` / ``1``)
``source_labels`` / ``target_labels``               populated    populated
``cardinality_stats``                               populated    populated
==================================================  ===========  ================================================

Connection options
~~~~~~~~~~~~~~~~~~

All options default to a stock local installation. Override on the command line:

======================  =========================  ================================
Option                  Default                    Description
======================  =========================  ================================
``--neo4j-uri``         ``bolt://localhost:7687``  Bolt URI for Neo4j
``--neo4j-user``        ``neo4j``                  Neo4j username
``--neo4j-password``    *(required via CLI)*       Neo4j password (no default)
``--memgraph-uri``      ``bolt://localhost:7688``  Bolt URI for Memgraph
``--memgraph-user``     *(empty)*                  Memgraph username (no default)
``--memgraph-password`` *(empty)*                  Memgraph password (no default)
======================  =========================  ================================

Credential Management
~~~~~~~~~~~~~~~~~~~~~

Credentials are managed **separately** for tests and notebooks:

**For tests**: Use CLI arguments to pass credentials (no .env file loading).

.. code-block:: shell

    # Run with Neo4j
    pytest --neo4j --neo4j-password <your-password>

    # Run with Memgraph
    pytest --memgraph --memgraph-user <user> --memgraph-password <password>

    # Both
    pytest --neo4j --neo4j-password <pw> --memgraph --memgraph-password <pw>

This approach is CI/CD-friendly: credentials are never stored in the repo, and
secrets can be injected via environment variables or CI secrets management.
Tests have zero knowledge of `.env` files — credentials are always explicit.

**For notebooks**: Credentials are loaded from ``notebooks/.env``.

1. Copy the template:

   .. code-block:: shell

      cp notebooks/.env_default notebooks/.env

2. Edit ``notebooks/.env`` with your database connection details.
3. The ``.env`` file is git-ignored and will never be committed.

Notebooks that require a live database (``03.02_neo4j_end_to_end.ipynb``,
``03.04_gqlalchemy_database_interaction.ipynb``) use the ``env_helper.py``
module to load credentials from ``notebooks/.env``.

Example notebook cell:

.. code-block:: python

    from env_helper import load_env

    neo4j_uri = load_env("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = load_env("NEO4J_USER", "neo4j")
    neo4j_password = load_env("NEO4J_PASSWORD", "password")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

Connection options
~~~~~~~~~

The ``notebooks/`` directory contains executable reference notebooks. Run them via
`nbval <https://github.com/computationalmodelling/nbval>`_:

.. code-block:: shell

   pytest notebooks/ --nbval-lax              # CI-safe notebooks only
   pytest notebooks/ --nbval-lax --neo4j      # + Neo4j notebooks

Notebooks that require a live database are excluded from collection unless the
corresponding flag is passed. The following notebooks require a running Neo4j instance:

* ``03.02_neo4j_end_to_end.ipynb``
* ``03.04_gqlalchemy_database_interaction.ipynb``
* ``06.01_profile_neo4j_example.ipynb``
* ``06.02_profile_neo4j_custom.ipynb``

Some notebooks also require optional dependencies (e.g., ``fastapi``, ``httpx`` for the OpenAPI
notebook). These are installed with the ``notebooks`` extra.

Adding a new live-DB test
~~~~~~~~~~~~~~~~~~~~~~~~~

Decorate the test with the relevant marker:

.. code-block:: python

   @pytest.mark.neo4j
   def test_something(neo4j_driver, neo4j_clean):
       ...

   @pytest.mark.memgraph
   def test_something(memgraph_driver, memgraph_clean):
       ...

The ``neo4j_driver`` / ``memgraph_driver`` fixtures are session-scoped (one connection
per test run). The ``neo4j_clean`` / ``memgraph_clean`` fixtures are function-scoped and
wipe the database before and after each test.

For a DB-requiring notebook, add an entry to ``_DB_NOTEBOOKS`` in
``notebooks/conftest.py``:

.. code-block:: python

    _DB_NOTEBOOKS: dict[str, str] = {
        "your_notebook_name.ipynb": "neo4j",  # or "memgraph"
    }

This ensures the notebook is skipped in CI by default and only runs when the corresponding
flag is passed (e.g., ``pytest notebooks/ --nbval-lax --neo4j``).

Full matrix
~~~~~~~~~~~

.. code-block:: shell

   # Unit + mock tests (CI default)
   pytest

   # Unit + Neo4j live tests
   pytest --neo4j --neo4j-password <pw>

   # Unit + Memgraph live tests
   pytest --memgraph

   # Everything
   pytest --neo4j --neo4j-password <pw> --memgraph

   # With coverage
   pytest --cov=src/orthograph --cov-report=term-missing
