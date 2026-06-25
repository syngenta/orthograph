"""DB-type-string → Python-type mapping for the comparison layer.

This is a pure, dependency-free leaf utility used by both
:mod:`orthograph.comparison.rules` and
:mod:`orthograph.comparison.diff_rules` to translate the database type
vocabulary emitted by a backend inspector into Python built-in types that
can be compared against declared annotations.

Having the mapping here (rather than in the orchestrating
:mod:`orthograph.comparison.engine`) lets the rule modules import it
top-level with no circular-dependency risk, since this module carries no
imports from the comparison package.
"""

_DB_TYPE_MAP: dict[str, type] = {
    "String": str,
    "str": str,
    "Long": int,
    "Integer": int,
    "Int": int,
    "int": int,
    "Double": float,
    "Float": float,
    "float": float,
    "Boolean": bool,
    "Bool": bool,
    "bool": bool,
    "StringArray": list,
    "LongArray": list,
    "DoubleArray": list,
    "List": list,
    "list": list,
}


def db_type_to_python(db_type: str) -> type | None:
    """Map a database type string to a Python type."""
    return _DB_TYPE_MAP.get(db_type)
