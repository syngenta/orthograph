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

5. Create and activate a dedicated conda environment (any other virtual environment management would work):

    ```sh
    conda env create -n orthograph
    conda activate orthograph
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
