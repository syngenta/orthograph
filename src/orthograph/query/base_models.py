"""Typed query base models and Executor seam.

Defines the pure build/materialise contract (ReadQueryModel, WriteQueryModel) and the
single I/O seam (Executor) that separates construction from execution.

Orthograph never owns a connection. Executor implementations receive a factory
callable, not a live session.

No database-specific imports here.
"""

import inspect
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar, Generic, TypeVar, get_args

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


def _check_query_id_attr(cls: type, problems: list[str]) -> None:
    """Append a problem if ``query_id`` is present but not a str."""
    query_id = getattr(cls, "query_id", None)
    if query_id is not None and not isinstance(query_id, str):
        problems.append(f"query_id must be a str, got {query_id!r}")


def _extract_generic_args(cls: type, base_cls: type) -> tuple[Any, ...] | None:
    """Extract concrete type arguments from *cls*'s own direct parameterised base.

    Only inspects ``__orig_bases__`` stored **directly on** *cls* (never
    inherited), so subclasses-of-subclasses do not pick up their parent's
    unbound TypeVars.  Any arg that is still a ``TypeVar`` causes the whole
    result to be discarded — callers only receive fully-bound concrete types.
    """
    for base in cls.__dict__.get("__orig_bases__", ()):
        origin = getattr(base, "__origin__", None)
        if origin is not None and issubclass(origin, base_cls):
            args = get_args(base)
            if args and not any(isinstance(a, TypeVar) for a in args):
                return args
    return None


def _auto_populate_classvar(cls: type, attr_name: str, value: Any) -> None:
    """Set *attr_name* on *cls* from a generic arg if not explicitly declared.

    If the attribute **is** already in ``cls.__dict__`` and its value differs
    from *value*, raise ``TypeError`` at class-definition time (conflicting
    explicit assignment).  If it matches, accept silently.
    """
    if attr_name in cls.__dict__:
        declared = cls.__dict__[attr_name]
        if declared != value:
            raise TypeError(
                f"{cls.__name__}: {attr_name} is declared as {declared!r} "
                f"but the generic argument is {value!r}; "
                f"remove the explicit {attr_name} = ... assignment or make it match"
            )
    else:
        setattr(cls, attr_name, value)


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
    if "query_id" in other_attrs:
        _check_query_id_attr(cls, problems)
    if problems:
        raise TypeError(f"{cls.__name__}: " + "; ".join(problems))


class ReadQueryModel(ABC, Generic[P, D]):
    """Abstract generic base for typed read queries.

    Subclasses MUST define:
      - ``params_schema``  — the Pydantic model class that declares accepted parameters
      - ``Output``  — the Pydantic model class that declares the returned record shape
      - ``query_id``    — unique string identifier within a catalogue
      - ``backend`` — ``Backend`` enum value

    The two abstract methods keep construction and execution strictly separated:
      - ``build()``       — pure, I/O-free; constructs the backend query object
      - ``materialize()`` — pure, per-record; maps a raw storage record to ``Output``
    """

    params_schema: ClassVar[type[BaseModel]]
    Output: ClassVar[type[BaseModel]]
    query_id: ClassVar[str]
    backend: ClassVar[Backend]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Skip enforcement for intermediate abstract classes (those that still
        # leave at least one abstractmethod unimplemented).
        if inspect.isabstract(cls):
            return
        # T6: auto-populate params_schema and Output from generic args when the
        # class directly parameterises ReadQueryModel[P, D] with concrete types.
        args = _extract_generic_args(cls, ReadQueryModel)
        if args and len(args) >= 2:
            _auto_populate_classvar(cls, "params_schema", args[0])
            _auto_populate_classvar(cls, "Output", args[1])
        _enforce_query_contract(
            cls,
            model_attrs=("params_schema", "Output"),
            other_attrs=("query_id", "backend"),
        )

    @abstractmethod
    def build(self, params: P) -> Any:
        """Pure construction of the backend query object (no I/O or side effects)."""

    @abstractmethod
    def materialize(self, raw: Any) -> D:
        """Pure per-record mapping from a raw storage record to the Output type."""


class WriteQueryModel(ABC, Generic[P, R]):
    """Abstract generic base for typed write queries.

    Subclasses MUST define:
      - ``params_schema``  — the Pydantic model class that declares accepted parameters
      - ``query_id``    — unique string identifier within a catalogue
      - ``backend`` — ``Backend`` enum value

    Subclasses MAY define:
      - ``Output``  — a Pydantic model class that describes the write result structure
                      (defaults to ``None``)

    Write results (rowcounts, ids) are expressed via the ``R`` TypeVar and
    ``interpret_result()``.
    """

    params_schema: ClassVar[type[BaseModel]]
    Output: ClassVar[type[BaseModel] | None] = None
    query_id: ClassVar[str]
    backend: ClassVar[Backend]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls):
            return
        # T6: auto-populate params_schema from the first generic arg.
        args = _extract_generic_args(cls, WriteQueryModel)
        if args and len(args) >= 1:
            _auto_populate_classvar(cls, "params_schema", args[0])
        _enforce_query_contract(
            cls, model_attrs=("params_schema",), other_attrs=("query_id", "backend")
        )

    @abstractmethod
    def build(self, params: P) -> Any:
        """Pure, I/O-free construction of the write query object."""

    @abstractmethod
    def interpret_result(self, raw: Any) -> R:
        """Pure mapping of a mutation summary into the declared result type.

        ``raw`` is expected to satisfy the
        :class:`~orthograph.query.write_result.WriteResultSummary` protocol
        when invoked through :class:`~orthograph.cypher.query_execution.CypherExecutor`
        (which passes a ``CypherWriteResultSummary`` wrapping the driver's
        ``SummaryCounters``).  The signature accepts ``Any`` so that the abstract
        layer stays vendor-free and test doubles may pass plain dataclasses or
        dicts during unit testing.
        """


class Executor(ABC):
    """The only place a connection or session is touched.

    ``read()`` and ``write()`` carry different transactional intent and must
    not be unified behind a flag.  Implementations receive a factory callable,
    not a live connection, and open/close sessions per call.
    """

    @abstractmethod
    def read(self, query: ReadQueryModel[P, D], raw_params: Any) -> list[D]:
        """Validate params → build() (pure) → execute → materialize. No commit."""

    @abstractmethod
    def write(self, query: WriteQueryModel[P, R], raw_params: Any) -> R:
        """Validate params → build() (pure) → execute → interpret_result. No commit."""


class ReadPort(ABC, Generic[P, D]):
    """A named read capability with a store-neutral signature.

    Consuming code depends on a ``ReadPort`` subclass, never on a specific
    ``ReadQueryModel`` or ``Executor``. The composition root binds the port to a
    concrete query + executor, making the read store swappable at one point
    without touching callers.
    """

    @abstractmethod
    def fetch(self, params: P) -> list[D]: ...


class QueryBackedReadPort(ReadPort[P, D]):
    """A ``ReadPort`` backed by a ``ReadQueryModel`` + ``Executor`` pair.

    Constructed at the composition root and injected into callers as a
    ``ReadPort``. Swap the query or executor without changing any caller.
    """

    def __init__(self, query: ReadQueryModel[P, D], executor: Executor) -> None:
        self._query = query
        self._executor = executor

    def fetch(self, params: P) -> list[D]:
        return self._executor.read(self._query, params)


class AsyncExecutor(ABC):
    """Async counterpart of Executor. Same contract, awaited.

    Like Executor, it NEVER commits or rolls back — the caller owns the transaction
    boundary (ADR-028). Implementations receive an async factory and open/close the
    async session (or accept a caller-supplied live async transaction) per call.
    """

    @abstractmethod
    async def read(self, query: ReadQueryModel[P, D], raw_params: Any) -> list[D]:
        """Validate params → build() (pure) → execute → materialize. No commit."""

    @abstractmethod
    async def write(self, query: WriteQueryModel[P, R], raw_params: Any) -> R:
        """Validate params → build() (pure) → execute → interpret_result. No commit."""


class AsyncReadPort(ABC, Generic[P, D]):
    """Async named read capability. Async counterpart of ReadPort."""

    @abstractmethod
    async def fetch(self, params: P) -> list[D]: ...


class AsyncQueryBackedReadPort(AsyncReadPort[P, D]):
    """An AsyncReadPort backed by a ReadQueryModel + AsyncExecutor pair."""

    def __init__(self, query: ReadQueryModel[P, D], executor: AsyncExecutor) -> None:
        self._query = query
        self._executor = executor

    async def fetch(self, params: P) -> list[D]:
        return await self._executor.read(self._query, params)
