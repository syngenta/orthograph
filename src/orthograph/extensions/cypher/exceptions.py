"""Custom exceptions raised by the Cypher extension.

A single home for the Cypher backend's raised exceptions, distinct from
``orthograph.core.errors`` (which holds validation *value-objects* such as
``ValidationResult``, not raised exceptions).

All exceptions raised by this extension derive from ``CypherError``, so a caller
can catch the whole family with ``except CypherError`` or a specific subclass.
The specifics of any failure are carried in the exception *message*, not in a
fixed list — differentiate by subclass or by reading the message.
"""


class CypherError(Exception):
    """Base class for every exception raised by the Cypher extension."""


class CypherQueryDefinitionError(CypherError):
    """A declarative query's contract is violated at class-definition time.

    The message names the offending query class and each problem found (empty or
    unparseable ``cypher_template``, or a placeholder that does not map 1:1 to a
    declared ``Params`` / ``Identifiers`` field).
    """


class CypherSyntaxError(CypherError):
    """Cypher produced by ``build()`` does not parse.

    The message names the query and the underlying parse error.
    """
