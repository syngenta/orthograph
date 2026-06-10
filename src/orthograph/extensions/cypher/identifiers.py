"""Cypher identifier safety — the single authority on safe identifiers.

A small, pure module. No generator logic, no model — just string rules. This is
the seam every identifier interpolation must pass through.

Cypher (and Cypher-like languages) cannot parameterise identifiers — node
labels, relationship types, and property keys are not values and cannot be
passed as ``$param``. Wherever an identifier must be embedded into a query
string, it MUST first pass through :func:`validate_identifier`, which rejects
anything outside the safe-identifier grammar (validate-and-reject by default).

:func:`escape_identifier` is a documented fallback for a future explicit opt-in
(backtick-quoting). It is NOT wired into generation: the default policy is to
fail loudly on an unsafe identifier, not to silently accept an attacker-named
one.
"""

import re

from orthograph.extensions.cypher.exceptions import CypherIdentifierError


# Cypher unescaped identifier grammar: letters, digits, underscore; must not
# start with a digit. Anchored with ``\Z`` (not ``$``) so a trailing newline is
# rejected — ``$`` would match just before a final ``\n``, letting e.g.
# ``"Person\n"`` slip through this gate.
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")


def is_safe_identifier(name: str) -> bool:
    """Return True if ``name`` is a safe (unescaped) Cypher identifier."""
    return bool(_SAFE_IDENTIFIER.match(name))


def validate_identifier(name: str, *, kind: str) -> str:
    """Return ``name`` unchanged if safe, else raise ``CypherIdentifierError``.

    ``kind`` is one of ``"label"``, ``"relationship type"``, ``"property key"``
    and is used only for the error message. This is the function that
    f-string / template interpolation sites MUST call before embedding any
    identifier into a Cypher string.
    """
    if is_safe_identifier(name):
        return name
    raise CypherIdentifierError(f"Unsafe Cypher {kind}: {name!r}")


def escape_identifier(name: str) -> str:
    """Backtick-quote an identifier, doubling internal backticks.

    Defensive fallback only — NOT wired into generation in this epic. The
    generator's policy is validate-and-reject (see :func:`validate_identifier`).

    ``Foo`` -> `` `Foo` `` ; ``Fo`o`` -> `` `Fo``o` ``.
    """
    return "`" + name.replace("`", "``") + "`"
