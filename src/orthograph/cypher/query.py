"""CypherQuery — a concrete, YAML-serialisable Cypher query definition.

Two parallel paths for defining Cypher queries
-----------------------------------------------
Orthograph offers two parallel authoring styles:

* **Typed path** — :class:`~orthograph.cypher.base_models.CypherReadQuery` /
  :class:`~orthograph.cypher.base_models.CypherWriteQuery`.  Abstract bases you
  subclass.  Enforce a full typed contract at class-definition time: ``params_schema``
  model required, ``Output`` model required, ``materialize()`` / ``interpret_result()``
  implementation required.  Results are statically typed.
* **Simple path** — :class:`CypherQuery` (this module).  A **concrete data class
  you instantiate directly** — no subclassing required.  Lower ceremony; YAML
  round-trip compatible via JSON-Schema serialization of ``params_schema`` /
  ``identifiers_schema``.  The only difference from the typed path is that the simple
  path declares **no** ``Output`` model, so results are raw ``list[dict]`` rows.

Both paths share the **same validation core** (``validate_cypher_spec``) and are
first-class :class:`~orthograph.query.catalogue.QueryCatalogue` citizens — a
YAML-loaded ``CypherQuery`` registered in the catalogue is covered by
``validate_query_catalogue`` and produces identical domain codes to an equivalent
typed query.

Design goals
------------
* **YAML-serialisable.** ``params_schema`` and ``identifiers_schema`` models are serialized to
  JSON Schema (via ``model_to_json_schema``) and reconstructed on load (via
  ``model_from_json_schema``).
* **Required typed params_schema.** A ``params_schema`` Pydantic model is **required**.  For
  queries with no ``$value`` parameters, pass ``params_schema = NoParams`` (the canonical
  empty sentinel from :mod:`orthograph.cypher.bindings`).
* **Required typed identifiers_schema.** An ``identifiers_schema`` Pydantic model is
  **required**.  For queries with no ``<<name>>`` identifier splicing, pass
  ``identifiers_schema = NoIdentifiers`` (the canonical empty sentinel from
  :mod:`orthograph.cypher.bindings`).  Identifier *values* are **not** stored on
  the query — they are passed to :meth:`build` at call time, symmetric with
  ``params_schema``.
* **Full shared validation.** Use :func:`~orthograph.cypher.validation._validate_cypher_query`
  (a free function in :mod:`orthograph.cypher.validation`) to validate a
  ``CypherQuery`` against a
  :class:`~orthograph.graph_definition.graph_definition.GraphDefinition`.
  It runs the **same syntactic + semantic checks as the typed path** via the shared
  :func:`~orthograph.cypher.validation.validate_cypher_spec` core — parse,
  ``$param`` ↔ declared-arg alignment, labels, relationship types, property
  accesses, and endpoints.  Passing ``None`` performs a syntactic-only check
  (parse + param alignment) without domain validation.  A stale ``$param`` is
  caught statically on this path (not only at driver runtime).
* **No output model.** Returns raw ``list[dict]`` rows when executed via
  :class:`~orthograph.cypher.query_execution.CypherExecutor`.  Callers unpack
  rows themselves.  This keeps the class useful as a validation-only on-ramp
  before a consuming project is ready to declare typed ``Output`` models.
* **Catalogue citizen.** Carries ``backend = Backend.CYPHER`` (metadata only) and is
registerable in ``QueryCatalogue`` via ``register_cypher_query``.
* **Validation timing.** Validation (:func:`~orthograph.cypher.validation._validate_cypher_query`)
  runs at call time, not class-definition time like the typed path.  The shared field name
  ``cypher_template`` does **not** imply the typed-path definition-time contract.

Usage — Python (simple path)::

     from orthograph.cypher.bindings import NoParams, NoIdentifiers
     from orthograph.cypher.validation import _validate_cypher_query

     query = CypherQuery(
         query_id="find_movie",
         cypher_template="MATCH (m:Movie {movie_id: $movie_id}) RETURN m",
         params_schema=FindMovieParams,
         identifiers_schema=NoIdentifiers,
     )
     result = _validate_cypher_query(query, my_graph_definition)   # static, no DB
     query_data = query.build(movie_id="M-001")
     await session.run(query_data.cypher, query_data.params)

Usage — identifier splicing::

     class LabelIds(BaseModel):
         label: str

     query = CypherQuery(
         query_id="nodes_by_label",
         cypher_template="MATCH (n:<<label>>) RETURN n",
         params_schema=NoParams,
         identifiers_schema=LabelIds,
     )
     query_data = query.build(identifiers=LabelIds(label="Movie"))

Usage — zero-arg query::

     query = CypherQuery(
         query_id="count_movies",
         cypher_template="MATCH (m:Movie) RETURN count(m) AS total",
         params_schema=NoParams,
         identifiers_schema=NoIdentifiers,
     )

YAML serialization (JSON-Schema round-trip)::

     query.model_dump(by_alias=True)
     # Returns:
     # {
     #   "query_id": "find_movie",
     #   "cypher_template": "...",
     #   "params_schema": {...},       # JSON Schema of params_schema
     #   "identifiers_schema": {...},  # JSON Schema of identifiers_schema
     # }
"""  # NOQA E501

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

from orthograph.cypher.bindings import (
    CypherQueryData,
    NoIdentifiers,
    render_with_identifiers,
)
from orthograph.cypher.exceptions import CypherQueryError
from orthograph.cypher.schema_codec import model_from_json_schema, model_to_json_schema
from orthograph.query.base_models import Backend


class CypherQuery(BaseModel):
    """A concrete, YAML-serialisable Cypher query definition.

    Instantiate directly — do not subclass.  For typed queries with full
    ``params_schema`` / ``Output`` / ``materialize()`` contracts, use
    :class:`~orthograph.cypher.base_models.CypherReadQuery` or
    :class:`~orthograph.cypher.base_models.CypherWriteQuery` instead.

    Parameters
    ----------
    query_id:
        Unique identifier for this query within a catalogue or YAML file.
        Serialised as ``query_id`` in YAML/JSON.
    cypher_template:
        The raw Cypher string. ``$name`` placeholders are driver-bound
        parameters; ``<<name>>`` placeholders are identifier slots.
        They must correspond to fields on ``params_schema`` / ``identifiers_schema``.
        No alias accepted — use ``cypher_template`` in YAML files.
    params_schema:
        A Pydantic ``BaseModel`` subclass declaring accepted ``$value``
        parameters with Python types.  **Required** — pass ``NoParams`` for
        zero-arg queries.  Serialised as a JSON Schema and reconstructed on load.
        This field holds a *class* (``type[BaseModel]``), not an instance.
    identifiers_schema:
        A Pydantic ``BaseModel`` subclass declaring ``<<name>>`` identifier
        slots.  **Required** — pass ``NoIdentifiers`` for queries with no
        identifier splicing.  Optional field omitted from serialization when absent.
        Identifier *values* are passed to :meth:`build` at call time, not
        stored on the query instance.  This field holds a *class* (``type[BaseModel]``),
        not an instance.
    description:
        Human-readable description of what this query does.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        populate_by_name=True,
    )

    backend: ClassVar[Backend] = Backend.CYPHER

    query_id: str = Field(...)
    cypher_template: str
    description: str | None = Field(default=None)
    params_schema: type[BaseModel] = Field(...)
    identifiers_schema: type[BaseModel] | None = Field(default=None)

    @field_serializer("params_schema")
    def _serialize_params_schema(self, value: type[BaseModel]) -> dict[str, Any]:
        return model_to_json_schema(value)

    @field_serializer("identifiers_schema")
    def _serialize_identifiers_schema(
        self, value: type[BaseModel] | None
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        return model_to_json_schema(value)

    @field_validator("params_schema", mode="before")
    @classmethod
    def _deserialize_params_schema(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return model_from_json_schema(value)
        return value

    @field_validator("identifiers_schema", mode="before")
    @classmethod
    def _deserialize_identifiers_schema(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return model_from_json_schema(value)
        if value is NoIdentifiers:
            return (
                None  # NoIdentifiers and None are equivalent — omit from serialization
            )
        return value

    def list_arguments(self) -> dict[str, list[str]]:
        """Return required and optional argument names derived from ``params_schema``.

        Returns a dict with keys ``"required"`` and ``"optional"``.
        """
        required = [
            n for n, f in self.params_schema.model_fields.items() if f.is_required()
        ]
        optional = [
            n for n, f in self.params_schema.model_fields.items() if not f.is_required()
        ]
        return {"required": required, "optional": optional}

    def build(
        self, identifiers: BaseModel | None = None, **kwargs: Any
    ) -> CypherQueryData:
        """Validate arguments and return ``CypherQueryData(cypher, params)``.

        The returned value is ready to pass directly to a driver session::

            query_data = query.build(movie_id="M-001")
            await session.run(query_data.cypher, query_data.params)

        For queries with identifier splicing, pass an ``identifiers_schema`` model
        instance::

            query_data = query.build(identifiers=LabelIds(label="Movie"))

        Uses ``model_validate`` + ``exclude_unset=True`` so only the fields
        the caller supplied are included in the params dict (Pydantic defaults
        for omitted optional fields are **not** injected into the driver call).

        Parameters
        ----------
        identifiers:
            Optional model instance matching ``identifiers_schema``.  When ``None`` (the
            default) and ``identifiers_schema`` is not ``NoIdentifiers``, the
            ``cypher_template`` must contain no ``<<name>>`` placeholders
            or a ``CypherQueryDefinitionError`` will be raised by
            ``render_with_identifiers``.  Pass ``None`` for queries declared
            with ``identifiers_schema=NoIdentifiers``.
        **kwargs:
            ``$value`` parameter values validated against ``params_schema``.

        Raises
        ------
        CypherQueryError
            If a required argument is missing or an unknown argument is
            supplied.
        pydantic.ValidationError
            If the supplied values fail ``params_schema`` validation.
        """
        self._validate_call_kwargs(kwargs)

        validated = self.params_schema.model_validate(kwargs)
        params = validated.model_dump(exclude_unset=True)

        cypher = self.cypher_template
        bound = (
            identifiers
            if identifiers is not None
            else (self.identifiers_schema or NoIdentifiers)()
        )
        cypher = render_with_identifiers(cypher, bound)

        return CypherQueryData(cypher, params)

    def _validate_call_kwargs(self, kwargs: dict[str, Any]) -> None:
        """Check that all required args are present and no unknown args supplied."""
        required = [
            n for n, f in self.params_schema.model_fields.items() if f.is_required()
        ]
        known = set(self.params_schema.model_fields)

        missing = [arg for arg in required if arg not in kwargs]
        if missing:
            raise CypherQueryError(
                f"Query '{self.query_id}': Missing required argument(s): "
                f"{', '.join(missing)}"
            )

        unknown = [arg for arg in kwargs if arg not in known]
        if unknown:
            raise CypherQueryError(
                f"Query '{self.query_id}': Unknown argument(s): "
                f"{', '.join(unknown)}. "
                f"Declared on params_schema: {sorted(known)}"
            )

    def __repr__(self) -> str:
        id_name = (
            self.identifiers_schema.__name__
            if self.identifiers_schema is not None
            else "NoIdentifiers"
        )
        return (
            f"CypherQuery(query_id={self.query_id!r}, "
            f"params_schema={self.params_schema.__name__}, "
            f"identifiers_schema={id_name})"
        )
