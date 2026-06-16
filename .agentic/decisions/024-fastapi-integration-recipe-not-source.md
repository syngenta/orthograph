# FastAPI integration lives in recipe notebooks, not in library source

`QueryDescription.params_schema` and `output_schema` (and the new `output_class` field) are the
right pieces for auto-generating OpenAPI endpoint schemas. A team building a FastAPI endpoint can
wire `ReadPort.fetch(params)` as a `Depends()` dependency and pass `query.Output` directly as
`response_model=`.

We do not ship any FastAPI-aware helpers, `QueryRouter`, or framework integration code in
`src/orthograph/`. The boundary is: orthograph produces typed query contracts; consuming
applications own their web framework wiring. This is a hard constraint: the library must not
acquire a hard or optional dependency on FastAPI, Starlette, or any web framework.

The integration pattern is demonstrated in notebook `05.01_openapi_ergonomics_assessment.ipynb`
as illustrative (non-executing) code cells. The notebook covers: `GET` endpoint wiring with
`response_model=`, `POST` endpoint wiring with optional write `Output`, the `Depends()` DI
pattern for `ReadPort`, and `PaginatedParams` composition. A runnable vertical slice (live
FastAPI app with test client) is deferred to a future notebook or integration test suite.

## Considered options

- **Thin `fastapi` optional extra with a `QueryRouter` helper** — would auto-wire a
  `QueryCatalogue` to FastAPI routes; rejected because it creates framework lock-in, couples
  orthograph's release cycle to FastAPI's, and the value proposition is unclear until real
  consumer experience is gathered post-public.
- **No documentation at all** — leaves the DI wiring pattern as a discovery problem for every
  team; rejected because the pattern is non-obvious enough to warrant a recipe.
