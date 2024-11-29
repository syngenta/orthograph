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
