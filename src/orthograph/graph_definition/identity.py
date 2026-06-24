"""Relationship-type identity primitive.

``RelTypeKey`` is the single source of truth for relationship-identity
encoding/decoding.  It lives in ``graph_definition/`` — the foundation of the
declared/observed mirror — so both the declared side (``GraphDefinition``) and
the observed side (``GraphProfile`` / ``comparison``) can depend on it
*downward*, honouring the dependency DAG
(``graph_profile`` → ``graph_definition``, never the reverse).
"""

from pydantic import BaseModel


class RelTypeKey(BaseModel):
    """Identity of a relationship type: the ``(source, label, target)`` triple.

    A relationship type is identified by its source node label, its relationship
    label, and its target node label.  Two relationships sharing a
    label but differing in either endpoint are *distinct* types; only an
    identical triple collapses into one type.  ``__directed__`` is *not* part of
    identity.

    ``__str__`` serialises to the deterministic composite ``"source:LABEL:target"``
    used as the ``dict`` key and the comparison address; :meth:`parse` is its
    inverse.  This is the single source of truth for relationship-identity
    encoding/decoding — consumers recover the parts via :meth:`parse`, never by
    ad-hoc string splitting (mirrors the :class:`PartitionKey` convention).

    Delimiter-safety invariant: every label is a safe Cypher identifier matching
    ``^[A-Za-z_][A-Za-z0-9_]*$`` (``cypher/identifiers.py::validate_identifier``),
    so ``:`` can never appear *inside* a part and the encoding is unambiguous.
    """

    model_config = {"frozen": True}

    source_label: str
    label: str
    target_label: str

    def __str__(self) -> str:
        return f"{self.source_label}:{self.label}:{self.target_label}"

    @classmethod
    def parse(cls, key: str) -> "RelTypeKey":
        """Recover a :class:`RelTypeKey` from its ``__str__`` form.

        Strict by design: a wrong split silently mis-identifies a type.  Requires
        exactly three non-empty parts separated by ``:``; anything else raises
        ``ValueError``.
        """
        parts = key.split(":")
        if len(parts) != 3 or not all(parts):
            raise ValueError(f"Malformed RelTypeKey: {key!r}")
        source_label, label, target_label = parts
        return cls(source_label=source_label, label=label, target_label=target_label)
