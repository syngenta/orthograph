Orthograph
=======================================



Installation
------------

Create a dedicated python environment for this package with your favorite environment manager.

.. code-block:: shell

   conda create -n orthograph python=3.9
   conda activate orthograph


* Option 1: Install the package from the git repository:

.. code-block:: shell

   pip install git+ssh://git@gitlab.com/syngentagroup/cas/prod/orthograph.git

* Option 2: Install the package from the python package repository if its url is configured in the pip configuration file:

.. code-block:: shell

   pip install orthograph

* Option 3: Install the package from the python package repository if its url is not configured in the pip configuration file:

.. code-block:: shell

    pip install orthograph --extra-index-url=https://deawilldtd002.cloud.syngenta.org/nexus/repository/pypi-group/simple/

An incomplete setup of certificated might result in a failure to install the packages.
To fix this, you need to install the certificate (ex in C:\certificates\ca-certificates.crt) and point the environment variable REQUESTS_CA_BUNDLE to the certificate file.
Alternatively you can use the --cert option in the pip install command. (--cert C:\certificates\ca-certificates.crt).


For Development
---------------

When working on the development of this package, the developer wants to work
directly on the source code while still using the packaged installation. For
that, run:

.. code-block:: shell

   git clone git@gitlab.com:syngentagroup/cas/prod/orthograph.git
   pip install -e orthograph/[dev]


Running Tests
~~~~~~~~~~~~~

Unit tests run by default without any external services:

.. code-block:: shell

   pytest

Notebooks are tested separately via nbval (CI-safe notebooks only):

.. code-block:: shell

   pytest notebooks/ --nbval-lax

Tests and notebooks that require a live database are gated behind CLI flags
and skipped by default. Use ``--neo4j`` or ``--memgraph`` to include them:

.. code-block:: shell

   pytest --neo4j                            # include @pytest.mark.neo4j unit tests
   pytest notebooks/ --nbval-lax --neo4j     # include Neo4j-requiring notebooks
   pytest notebooks/ --nbval-lax --memgraph  # include Memgraph-requiring notebooks

To mark a new test as DB-dependent, decorate it with ``@pytest.mark.neo4j`` or
``@pytest.mark.memgraph``. For notebooks, add an entry to the ``_DB_NOTEBOOKS``
dict in ``notebooks/conftest.py``.

See ``conftest.py`` (project root) for the flag registration and auto-skip logic.
