"""CypherQuerySpec — a concrete, YAML-serialisable Cypher query definition.

This is a companion to :class:`~orthograph.cypher.base_models.CypherReadQuery`
and :class:`~orthograph.cypher.base_models.CypherWriteQuery`.  It trades the
full typed contract (``Params`` model required, ``Output`` model required,
``materialize()`` implementation required) for lower ceremony and YAML
round-trip compatibility.

Contrast with the typed bases:

* :class:`~orthograph.cypher.base_models.CypherReadQuery` and
  :class:`~orthograph.cypher.base_models.CypherWriteQuery` are **abstract bases
  you subclass** — they enforce a full typed contract at class-definition time.
* :class:`CypherQuerySpec` is a **concrete data class you instantiate directly**
  — no subclassing required or intended.

Design goals
------------
* **YAML-serialisable.** Pydantic ``model_dump()`` returns fields with both
  standard names (``name``, ``cypher``) and legacy names (``query_name``,
  ``query``) for backward compatibility via field aliases.
* **Optionally typed.** A ``Params`` Pydantic model may be declared. When
  present, :meth:`build` validates and coerces argument values through it.
  When absent, arguments are passed through as-is after name validation.
* **Schema-validatable.** :meth:`validate_query` accepts a
  :class:`~orthograph.graph_definition.graph_definition.GraphDefinition` and
  runs the same static domain checks as
  :func:`~orthograph.cypher.parser.validate_cypher` — labels, relationship
  types, property accesses, and endpoints. Passing ``None`` skips domain
  validation and returns an empty :class:`ValidationResult` (useful for
  syntax-only checks before a schema is available).
* **No output model.** Returns a raw ``(cypher, params)`` tuple from
  :meth:`build`.  Callers pass that directly to their own driver session.
  This keeps the class useful as a validation-only on-ramp before a
  consuming project is ready to declare typed ``Output`` models.

Usage — name-list style::

    query = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
        query_args_required=["movie_id"],
    )
    result = query.validate_query(my_graph_definition)   # static, no DB
    cypher, params = query.build(movie_id="M-001")
    await session.run(cypher, params)

Usage — with optional Params model (adds type validation)::

    class MovieParams(BaseModel):
        movie_id: str
        limit: int = 10

    query = CypherQuerySpec(
        name="find_movie",
        cypher="MATCH (m:Movie {movie_id: $movie_id}) RETURN m LIMIT $limit",
        query_args_required=["movie_id"],
        query_args_optional=["limit"],
        Params=MovieParams,
    )
    cypher, params = query.build(movie_id="M-001", limit=5)

YAML serialization using model_dump::

    query.model_dump(
        exclude_none=True,
        by_alias=True,  # returns query_name / query for YAML compatibility
    )
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orthograph.cypher.exceptions import CypherQuerySpecError
from orthograph.diagnostics.result import ValidationResult


class CypherQuerySpec(BaseModel):
    """A concrete, YAML-serialisable Cypher query definition.

    Instantiate directly — do not subclass.  For typed queries with full
    ``Params`` / ``Output`` / ``materialize()`` contracts, use
    :class:`~orthograph.cypher.base_models.CypherReadQuery` or
    :class:`~orthograph.cypher.base_models.CypherWriteQuery` instead.

    Parameters
    ----------
    name:
        Unique identifier for this query within a catalogue or YAML file.
        Serialized as ``query_name`` for YAML compatibility.
    cypher:
        The raw Cypher string. ``$name`` placeholders are driver-bound
        parameters; they must correspond to entries in ``query_args_required``
        or ``query_args_optional``.
        Serialized as ``query`` for YAML compatibility.
    query_args_required:
        Names of parameters that must be supplied to :meth:`build`. Must be
        disjoint from ``query_args_optional``.
    query_args_optional:
        Names of parameters that may be supplied to :meth:`build`. Omitted
        optional args are simply excluded from the parameter dict. Must be
        disjoint from ``query_args_required``.
    Params:
        An optional Pydantic ``BaseModel`` subclass that declares the accepted
        parameters with Python types.  When provided:

        * every name in ``query_args_required`` and ``query_args_optional``
          must appear as a field on the model (checked at construction time);
        * :meth:`build` validates and coerces argument values through the
          model before returning the parameter dict.
    description:
        Human-readable description of what this query does.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        populate_by_name=True,  # accept both name/query_name and cypher/query
    )

    name: str = Field(..., alias="query_name")
    cypher: str = Field(..., alias="query")
    query_args_required: list[str] = Field(default_factory=list)
    query_args_optional: list[str] = Field(default_factory=list)
    description: str | None = Field(default=None)
    Params: type[BaseModel] | None = Field(default=None)  # noqa: N815 — matches Orthograph convention

    @model_validator(mode="after")
    def _validate_structure(self) -> CypherQuerySpec:
        """Check internal consistency immediately after construction."""
        overlap = set(self.query_args_required) & set(self.query_args_optional)
        if overlap:
            names = ", ".join(sorted(overlap))
            raise CypherQuerySpecError(
                f"Query '{self.name}': argument(s) {names!r} appear in both "
                "query_args_required and query_args_optional. "
                "Each argument must appear in at most one list."
            )

        if self.Params is not None:
            model_fields = set(self.Params.model_fields.keys())
            all_args = set(self.query_args_required) | set(self.query_args_optional)
            missing = all_args - model_fields
            if missing:
                names = ", ".join(sorted(missing))
                raise CypherQuerySpecError(
                    f"Query '{self.name}': argument(s) {names!r} are declared "
                    "in query_args_required / query_args_optional but not "
                    "declared in Params. Add them as fields on the Params model "
                    "or remove them from the argument lists."
                )
        return self

    def list_arguments(self) -> dict[str, list[str]]:
        """Return the required and optional argument names.

        Returns a dict with keys ``"required"`` and ``"optional"``.
        """
        return {
            "required": list(self.query_args_required),
            "optional": list(self.query_args_optional),
        }

    def build(self, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        """Validate arguments and return ``(cypher, params)``.

        The returned tuple is ready to pass directly to a driver session::

            cypher, params = query.build(movie_id="M-001")
            await session.run(cypher, params)

        Raises
        ------
        CypherQuerySpecError
            If a required argument is missing or an unknown argument is
            supplied.
        pydantic.ValidationError
            If a ``Params`` model is declared and the supplied values fail
            Pydantic validation.
        """
        self._validate_call_kwargs(kwargs)

        if self.Params is not None:
            validated = self.Params.model_validate(kwargs)
            # Only return fields that were actually supplied (don't inject
            # Pydantic defaults for args the caller did not pass).
            supplied = set(kwargs.keys())
            params = {k: v for k, v in validated.model_dump().items() if k in supplied}
        else:
            params = dict(kwargs)

        return self.cypher, params

    def validate_query(
        self,
        definition: Any | None,  # GraphDefinition | None — typed as Any to avoid
        # circular import concerns; real type is GraphDefinition
    ) -> ValidationResult:
        """Validate this query's Cypher string against ``definition``.

        Runs the same static checks as
        :func:`~orthograph.cypher.parser.validate_cypher`:

        * Cypher dialect parse (syntax)
        * Unknown node labels   → ``QUERY_UNKNOWN_NODE_LABEL`` (ERROR)
        * Unknown rel types     → ``QUERY_UNKNOWN_REL_TYPE`` (ERROR)
        * Unknown properties    → ``QUERY_UNKNOWN_PROPERTY`` (ERROR)
        * Invalid endpoints     → ``QUERY_INVALID_ENDPOINT`` (ERROR)

        Parameters
        ----------
        definition:
            A :class:`~orthograph.graph_definition.graph_definition.GraphDefinition`
            to validate the query against. Pass ``None`` to perform a
            syntax-only check (no domain validation); in that case an empty
            :class:`ValidationResult` (``is_valid=True``) is returned.
        """
        if definition is None:
            return ValidationResult()

        from orthograph.cypher.parser import validate_cypher

        return validate_cypher(query=self.cypher, graph_definition=definition)

    def _validate_call_kwargs(self, kwargs: dict[str, Any]) -> None:
        """Check that all required args are present and no unknown args supplied."""
        missing = [arg for arg in self.query_args_required if arg not in kwargs]
        if missing:
            raise CypherQuerySpecError(
                f"Query '{self.name}': Missing required argument(s): "
                f"{', '.join(missing)}"
            )

        known = set(self.query_args_required) | set(self.query_args_optional)
        unknown = [arg for arg in kwargs if arg not in known]
        if unknown:
            raise CypherQuerySpecError(
                f"Query '{self.name}': Unknown argument(s): "
                f"{', '.join(unknown)}. "
                f"Declared: required={self.query_args_required}, "
                f"optional={self.query_args_optional}"
            )

    def __repr__(self) -> str:
        return (
            f"CypherQuerySpec(name={self.name!r}, "
            f"required={self.query_args_required}, "
            f"optional={self.query_args_optional})"
        )
