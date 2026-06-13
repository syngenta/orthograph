"""Cypher identifier safety — single authority for safe-identifier validation.

Cypher cannot parameterise identifiers (labels, relationship types, property
keys).  Every identifier that is embedded into a query string MUST pass through
:func:`validate_identifier`, which rejects anything outside the safe-identifier
grammar.

The default policy is validate-and-reject.  :func:`escape_identifier` is an
explicit opt-in for backtick-quoting and is NOT wired into generation.
"""

import re

from orthograph.cypher.exceptions import CypherIdentifierError


# Cypher unescaped identifier grammar: letters, digits, underscore; must not
# start with a digit. Anchored with ``\Z`` (not ``$``) so a trailing newline is
# rejected — ``$`` would match just before a final ``\n``, letting e.g.
# ``"Person\n"`` slip through this gate.
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")


def is_safe_identifier(name: str) -> bool:
    """Return True if ``name`` is a safe (unescaped) Cypher identifier."""
    return bool(_SAFE_IDENTIFIER.match(name))


def validate_identifier(name: str, *, kind: str) -> str:
    """Return ``name`` if safe; raise ``CypherIdentifierError`` otherwise.

    ``kind`` (``"label"``, ``"relationship type"``, ``"property key"``) is used
    only in the error message.
    """
    if is_safe_identifier(name):
        return name
    raise CypherIdentifierError(f"Unsafe Cypher {kind}: {name!r}")


def escape_identifier(name: str) -> str:
    """Backtick-quote an identifier, doubling internal backticks.

    Not wired into generation — use :func:`validate_identifier` instead.
    ``Foo`` → `` `Foo` ``; ``Fo`o`` → `` `Fo``o` ``.
    """
    return "`" + name.replace("`", "``") + "`"
