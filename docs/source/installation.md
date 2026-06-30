# Installation

## Requirements

- Python **3.11 or later**
- pip (comes with Python)

---

## Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
.venv\Scripts\activate           # Windows
```

---

## Install Orthograph

**Core only** (model definition, in-memory validation, Cypher query authoring):

```bash
pip install orthograph
```

**With a backend extension:**

```bash
pip install "orthograph[neo4j]"       # Neo4j database inspection
pip install "orthograph[memgraph]"    # Memgraph database inspection
pip install "orthograph[networkx]"    # NetworkX in-memory graph inspection
pip install "orthograph[gqlalchemy]"  # GQLAlchemy OGM integration
```

**All extensions:**

```bash
pip install "orthograph[all]"
```

---

## Optional extras

| Extra | What it adds |
|-------|-------------|
| `neo4j` | `Neo4jInspector`, `validate_database()` for Neo4j |
| `memgraph` | `MemgraphInspector` for Memgraph (shares the Neo4j Bolt driver) |
| `networkx` | `NetworkxInspector`, `schema_to_networkx()` |
| `cypher` | Backward-compatibility alias — `graphglot` is a core dependency; no new packages added |
| `gqlalchemy` | `GqlAlchemyClient`, `ValidatedQueryBuilder`, auto-generated OGM classes |
| `all` | All of the above |
| `docs` | Sphinx + MyST-NB toolchain for building this documentation |
| `dev` | Everything above plus pytest, ruff, mypy, pre-commit, and type stubs |

---

## Development install

```bash
git clone <repo-url>
cd orthograph
pip install -e ".[dev]"
```

This installs all extensions, the docs toolchain, and the full test and lint stack in
editable mode. See [CONTRIBUTING](https://github.com/orthograph/orthograph/blob/main/CONTRIBUTING.md)
for how to run the test suite.
