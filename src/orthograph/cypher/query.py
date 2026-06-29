"""CypherQuery — a concrete, YAML-serialisable Cypher query definition.

Two parallel paths for defining Cypher queries
-----------------------------------------------
Orthograph offers two parallel authoring styles:

* **Typed path** — :class:`~orthograph.cypher.base_models.TypedCypherReadQueryModel` /
  :class:`~orthograph.cypher.base_models.TypedCypherWriteQueryModel`.  Abstract bases you
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
  :mod:`orthograph.cypher.bindings`).  Identifier *values* are bound at
  **construction** (``CypherQuery(..., identifiers=...)``), symmetric with the
  typed path; :meth:`build` takes only a ``params`` model.
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
* **Execution surface.** Run a CypherQuery via
  :class:`~orthograph.cypher.query_execution.CypherQueryExecutor` (or
  :class:`~orthograph.cypher.query_execution.AsyncCypherQueryExecutor`), using
  ``fetch()`` for RETURN queries (``list[dict[str, Any]]``) and ``execute()`` for
  mutations (``CypherWriteResultSummary``); or the public ``run_cypher_fetch`` /
  ``run_cypher_execute`` verbs in ``orthograph.execution``. These are typed
  concretely on ``CypherQuery`` — no ``# type: ignore`` is needed. The simple path
  is NOT passed to the typed ``CypherExecutor`` (use the typed path for that).
  The caller owns the transaction (ADR-028).
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
     query_data = query.build(FindMovieParams(movie_id="M-001"))
     await session.run(query_data.cypher, query_data.params)

Usage — identifier splicing::

     class LabelIds(BaseModel):
         label: str

     query = CypherQuery(
         query_id="nodes_by_label",
         cypher_template="MATCH (n:<<label>>) RETURN n",
         params_schema=NoParams,
         identifiers_schema=LabelIds,
         identifiers=LabelIds(label="Movie"),
     )
     query_data = query.build(NoParams())

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
    PrivateAttr,
    field_serializer,
    field_validator,
)

from orthograph.cypher.bindings import (
    CypherQueryData,
    NoIdentifiers,
    render_with_identifiers,
)
from orthograph.cypher.schema_codec import model_from_json_schema, model_to_json_schema
from orthograph.query.base_models import Backend


class CypherQuery(BaseModel):
    """A concrete, YAML-serialisable Cypher query definition.

    Instantiate directly — do not subclass.  For typed queries with full
    ``params_schema`` / ``Output`` / ``materialize()`` contracts, use
    :class:`~orthograph.cypher.base_models.TypedCypherReadQueryModel` or
    :class:`~orthograph.cypher.base_models.TypedCypherWriteQueryModel` instead.

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
        Identifier *values* are passed at construction (``identifiers=``), not
        to :meth:`build`.  This field holds a *class* (``type[BaseModel]``),
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

    # Bound identifier *values* (not a Pydantic field — never serialised, so the
    # YAML wire format stays schema-only).  Symmetric with the typed path's
    # ``TypedCypherReadQueryModel.__init__`` which also binds ``self._identifiers``.
    # ``None`` means "no identifier values supplied" — only the schema is known
    # (e.g. a YAML-loaded query carries the schema but no values); a template
    # with ``<<name>>`` slots then errors at ``build`` time, as before.
    _identifiers: BaseModel | None = PrivateAttr(default=None)

    def __init__(
        self, *, identifiers: BaseModel | dict[str, Any] | None = None, **data: Any
    ) -> None:
        """Construct the query and bind identifier *values* at construction.

        ``identifiers`` (when supplied) is validated against
        ``identifiers_schema`` and stored on a ``PrivateAttr`` — it does not
        enter ``model_dump``/JSON-Schema, so the YAML wire format is unchanged.
        This mirrors the typed path, where identifier values are likewise bound
        at construction and ``build`` takes only a ``params`` model.

        When ``identifiers`` is omitted, no values are bound — the simple path
        is then ``NoIdentifiers``-only (the de facto execution contract); a
        template carrying ``<<name>>`` slots raises at ``build`` time.
        """
        super().__init__(**data)
        if identifiers is not None:
            schema = self.identifiers_schema or NoIdentifiers
            self._identifiers = schema.model_validate(identifiers)

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

    def build(self, params: BaseModel) -> CypherQueryData:
        """Validate arguments and return ``CypherQueryData(cypher, params)``.

        The returned value is ready to pass directly to a driver session::

            query_data = query.build(FindMovieParams(movie_id="M-001"))
            await session.run(query_data.cypher, query_data.params)

        Identifier values are bound at *construction* (see :meth:`__init__`) and
        spliced into their ``<<name>>`` slots here — symmetric with the typed
        path.  ``build`` takes only the ``params`` model.

        Uses ``model_dump(exclude_unset=True)`` so only the fields the caller
        supplied are included in the params dict (Pydantic defaults for omitted
        optional fields are **not** injected into the driver call).

        Parameters
        ----------
        params:
            A ``params_schema`` model instance carrying the ``$value`` parameters.
        """
        cypher = render_with_identifiers(
            self.cypher_template, self._identifiers or NoIdentifiers()
        )
        return CypherQueryData(cypher, params.model_dump(exclude_unset=True))

    def materialize(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Identity materialiser — returns raw rows as plain dicts.

        The simple path declares no ``Output`` model, so reads via
        :class:`~orthograph.cypher.query_execution.CypherExecutor` yield raw
        ``list[dict]`` rows.
        """
        return dict(raw)

    def interpret_result(self, raw: Any) -> Any:
        """Return the write summary unchanged — raw counters for the on-ramp."""
        return raw

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
