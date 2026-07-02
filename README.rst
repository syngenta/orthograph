Orthograph
==========

.. image:: https://img.shields.io/pypi/v/orthograph
   :target: https://pypi.python.org/pypi/orthograph
   :alt: PyPI - Version
.. image:: https://static.pepy.tech/badge/orthograph/month
   :target: https://pepy.tech/project/orthograph
   :alt: Downloads monthly
.. image:: https://static.pepy.tech/badge/orthograph
   :target: https://pepy.tech/project/orthograph
   :alt: Downloads total
.. image:: https://img.shields.io/github/actions/workflow/status/syngenta/orthograph/ci.yml?branch=dev
   :alt: GitHub Workflow Status
.. image:: https://readthedocs.org/projects/orthograph/badge/?version=latest
   :target: https://orthograph.readthedocs.io/en/latest/?badge=latest
   :alt: Documentation Status
.. image:: https://img.shields.io/badge/contributions-welcome-blue
   :target: https://github.com/syngenta/orthograph/blob/main/CONTRIBUTING.md
   :alt: Contributions
.. image:: https://img.shields.io/badge/license-MIT-blue.svg
   :target: https://opensource.org/licenses/MIT
.. image:: https://img.shields.io/badge/repo%20status-Active-Green?style=for-the-badge
   :target: https://www.repostatus.org/#active
   :alt: Project Status: Active
.. image:: https://img.shields.io/pypi/pyversions/orthograph.svg?style=for-the-badge
   :target: https://pypi.python.org/pypi/orthograph/
   :alt: PyPI pyversions

---------------------

Pydantic-native graph data governance: one declared contract for your property
graph, continuously checked against your data, your queries, and your live
database.

Orthograph is a **library** — not a platform, not an ORM — that gives a property
graph the thing it usually lacks: a single declared contract the application can
read, and an enforcement loop around it. You declare node types, relationship
types, properties, and cardinalities once in Python or YAML; Orthograph then
validates data against that contract, governs a typed Cypher query catalogue, and
detects drift between the contract and a live database. It sits *above* the
database, driver, and any ORM, and never owns a connection — the caller passes one
in when Orthograph needs it.

It is vendor-agnostic and works with Neo4j, Memgraph, NetworkX, and raw Cypher.

Full documentation: https://orthograph.readthedocs.io

.. contents::
   :local:
   :depth: 2


What it does
------------

Property graphs are schema-flexible by design. That flexibility is an asset
during exploration and a liability in production: properties get loosely typed,
cardinalities are assumed but never checked, queries are raw strings that keep
running after a label is renamed (returning wrong or empty results with no
error), and the live database drifts away from the model nobody wrote down.
The database's own constraints enforce only a subset, below the application, and
are not the same as the application's *intended* contract.

Orthograph closes that gap with four distinct capabilities:

**1. Define the contract**
   Declare node types, relationship types, properties, and cardinality
   constraints once — in Python or YAML — and use that declaration as the single
   source of truth across every validation and query path.

**2. Validate data**
   Validate in-memory graph data against the contract before it reaches the
   database. Produces a structured ``ValidationResult`` with typed,
   differentiable error codes.

**3. Govern queries**
   Register named Cypher queries in a typed ``QueryCatalogue``. Each query
   declares its parameter and output models; the catalogue validates
   parameter↔template alignment at registration and checks each query — *without
   executing it* — for Cypher language correctness and for domain match against
   the contract (labels, relationship types, properties, endpoints).

**4. Detect drift**
   Detect divergence across the three-layer stack. ``validate_catalogue()``
   compares a whole query set against the contract; ``compare`` inspects a live
   database into a profile and compares that profile against the contract;
   ``validate_catalogue_against_profile()`` checks the query set against both at
   once — so schema evolution never silently desynchronises your queries and your
   database from your declared truth.

Query governance and drift detection are separate concerns: governance keeps
*individual queries* honest against the contract at the moment you register them;
drift detection answers whether *whole sets* — the query catalogue, the live
database — have diverged from the contract over time.


Extensions
----------

The core library (contract definition, data validation, and Cypher query
authoring/validation) depends only on Pydantic, PyYAML, and the ``graphglot``
Cypher parser. Database-specific functionality ships as optional extras:

===============  ====================================================================
Extra            What it adds
===============  ====================================================================
``neo4j``        ``inspect_neo4j`` — inspect a live Neo4j database into a
                 ``GraphProfile`` (APOC / SCHEMA / Cypher strategies,
                 auto-detected).
``memgraph``     ``inspect_memgraph`` — same interface, using Memgraph's schema
                 procedures over the Bolt driver.
``networkx``     ``inspect_networkx`` — in-process inspection of a
                 ``nx.MultiDiGraph``.
``cypher``       Backward-compat alias. ``graphglot`` is now a core dependency, so
                 query authoring and validation are always available; this extra
                 adds no new packages.
``gqlalchemy``   GQLAlchemy OGM integration: codegen of ``Node`` /
                 ``Relationship`` classes and validated fluent queries.
===============  ====================================================================


Installation
------------

Create a dedicated Python environment first (Python 3.11+):

.. code-block:: shell

   python -m venv .venv && source .venv/bin/activate

Install the core library:

.. code-block:: shell

   pip install orthograph

Install with a specific extra:

.. code-block:: shell

   pip install "orthograph[neo4j]"
   pip install "orthograph[memgraph]"
   pip install "orthograph[networkx]"
   pip install "orthograph[gqlalchemy]"

Install everything:

.. code-block:: shell

   pip install "orthograph[all]"

For development (all extras + test/lint/docs tooling):

.. code-block:: shell

   git clone <repo-url>
   cd orthograph
   pip install -e ".[dev]"


Quick start
-----------

Define the contract:

.. code-block:: python

   from typing import Optional

   from orthograph.definition import (
       GraphDefinition,
       NodeModel,
       RelationshipModel,
       validate_data,
   )

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
       __source_label__ = "Person"
       __target_label__ = "Movie"
       role: str

   definition = GraphDefinition(
       name="Filmography",
       node_types=[Person, Movie],
       relationship_types=[ActedIn],
   )

Validate in-memory data against the contract before writing to the database:

.. code-block:: python

   nodes = [
       {"__label__": "Person", "name": "Alice", "born": 1985},
       {"__label__": "Movie", "title": "Inception", "year": 2010},
   ]
   relationships = [
       {"__label__": "ACTED_IN", "__source_uid__": "Alice",
        "__target_uid__": "Inception", "role": "Lead"},
   ]

   result = validate_data(definition, nodes, relationships)
   print(result.is_valid)        # True / False
   for issue in result.issues:
       print(issue.code, issue.message)   # structured, typed error codes

Govern a typed Cypher query — declared parameters, validated against the
contract without executing it:

.. code-block:: python

   from pydantic import BaseModel

   from orthograph.queries import new_catalogue, simple_query, validate_catalogue

   class FindPersonParams(BaseModel):
       name: str

   catalogue = new_catalogue()
   catalogue.register_cypher_query(
       simple_query(
           name="find_person_by_name",
           cypher_template="MATCH (p:Person {name: $name}) RETURN p",
           params=FindPersonParams,
       )
   )

   # Drift detection: is the whole query set still consistent with the contract?
   drift = validate_catalogue(catalogue, definition)
   print(drift.is_valid)

Detect drift against a live database (requires the ``neo4j`` extra):

.. code-block:: python

   from neo4j import GraphDatabase

   from orthograph.compare import profile_to_definition
   from orthograph.profile import inspect_neo4j

   driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
   profile = inspect_neo4j(driver)
   result = profile_to_definition(profile, definition)

   print(result.is_valid)
   for issue in result.issues:
       print(issue.code, issue.message)


Contributing
------------

Setup, the full test matrix (unit, in-process integration, live Neo4j/Memgraph
flags, credential handling, and running the reference notebooks) are documented in
`CONTRIBUTING.md <CONTRIBUTING.md>`_.
