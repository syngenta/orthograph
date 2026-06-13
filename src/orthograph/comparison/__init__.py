"""Cross-layer comparison package (vendor-free).

Reconciles a :class:`~orthograph.graph_definition.graph_definition.GraphDefinition`
(the declared side) against a
:class:`~orthograph.graph_profile.models.GraphProfile` (the observed side).

Holds the injection-based comparison engine
(:func:`~orthograph.comparison.engine.compare`) and the Rule abstraction +
standard rule set (:mod:`orthograph.comparison.rules`).
No backend is imported here.
"""
