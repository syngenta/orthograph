# Contributing to orthograph

First off, thanks for taking the time to contribute! :tada::+1:

The following is a set of guidelines for contributing to orthograph, which are hosted in the [Syngenta Organization](https://github.com/syngenta) on GitHub.
These are mostly guidelines, not rules. Use your best judgment, and feel free to propose changes to this document in a pull request.

## Code of Conduct

Please note that this project is released with a [Code of Conduct](./CODE_OF_CONDUCT.md). By participating in this project you agree to abide by its terms.

## Contribution Terms and License

The code and documentation of orthograph is contained in this repository. To contribute
to this project or any of the elements of orthograph we recommend you start by reading this
contributing guide.

## Contributing to orthograph codebase

If you would like to contribute to the package, we recommend the following development setup.

1. Create a copy of the [repository](https://github.com/syngenta/orthograph) via the "_Fork_" button.

2. Clone the orthograph repository:

    ```sh
    git clone git@github.com:${GH_ACCOUNT_OR_ORG}/orthograph.git
    ```

3. Add remote orthograph repo as an "upstream" in your local repo, so you can check/update remote changes.

   ```sh
   git remote add upstream git@github.com:syngenta/orthograph.git
   ```

4. Create a dedicated branch:

    ```sh
    cd orthograph
    git checkout -b a-super-nice-feature-we-all-need
    ```

5. Create and activate a dedicated Python environment (any virtual environment tool works):

    ```sh
    python -m venv .venv
    # Linux / macOS
    source .venv/bin/activate
    # Windows
    .venv\Scripts\activate
    ```

6. Install orthograph in editable mode:

    ```sh
    pip install -e .[dev]
    ```

7. Set up and run pre-commit hooks:

    ```sh
    pre-commit install
    pre-commit run --all-files
    ```

8. Implement your changes and once you are ready run the tests:

    ```sh
    # Run all tests (this can take quite long)
    python -m pytest tests/

    # Or run specific tests
    python -m pytest tests/test_specific_module.py
    ```

9. Once the tests and checks pass, but most importantly you are happy with the implemented feature, commit your changes.

     ```sh
     # add the changes
     git add .
     # commit them
     git commit -s -m "feat: implementing super nice feature" -m "A feature we all need."
     # check upstream changes
     git fetch upstream
     git rebase upstream/main
     # push changes to your fork
     git push -u origin a-super-nice-feature-we-all-need
     ```

10. From your fork, open a pull request via the "_Contribute_" button, the maintainers will be happy to review it.

## Project Structure

Understanding the project layout will help you navigate the codebase:

- **src/orthograph/** - Main package source code
- **tests/** - Test suite (run with `pytest`)
- **docs/** - Documentation (Sphinx or similar)
- **notebooks/** - Jupyter notebooks for examples and experimentation
- **pyproject.toml** - Project metadata and dependencies
- **.pre-commit-config.yaml** - Pre-commit hooks configuration

## Development Guidelines

### Code Quality

The project uses:
- **ruff** - Fast Python linter (configured via pre-commit hooks)
- **mypy** - Static type checking (see mypy.ini)
- **pytest** - Testing framework

All of these checks run automatically via pre-commit hooks when you commit. Make sure they pass before pushing.

### Testing

- Write tests for any new functionality in the `tests/` directory
- Follow the existing test structure and naming conventions
- Run `python -m pytest` to execute the full test suite
- Use `python -m pytest -v` for verbose output

### Documentation

- Update relevant documentation in the `docs/` directory if your changes affect API or behavior
- Include docstrings in your code following the project's existing conventions
- Consider adding examples in notebooks if you add significant new functionality

---

## Running the tests

### Test categories

| Category | What runs | When |
|---|---|---|
| Unit | Pure Python, no external process | Always (default CI) |
| In-process integration | NetworkX backend, YAML round-trips | Always (no flag needed) |
| Live Neo4j | Tests marked `@pytest.mark.neo4j` + Neo4j notebooks | `--neo4j` flag |
| Live Memgraph | Tests marked `@pytest.mark.memgraph` + Memgraph notebooks | `--memgraph` flag |

### Basic usage

```sh
# Unit + in-process integration only (CI default)
pytest

# With verbose output
pytest -v
```

### Live-database flags

Passing credentials via the CLI is intentional — there are no `.env` file defaults for tests, ensuring explicit credential handling in CI/CD.

```sh
# Run with live Neo4j
pytest --neo4j --neo4j-password <password>

# Run with live Memgraph
pytest --memgraph --memgraph-password <password>

# Run with both
pytest --neo4j --neo4j-password <pw> --memgraph --memgraph-password <pw>
```

### Credential options

All connection details are passed via CLI. Defaults listed below; only passwords have no default.

| Option | Default | Notes |
|---|---|---|
| `--neo4j-uri` | `bolt://localhost:7687` | |
| `--neo4j-user` | `neo4j` | |
| `--neo4j-password` | *(required for `--neo4j`)* | No default — must be passed explicitly |
| `--memgraph-uri` | `bolt://localhost:7688` | |
| `--memgraph-user` | *(empty)* | |
| `--memgraph-password` | *(empty)* | |

### Full test matrix

```sh
# Unit tests only
pytest

# Unit + live Neo4j
pytest --neo4j --neo4j-password <pw>

# Unit + live Memgraph
pytest --memgraph --memgraph-password <pw>

# Unit + live Neo4j + live Memgraph
pytest --neo4j --neo4j-password <pw> --memgraph --memgraph-password <pw>
```

### Running notebooks

Notebooks are validated via [nbval](https://nbval.readthedocs.io/). They are split into three groups:

**CI-safe notebooks** — execute at build time, no external DB required:

```sh
pytest notebooks/ --nbval-lax
```

**Live-DB notebooks** — require the corresponding flag and a running database:

```sh
pytest notebooks/ --nbval-lax --neo4j --neo4j-password <pw>
pytest notebooks/ --nbval-lax --memgraph --memgraph-password <pw>
```

The following notebooks require a live database (source of truth: `notebooks/conftest.py`):

| Notebook | Requires flag |
|---|---|
| `03.03_cypher_query_usage.ipynb` | `--neo4j` |
| `04.02_neo4j_backend.ipynb` | `--neo4j` |
| `04.03_gqlalchemy_backend.ipynb` | `--memgraph` |
| `04.04_multi_shape_relationships.ipynb` | `--neo4j` |
| `04.06_cypher_query_definitions.ipynb` | `--neo4j` |

**UI notebooks** — require optional UI dependencies (`dash`, `fastapi`, `plotly`). Excluded from collection unless the `NOTEBOOKS_UI` environment variable is set:

```sh
NOTEBOOKS_UI=1 pytest notebooks/ --nbval-lax
```

UI notebooks: `06.01_fastapi_integration.ipynb`, `06.02_dash_profile_explorer.ipynb`, `06.03_async_query_runner.ipynb`.

### Adding live-DB tests

1. Mark the test with `@pytest.mark.neo4j` or `@pytest.mark.memgraph`.
2. Use the session-scoped fixture `neo4j_driver` or `memgraph_driver` (defined in the root `conftest.py`) to get a driver.
3. Use `neo4j_clean` / `memgraph_clean` if your test needs a blank database — these fixtures wipe all nodes and relationships before and after each test.

```python
import pytest

@pytest.mark.neo4j
def test_something_against_neo4j(neo4j_clean, neo4j_driver):
    neo4j_driver.execute_query("CREATE (n:Person {name: 'Alice'})")
    # ... assertions ...
```

The test is automatically skipped when `--neo4j` is not passed.
