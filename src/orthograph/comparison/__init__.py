"""Cross-layer comparison package (vendor-free).

Three comparison functions live in :mod:`orthograph.comparison.engine`:

- :func:`~orthograph.comparison.engine.compare_profile_to_definition` —
  checks whether a :class:`~orthograph.graph_profile.models.GraphProfile`
  satisfies a :class:`~orthograph.graph_definition.graph_definition.GraphDefinition`.
- :func:`~orthograph.comparison.engine.compare_profiles` — symmetric diff
  between two profiles.
- :func:`~orthograph.comparison.engine.compare_definitions` — symmetric diff
  between two definitions.

The :class:`~orthograph.comparison.views.GraphView` adapters
(:mod:`orthograph.comparison.views`) project each operand onto the shared
address space.  The Rule abstraction and standard satisfaction rules live in
:mod:`orthograph.comparison.rules`; symmetric diff rules live in
:mod:`orthograph.comparison.diff_rules`.
No backend is imported here.
"""
