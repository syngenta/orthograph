"""Abstract base class for graph inspectors."""

from abc import ABC, abstractmethod

from orthograph.extensions.models import GraphProfile


class GraphInspector(ABC):
    """Inspects a graph source and produces a structural profile."""

    @abstractmethod
    def inspect(self) -> GraphProfile: ...
