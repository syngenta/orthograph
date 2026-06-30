# Configuration file for the Sphinx documentation builder.
#
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------

from pathlib import Path

import orthograph


project = "orthograph"
copyright = "2026 Syngenta Group Co. Ltd."
author = "Orthograph contributors"

version = orthograph.__version__
release = version

# -- Notebook wiring ----------
# myst-nb only compiles notebooks under srcdir (docs/source/), but the
# canonical source is notebooks/ at repo root.  We expose the whole directory
# at docs/source/notebooks via a link so there are zero copies and the
# notebooks execute with their sibling `shared/` package and `data/` fixtures
# resolvable (they `from shared.filmography import ...` and read `data/*.json`).
#
# Link strategy, in order of preference:
#   1. POSIX / RTD: a directory symlink.
#   2. Windows: a directory junction (works without Developer Mode, and — unlike
#      a copy — keeps the sibling shared/ and data/ reachable at build time).
#   3. Last resort (no link possible): copy the wired notebooks AND their
#      support dirs so relative imports/reads still work.

_HERE = Path(__file__).parent  # docs/source/
_REPO_ROOT = _HERE.parent.parent  # repo root
_LINK = _HERE / "notebooks"
_NB_SOURCE = _REPO_ROOT / "notebooks"

# Wired into toctrees: pillars 01-05 (Tutorials, E61.2.2) + the 06.x
# integration notebooks (How-to, E61.3.2).  Only consulted by the copy
# fallback; the link paths expose every notebook automatically.
_WIRED = [
    "01.01_create_a_graph_definition.ipynb",
    "01.02_validating_graph_data.ipynb",
    "01.03_what_is_cardinality.ipynb",
    "01.04_optionality_and_cardinality.ipynb",
    "01.05_conditional_cardinality.ipynb",
    "02.01_yaml_configuration.ipynb",
    "02.02_visualization.ipynb",
    "03.01_cypher_generation.ipynb",
    "03.02_cypher_query_definitions.ipynb",
    "03.03_cypher_query_usage.ipynb",
    "03.04_typed_query_contracts.ipynb",
    "03.05_typed_query_result_shapes_and_materialization.ipynb",
    "04.01_networkx_backend.ipynb",
    "04.02_neo4j_backend.ipynb",
    "04.03_gqlalchemy_backend.ipynb",
    "04.04_multi_shape_relationships.ipynb",
    "05.01_introducing_the_graph_profile.ipynb",
    "05.02_profile_vs_definition.ipynb",
    "05.03_profile_vs_profile.ipynb",
    "05.04_definition_vs_definition.ipynb",
    "05.05_conditional_cardinality_profiling.ipynb",
    "05.06_enum_properties.ipynb",
    "06.01_fastapi_integration.ipynb",
    "06.02_dash_profile_explorer.ipynb",
    "06.03_async_query_runner.ipynb",
]

# Support dirs a notebook needs at execution time (relative to notebooks/).
_NB_SUPPORT = ["shared", "data"]


def _is_link(path: Path) -> bool:
    """True if path is a symlink or a Windows directory junction/reparse point."""
    if path.is_symlink():
        return True
    # Windows junctions: detect via lstat attributes (ReparsePoint flag = 0x400)
    try:
        lstat = path.lstat()
        # FILE_ATTRIBUTE_REPARSE_POINT = 0x400
        if getattr(lstat, "st_file_attributes", 0) & 0x400:
            return True
    except (AttributeError, OSError):
        pass
    try:
        # py3.12+ may expose st_reparse_point on some builds
        return bool(getattr(path.stat(), "st_reparse_point", None))
    except (AttributeError, OSError):
        pass
    return False


def _wire_notebooks() -> None:
    if _LINK.exists() or _LINK.is_symlink():
        if _is_link(_LINK):
            return  # link already in place — single source, nothing to do
        # A stale plain-directory copy from an earlier build: replace it.
        import shutil

        shutil.rmtree(_LINK)

    # 1. symlink (POSIX / RTD)
    try:
        _LINK.symlink_to(_NB_SOURCE, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass

    # 2. Windows directory junction (no Developer Mode required)
    import subprocess

    try:
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(_LINK), str(_NB_SOURCE)],
            check=True,
            capture_output=True,
        )
        return
    except (OSError, subprocess.CalledProcessError):
        pass

    # 3. copy fallback: notebooks + support dirs so relative paths resolve
    import shutil

    _LINK.mkdir()
    for _nb in _WIRED:
        shutil.copy2(_NB_SOURCE / _nb, _LINK / _nb)
    for _dir in _NB_SUPPORT:
        _src_dir = _NB_SOURCE / _dir
        if _src_dir.is_dir():
            shutil.copytree(_src_dir, _LINK / _dir, dirs_exist_ok=True)


_wire_notebooks()

# -- General configuration ---------------------------------------------------

extensions = [
    "myst_nb",
    "sphinx_design",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.viewcode",
    "sphinx.ext.doctest",
    "sphinxcontrib.mermaid",
    # intersphinx re-enable when prose pages reference Python stdlib types
    # (currently blocked by corporate proxy intercepting objects.inv fetch)
    # "sphinx.ext.intersphinx",
]

templates_path = ["_templates"]
exclude_patterns = [
    "_build",
    "build",
    "Thumbs.db",
    ".DS_Store",
    "**/.ipynb_checkpoints",
]

# Notebooks not yet wired into a toctree will be added in E61.P2.
# Suppress the orphan warning until then.
suppress_warnings = ["toc.not_included"]

# MyST extensions needed for sphinx-design grid/card directives.
myst_enable_extensions = ["colon_fence"]

modindex_common_prefix = ["orthograph."]
autosummary_generate = True
autosummary_generate_overwrite = False

# autosummary writes .rst stub files; it needs .rst in source_suffix to do so.
# myst-nb only registers .md/.ipynb — adding .rst here lets autosummary
# generate stubs while all authored pages remain MyST Markdown.
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "myst-nb",
    ".ipynb": "myst-nb",
}

# -- MyST / myst-nb ----------------------------------------------------------

# Notebooks that require a live DB or optional UI deps — render from saved
# outputs rather than re-executing at build time.
# Source of truth: notebooks/conftest.py (_DB_NOTEBOOKS + _UI_NOTEBOOKS).
nb_execution_mode = "auto"
nb_execution_excludepatterns = [
    # Live-DB notebooks
    "03.03_cypher_query_usage.ipynb",
    "04.02_neo4j_backend.ipynb",
    "04.03_gqlalchemy_backend.ipynb",
    "04.04_multi_shape_relationships.ipynb",
    "04.06_cypher_query_definitions.ipynb",
    # UI-dependency notebooks
    "06.01_fastapi_integration.ipynb",
    "06.02_dash_profile_explorer.ipynb",
    "06.03_async_query_runner.ipynb",
]

# -- Intersphinx -------------------------------------------------------------
# Disabled: corporate proxy intercepts objects.inv fetch and triggers a
# format-string crash in sphinx.ext.intersphinx._load (Sphinx 8.x).
# Re-enable once an offline inventory cache is in place or the proxy is
# bypassed.
#
# intersphinx_mapping = {
#     "python": ("https://docs.python.org/3", None),
# }

# -- HTML output -------------------------------------------------------------

html_theme = "furo"
html_static_path = ["_static"]
html_css_files = ["default.css"]
html_js_files = ["custom.js"]

html_logo = "_static/banner.png"
html_favicon = "_static/favicon.png"

html_theme_options = {
    # banner.png is the sidebar logo (wide, replaces html_logo in sidebar top)
    # logo.png is the square mark used elsewhere if needed
    "light_css_variables": {
        "color-brand-primary": "#78ac1b",
        "color-brand-content": "#78ac1b",
        "color-api-highlight-on-target": "#e5fff5",
    },
    "dark_css_variables": {
        "color-brand-primary": "#78ac1b",
        "color-brand-content": "#78ac1b",
        "color-api-highlight-on-target": "#e5fff5",
    },
}
