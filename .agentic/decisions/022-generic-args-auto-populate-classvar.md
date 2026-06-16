# Generic type args auto-populate Params and Output ClassVars; explicit re-declaration is not supported

Every `CypherReadQuery` subclass previously required writing the type twice:

```python
class MoviesByYear(CypherReadQuery[MoviesByYearParams, Movie]):
    Params = MoviesByYearParams  # redundant
    Output = Movie               # redundant
```

The duplication existed because `__init_subclass__` cannot introspect generic type arguments at
runtime. The ClassVars were the introspectable ground truth for validation, catalogue introspection,
and executor param validation.

We use `typing.get_args(cls.__orig_bases__[0])` in `__init_subclass__` to auto-populate `Params`
and `Output` from the generic arguments when the class is concrete. Explicit re-declaration is not
supported: if a subclass declares `Params` or `Output` explicitly and the value disagrees with the
generic argument, a `TypeError` is raised at class-definition time. The library targets Python
3.11+; `get_args` on `__orig_bases__` is reliable at that target.

The ClassVars remain on the class (auto-set, not removed) because they are accessed at runtime by
`CypherExecutor` (`query.Params.model_validate`) and `QueryCatalogue.describe`
(`q.Params.model_json_schema`, `q.Output.model_json_schema`). Accessor methods were considered
and rejected: ClassVars are the correct Python primitive for class-level properties and the
existing call sites depend on them directly.

## Considered options

- **Accept the duplication; add a comment explaining why** — zero ergonomic improvement; every
  query a team writes carries redundant lines.
- **Auto-populate with cross-validation; allow explicit re-declaration as a cross-check** — two
  ways to express the same thing; allows a mismatch between generics and ClassVars to exist
  silently if the cross-check is not enforced strictly.
- **Accessor methods (`params_class()`, `output_class()`)** — adds indirection with no benefit;
  ClassVars are already accessible through instances transparently; antipattern for class-level
  properties.
