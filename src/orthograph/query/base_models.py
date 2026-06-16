"""Typed query base models and Executor seam.

Defines the pure build/materialise contract (ReadQuery, WriteQuery) and the
single I/O seam (Executor) that separates construction from execution.

Orthograph never owns a connection. Executor implementations receive a factory
callable, not a live session.

No database-specific imports here.
"""

import inspect
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel


P = TypeVar("P", bound=BaseModel)  # Params — a validated Pydantic model
D = TypeVar("D", bound=BaseModel)  # Output — a NodeModel or projection BaseModel
R = TypeVar("R")  # Write result — rowcount, id, etc.


class Backend(str, Enum):
    """Descriptive tag identifying which backend a query targets.

    This is metadata only — NOT a dispatch switch. The catalogue and executor
    use it for introspection and documentation, not for routing.
    """

    CYPHER = "cypher"
    SQLALCHEMY = "sqlalchemy"
    GQLALCHEMY = "gqlalchemy"


def _check_attr_presence(
    cls: type, attrs: tuple[str, ...], problems: list[str]
) -> None:
    """Append a problem for each attr missing from *cls* or its MRO."""
    for attr in attrs:
        if not any(attr in base.__dict__ for base in cls.__mro__):
            problems.append(f"missing class variable: {attr}")


def _check_model_attrs(
    cls: type, model_attrs: tuple[str, ...], problems: list[str]
) -> None:
    """Append a problem for each model_attr that is
    present but not a BaseModel subclass."""
    for attr in model_attrs:
        value = getattr(cls, attr, None)
        if value is not None and not (
            isinstance(value, type) and issubclass(value, BaseModel)
        ):
            problems.append(f"{attr} must be a BaseModel subclass, got {value!r}")


def _check_backend_attr(cls: type, problems: list[str]) -> None:
    """Append a problem if ``backend`` is present but not a Backend value."""
    backend = getattr(cls, "backend", None)
    if backend is not None and not isinstance(backend, Backend):
        problems.append(f"backend must be a Backend value, got {backend!r}")


def _check_name_attr(cls: type, problems: list[str]) -> None:
    """Append a problem if ``name`` is present but not a str."""
    name = getattr(cls, "name", None)
    if name is not None and not isinstance(name, str):
        problems.append(f"name must be a str, got {name!r}")


def _enforce_query_contract(
    cls: type, *, model_attrs: tuple[str, ...], other_attrs: tuple[str, ...]
) -> None:
    """Validate that a query subclass declares its required class vars.

    Checks: presence and type (``model_attrs`` must be ``BaseModel`` subclasses).
    Raises ``TypeError`` listing all problems.
    """
    problems: list[str] = []
    _check_attr_presence(cls, (*model_attrs, *other_attrs), problems)
    _check_model_attrs(cls, model_attrs, problems)
    if "backend" in other_attrs:
        _check_backend_attr(cls, problems)
    if "name" in other_attrs:
        _check_name_attr(cls, problems)
    if problems:
        raise TypeError(f"{cls.__name__}: " + "; ".join(problems))


class ReadQuery(ABC, Generic[P, D]):
    """Abstract generic base for typed read queries.

    Subclasses MUST define:
      - ``Params``  — the Pydantic model class that declares accepted parameters
      - ``Output``  — the Pydantic model class that declares the returned record shape
      - ``name``    — unique string identifier within a catalogue
      - ``backend`` — ``Backend`` enum value

    The two abstract methods keep construction and execution strictly separated:
      - ``build()``       — pure, I/O-free; constructs the backend query object
      - ``materialize()`` — pure, per-record; maps a raw storage record to ``Output``
    """

    Params: ClassVar[type[BaseModel]]
    Output: ClassVar[type[BaseModel]]
    name: ClassVar[str]
    backend: ClassVar[Backend]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Skip enforcement for intermediate abstract classes (those that still
        # leave at least one abstractmethod unimplemented).
        if inspect.isabstract(cls):
            return
        _enforce_query_contract(
            cls, model_attrs=("Params", "Output"), other_attrs=("name", "backend")
        )

    @abstractmethod
    def build(self, params: P) -> Any:
        """Pure construction of the backend query object (no I/O or side effects)."""

    @abstractmethod
    def materialize(self, raw: Any) -> D:
        """Pure per-record mapping from a raw storage record to the Output type."""


class WriteQuery(ABC, Generic[P, R]):
    """Abstract generic base for typed write queries.

    Subclasses MUST define:
      - ``Params``  — the Pydantic model class that declares accepted parameters
      - ``name``    — unique string identifier within a catalogue
      - ``backend`` — ``Backend`` enum value

    WriteQuery has NO ``Output`` class variable — write results (rowcounts, ids)
    are expressed via the ``R`` TypeVar and ``materialize()``.
    """

    Params: ClassVar[type[BaseModel]]
    name: ClassVar[str]
    backend: ClassVar[Backend]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls):
            return
        _enforce_query_contract(
            cls, model_attrs=("Params",), other_attrs=("name", "backend")
        )

    @abstractmethod
    def build(self, params: P) -> Any:
        """Pure, I/O-free construction of the write query object."""

    @abstractmethod
    def materialize(self, raw: Any) -> R:
        """Pure mapping of the driver's write result into the declared result type."""


class Executor(ABC):
    """The only place a connection or session is touched.

    ``read()`` and ``write()`` carry different transactional intent and must
    not be unified behind a flag.  Implementations receive a factory callable,
    not a live connection, and open/close sessions per call.
    """

    @abstractmethod
    def read(self, query: ReadQuery[P, D], raw_params: Any) -> list[D]:
        """Validate params → build() (pure) → execute → materialize. No commit."""

    @abstractmethod
    def write(self, query: WriteQuery[P, R], raw_params: Any) -> R:
        """Validate params → build() (pure) → execute → commit → materialize."""


class ReadPort(ABC, Generic[P, D]):
    """A named read capability with a store-neutral signature.

    Consuming code depends on a ``ReadPort`` subclass, never on a specific
    ``ReadQuery`` or ``Executor``. The composition root binds the port to a
    concrete query + executor, making the read store swappable at one point
    without touching callers.
    """

    @abstractmethod
    def fetch(self, params: P) -> list[D]: ...


class QueryBackedReadPort(ReadPort[P, D]):
    """A ``ReadPort`` backed by a ``ReadQuery`` + ``Executor`` pair.

    Constructed at the composition root and injected into callers as a
    ``ReadPort``. Swap the query or executor without changing any caller.
    """

    def __init__(self, query: ReadQuery[P, D], executor: Executor) -> None:
        self._query = query
        self._executor = executor

    def fetch(self, params: P) -> list[D]:
        return self._executor.read(self._query, params)
