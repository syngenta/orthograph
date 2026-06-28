"""GraphValidator -- validates graph data against a GraphDefinition."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from orthograph.diagnostics.classification import EntityType, Severity
from orthograph.diagnostics.result import ValidationIssue, ValidationResult
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import (
    CardinalitySpec,
    ConditionalCardinality,
    NodeModel,
    RelationshipModel,
    coerce_match_value,
    representative_spec,
)


# Type alias for the (label, src_uid, tgt_uid, props) tuple used internally
_RelRecord = tuple[str, str, str, dict[str, Any]]

# Maps (uid, rel_label) → degree count.  Key: the counted node's uid paired with
# the relationship label it participates in (e.g. ("n1", "KNOWS") → 3).
_DegreeCounts = dict[tuple[str, str], int]

# Sorted (key, value) pairs selected from one endpoint's properties.
# Equal selections share one identity regardless of insertion order.
_EndpointProps = tuple[tuple[str, object], ...]

# Absolute partition key: (source-label-node discriminator props,
# target-label-node discriminator props).  Always built in source-then-target
# order regardless of side — the absolute convention (see the ``models`` module
# docstring, the one place the convention is stated).
_Partition = tuple[_EndpointProps, _EndpointProps]

# Maps (uid, rel_label) → {partition → count}.  Key: the counted node's uid
# paired with the relationship label; value: per-partition degree counts.
# Populated only for sides whose cardinality is ConditionalCardinality.
_PartitionCounts = dict[tuple[str, str], dict[_Partition, int]]


@dataclass(frozen=True)
class _IndexedNode:
    """A validated node's identity and properties, indexed by uid.

    Internal currency for referential-integrity and conditional-cardinality
    checks; never crosses the public API boundary.
    """

    label: str
    uid: str
    props: Mapping[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Input unpacking helpers
# ---------------------------------------------------------------------------


def _rel_type_by_label(
    graph_definition: GraphDefinition, label: str
) -> type[RelationshipModel] | None:
    """Resolve a relationship type from a bare label seen on a data record.

    Runtime relationship records carry only the bare ``__label__`` (endpoints are
    not yet threaded through this validator).  Identity is
    the ``(source, label, target)`` triple, so a label may map to more
    than one declared shape; this returns the first declared shape with the
    label, preserving the single-shape behaviour every current caller relies on.
    """
    shapes = graph_definition.get_relationship_types_by_label(label)
    return shapes[0] if shapes else None


def _unpack_node(
    node: dict[str, Any] | NodeModel,
) -> tuple[str | None, dict[str, Any]]:
    """Return (label, props) from a node dict or NodeModel instance.

    ``props`` contains only property fields — never any dunder meta keys.
    """
    if isinstance(node, NodeModel):
        return node.__label__, node.model_dump()
    data = dict(node)
    return data.pop("__label__", None), data


def _unpack_rel(
    rel: dict[str, Any] | RelationshipModel,
) -> tuple[str | None, str | None, str | None, dict[str, Any]]:
    """Return (label, src_uid, tgt_uid, props) from a relationship dict or instance.

    ``props`` contains only property fields — never any dunder meta keys.
    For a ``RelationshipModel`` instance, ``src_uid`` and ``tgt_uid`` are
    always ``None`` because endpoint identity is not part of the model schema;
    callers that pass model instances must not require endpoint-uid validation.
    """
    if isinstance(rel, RelationshipModel):
        return rel.__label__, None, None, rel.model_dump()
    data = dict(rel)
    label = data.pop("__label__", None)
    src_uid = data.pop("__source_uid__", None)
    tgt_uid = data.pop("__target_uid__", None)
    return label, src_uid, tgt_uid, data


def _check_endpoint_types(
    label: str,
    src_uid: str,
    tgt_uid: str,
    src_actual: str,
    tgt_actual: str,
    rel_type: type[RelationshipModel],
) -> list[ValidationIssue]:
    """Return endpoint-type issues for a single relationship instance.

    Called only when both source and target nodes are present in the node index.
    Returns an empty list when endpoints are valid.
    """
    expected_src = rel_type.__source_label__
    expected_tgt = rel_type.__target_label__

    forward_ok = src_actual == expected_src and tgt_actual == expected_tgt
    reverse_ok = (
        not rel_type.__directed__
        and src_actual == expected_tgt
        and tgt_actual == expected_src
    )
    if forward_ok or reverse_ok:
        return []

    entity_id = f"{label}:{src_uid}->{tgt_uid}"

    if not rel_type.__directed__:
        valid_types = sorted({expected_src, expected_tgt})
        return [
            ValidationIssue(
                code="WRONG_ENDPOINT_TYPE",
                severity=Severity.ERROR,
                entity_type=EntityType.RELATIONSHIP,
                entity_id=entity_id,
                message=(
                    f"Undirected relationship '{label}' "
                    f"endpoints ({src_actual}, {tgt_actual}) "
                    f"do not match expected types ({', '.join(valid_types)})"
                ),
                context={
                    "actual_source": src_actual,
                    "actual_target": tgt_actual,
                    "expected_types": valid_types,
                },
            )
        ]

    # Directed: report each mismatched endpoint individually
    issues: list[ValidationIssue] = []
    for uid, actual, expected, role in (
        (src_uid, src_actual, expected_src, "source"),
        (tgt_uid, tgt_actual, expected_tgt, "target"),
    ):
        if actual != expected:
            issues.append(
                ValidationIssue(
                    code="WRONG_ENDPOINT_TYPE",
                    severity=Severity.ERROR,
                    entity_type=EntityType.RELATIONSHIP,
                    entity_id=entity_id,
                    message=(
                        f"{role.capitalize()} node '{uid}' has label '{actual}', "
                        f"expected '{expected}'"
                    ),
                    context={
                        "uid": uid,
                        "role": role,
                        "actual": actual,
                        "expected": expected,
                    },
                )
            )
    return issues


def _cardinality_violation_issue(
    uid: str,
    node_label: str,
    rel_type: type[RelationshipModel],
    direction: str,
    count: int,
) -> ValidationIssue | None:
    """Return a CARDINALITY_VIOLATION issue if ``count`` is out of range, else None."""
    raw_cardinality = (
        rel_type.source_cardinality()
        if direction != "incoming"
        else rel_type.target_cardinality()
    )
    # conditional sides are resolved per pair elsewhere; this
    # constant path collapses any residual conditional (e.g. an undirected
    # side, not partitioned) to its representative spec rather than crashing.
    cardinality = representative_spec(raw_cardinality)
    if cardinality.contains(count):
        return None
    return ValidationIssue(
        code="CARDINALITY_VIOLATION",
        severity=Severity.ERROR,
        entity_type=EntityType.NODE,
        entity_id=f"{node_label}:{uid}",
        message=(
            f"Node '{uid}' ({node_label}) has {count} {direction} "
            f"{rel_type.__label__} relationships, "
            f"expected {cardinality.notation}"
        ),
        context={
            "rel_label": rel_type.__label__,
            "direction": direction,
            "expected_min": cardinality.min,
            "expected_max": cardinality.max,
            "actual": count,
        },
    )


# ---------------------------------------------------------------------------
# Conditional-cardinality checks
# ---------------------------------------------------------------------------


def _referenced_source_keys(card: ConditionalCardinality) -> frozenset[str]:
    """Keys any rule discriminates on for the edge's source-label node (absolute)."""
    keys: set[str] = set()
    for rule in card.rules:
        keys.update(rule.source.conditions)
    return frozenset(keys)


def _referenced_target_keys(card: ConditionalCardinality) -> frozenset[str]:
    """Keys any rule discriminates on for the edge's target-label node (absolute)."""
    keys: set[str] = set()
    for rule in card.rules:
        keys.update(rule.target.conditions)
    return frozenset(keys)


def _select(props: Mapping[str, object], keys: frozenset[str]) -> _EndpointProps:
    """Project *props* onto *keys*, sorted, as a canonical partition component.

    Enum-valued discriminators are reduced to their ``.value`` (via
    :func:`coerce_match_value`) so an observed partition key built from a node's
    ``model_dump()`` (which preserves a plain ``enum.Enum`` member) shares the
    identity of the declared partition authored with the underlying literal.
    Without this, the observed ``(kind, Genre.DRAMA)`` partition and the declared
    ``(kind, "drama")`` partition would never coincide, splitting the count and
    producing a spurious violation.
    """
    return tuple(sorted((k, coerce_match_value(props.get(k))) for k in keys))


def _partition_endpoints(
    partition: _Partition,
) -> tuple[dict[str, object], dict[str, object]]:
    """Split a partition into (source-label props, target-label props) dicts.

    The fixed source-then-target order is the absolute convention (see the
    ``models`` module docstring).
    """
    src, tgt = partition
    return dict(src), dict(tgt)


def _node_matches_any_rule(
    card: ConditionalCardinality, side: str, counted_node_props: Mapping[str, object]
) -> bool:
    """Return True when some rule's counted-endpoint predicate matches this node.

    The counted endpoint is ``rule.source`` on the source side and ``rule.target``
    on the target side (absolute convention, ADR-032 §1a). A wildcard there matches
    every node, so its presence means the node is never "unmatched".
    """
    for rule in card.rules:
        own = rule.source if side == "source" else rule.target
        if own.matches(counted_node_props):
            return True
    return False


def _declared_partitions(
    card: ConditionalCardinality, side: str, counted_node_props: Mapping[str, object]
) -> set[_Partition]:
    """Return partitions a rule pins for this node so a missing one is checked.

    A rule contributes a partition only when its counted-endpoint predicate
    matches the node *and* the opposite-endpoint predicate fixes a value for every
    key that endpoint discriminates on (a fully-determined partition). The pinned
    partition carries both endpoints' selected props (absolute convention): the
    counted node supplies its own matched values, the opposite endpoint the rule's.
    """
    src_keys = _referenced_source_keys(card)
    tgt_keys = _referenced_target_keys(card)
    self_keys = src_keys if side == "source" else tgt_keys
    other_keys = tgt_keys if side == "source" else src_keys

    partitions: set[_Partition] = set()
    for rule in card.rules:
        own = rule.source if side == "source" else rule.target
        other = rule.target if side == "source" else rule.source
        if not own.matches(counted_node_props):
            continue
        if not other_keys <= other.conditions.keys():
            continue
        self_sel = _select(counted_node_props, self_keys)
        other_sel = tuple(sorted((k, other.conditions[k]) for k in other_keys))
        partition = (self_sel, other_sel) if side == "source" else (other_sel, self_sel)
        partitions.add(partition)
    return partitions


def _discriminator_value(
    props: Mapping[str, object], keys: frozenset[str]
) -> object | None:
    """Return the single discriminator value for *keys* read from *props*.

    Conditional cardinality rules discriminate on one property per endpoint in
    practice; the reported ``*_kind`` is that property's value (or ``None`` when
    the endpoint has no discriminator or the value is absent).
    """
    if len(keys) == 1:
        return props.get(next(iter(keys)))
    return None


def _conditional_violation_issue(
    uid: str,
    node_label: str,
    rel_label: str,
    side: str,
    partition: _Partition,
    spec: CardinalitySpec,
    count: int,
    card: ConditionalCardinality,
) -> ValidationIssue:
    """Build a CARDINALITY_VIOLATION naming the source/target discriminator values."""
    src_props, tgt_props = _partition_endpoints(partition)
    source_kind = _discriminator_value(src_props, _referenced_source_keys(card))
    target_kind = _discriminator_value(tgt_props, _referenced_target_keys(card))
    direction = "outgoing" if side == "source" else "incoming"
    max_str = "*" if spec.max is None else str(spec.max)
    return ValidationIssue(
        code="CARDINALITY_VIOLATION",
        severity=Severity.ERROR,
        entity_type=EntityType.NODE,
        entity_id=f"{node_label}:{uid}",
        message=(
            f"Node '{uid}' ({node_label}) has {count} {direction} {rel_label} "
            f"relationships for pair (source={source_kind!r}, "
            f"target={target_kind!r}), expected {spec.min}..{max_str}"
        ),
        context={
            "rel_label": rel_label,
            "direction": direction,
            "source_kind": source_kind,
            "target_kind": target_kind,
            "expected_min": spec.min,
            "expected_max": spec.max,
            "actual": count,
        },
    )


def _counted_keys(card: ConditionalCardinality, side: str) -> frozenset[str]:
    """Keys the counted endpoint discriminates on for *side* (absolute convention)."""
    return (
        _referenced_source_keys(card)
        if side == "source"
        else _referenced_target_keys(card)
    )


def _unmatched_kind_issue(
    uid: str,
    node_label: str,
    rel_label: str,
    side: str,
    counted_node_props: Mapping[str, object],
    card: ConditionalCardinality,
) -> ValidationIssue:
    """Build the CARDINALITY_UNMATCHED_KIND INFO for an unmodelled discriminator."""
    val = _discriminator_value(counted_node_props, _counted_keys(card, side))
    role = "source" if side == "source" else "target"
    return ValidationIssue(
        code="CARDINALITY_UNMATCHED_KIND",
        severity=Severity.INFO,
        entity_type=EntityType.NODE,
        entity_id=f"{node_label}:{uid}",
        message=(
            f"Node '{uid}' ({node_label}) {val!r} matches no {rel_label} "
            f"{role} cardinality rule; the default bound applies."
        ),
        context={
            "rel_label": rel_label,
            "side": side,
            f"{role}_kind": val,
        },
    )


def _default_floor_issue(
    uid: str,
    node_label: str,
    rel_label: str,
    side: str,
    counted_node_props: Mapping[str, object],
    spec: CardinalitySpec,
    total: int,
    card: ConditionalCardinality,
) -> ValidationIssue | None:
    """Return a CARDINALITY_VIOLATION when an unmatched node's total degree on
    this side breaks the ``default`` bound, else ``None``.

    A node whose discriminator matches no rule is governed solely by ``default``
    Enforcing ``default`` against the node's *total* side degree
    keeps a ``min > 0`` default from silently passing a node with no edges
    A permissive default (``min == 0``) admits a
    zero total, so this never fires for the common ``ZERO_OR_MORE`` default.
    """
    if spec.contains(total):
        return None
    val = _discriminator_value(counted_node_props, _counted_keys(card, side))
    role = "source" if side == "source" else "target"
    direction = "outgoing" if side == "source" else "incoming"
    max_str = "*" if spec.max is None else str(spec.max)
    return ValidationIssue(
        code="CARDINALITY_VIOLATION",
        severity=Severity.ERROR,
        entity_type=EntityType.NODE,
        entity_id=f"{node_label}:{uid}",
        message=(
            f"Node '{uid}' ({node_label}) {val!r} matches no {rel_label} "
            f"{role} cardinality rule and has {total} {direction} relationships, "
            f"violating the default bound {spec.min}..{max_str}"
        ),
        context={
            "rel_label": rel_label,
            "direction": direction,
            f"{role}_kind": val,
            "default": True,
            "expected_min": spec.min,
            "expected_max": spec.max,
            "actual": total,
        },
    )


def _check_conditional_side(
    uid: str,
    node_label: str,
    counted_node_props: Mapping[str, object],
    rel_type: type[RelationshipModel],
    side: str,
    card: ConditionalCardinality,
    observed: dict[_Partition, int],
    total: int,
) -> list[ValidationIssue]:
    """Check one conditional cardinality side of a node, partition by partition.

    Each partition's bound comes from ``card.resolve_for_pair(self, other)``; a
    declared-but-unobserved partition counts as 0 so an unmet ``min`` is caught.
    A node whose discriminator matches no rule is governed by ``default``: its
    total side degree is checked against the default (so a ``min > 0`` default is
    not silently skipped) and a CARDINALITY_UNMATCHED_KIND INFO is emitted.
    """
    issues: list[ValidationIssue] = []
    partitions = set(observed) | _declared_partitions(card, side, counted_node_props)

    for partition in partitions:
        # ``resolve_for_pair`` takes (source-label props, target-label props) in
        # that fixed order — the absolute convention (``models`` module docstring).
        source_side_props, target_side_props = _partition_endpoints(partition)
        spec = card.resolve_for_pair(source_side_props, target_side_props)
        count = observed.get(partition, 0)
        if not spec.contains(count):
            issues.append(
                _conditional_violation_issue(
                    uid,
                    node_label,
                    rel_type.__label__,
                    side,
                    partition,
                    spec,
                    count,
                    card,
                )
            )

    if not _node_matches_any_rule(card, side, counted_node_props):
        floor = _default_floor_issue(
            uid,
            node_label,
            rel_type.__label__,
            side,
            counted_node_props,
            card.default,
            total,
            card,
        )
        if floor is not None:
            issues.append(floor)
        issues.append(
            _unmatched_kind_issue(
                uid, node_label, rel_type.__label__, side, counted_node_props, card
            )
        )

    return issues


def _collect_present_labels(
    items: Sequence[dict[str, Any] | NodeModel | RelationshipModel],
    *,
    unpack: Any,
) -> set[str]:
    """Return the set of ``__label__`` values present in *items*."""
    labels: set[str] = set()
    for item in items:
        label = unpack(item)[0]
        if label:
            labels.add(label)
    return labels


def _pydantic_issues(
    entity_type: EntityType,
    entity_id: str,
    exc: PydanticValidationError,
) -> list[ValidationIssue]:
    """Convert a PydanticValidationError into a list of ValidationIssues."""
    return [
        ValidationIssue(
            code="PROPERTY_VALIDATION_ERROR",
            severity=Severity.ERROR,
            entity_type=entity_type,
            entity_id=entity_id,
            message=(
                f"Validation error: {err['msg']} "
                f"(field: {'.'.join(str(loc) for loc in err['loc'])})"
            ),
            context={"pydantic_error": err},
        )
        for err in exc.errors()
    ]


def _extra_properties_issue(
    entity_type: EntityType,
    entity_id: str,
    extra: set[str],
) -> ValidationIssue:
    """Return an EXTRA_PROPERTIES issue for ``extra`` property keys."""
    return ValidationIssue(
        code="EXTRA_PROPERTIES",
        severity=Severity.ERROR,
        entity_type=entity_type,
        entity_id=entity_id,
        message=f"Extra properties not in model: {', '.join(sorted(extra))}",
        context={"extra": sorted(extra)},
    )


def _validate_props(
    entity_type: EntityType,
    entity_id: str,
    model_type: type[NodeModel] | type[RelationshipModel],
    props: dict[str, Any],
    result: "ValidationResult",
) -> bool:
    """Run the extra-props → pydantic guard ladder for one entity.

    Adds any issues to *result*. Returns ``False`` when extra properties are
    found (caller should ``continue`` — the entity is unindexable). Returns
    ``True`` when props are within the declared set (pydantic errors are added
    but do not skip indexing/collecting).
    """
    extra = set(props.keys()) - model_type.get_all_property_names()
    if extra:
        result.add(_extra_properties_issue(entity_type, entity_id, extra))
        return False

    try:
        model_type.model_validate(props)
    except PydanticValidationError as e:
        for issue in _pydantic_issues(entity_type, entity_id, e):
            result.add(issue)
    return True


# ---------------------------------------------------------------------------
# Conditional-cardinality partitioning helpers
# ---------------------------------------------------------------------------


def _absolute_partition(
    card: ConditionalCardinality,
    src_node: "_IndexedNode | None",
    tgt_node: "_IndexedNode | None",
) -> _Partition:
    """Build the absolute (source-label props, target-label props) partition key.

    Selects, from each endpoint, the keys any rule discriminates on for that
    endpoint (the absolute convention; see the ``models`` module docstring). A
    dangling/absent endpoint reads its selected keys as ``None``.
    """
    src_props = src_node.props if src_node is not None else {}
    tgt_props = tgt_node.props if tgt_node is not None else {}
    return (
        _select(src_props, _referenced_source_keys(card)),
        _select(tgt_props, _referenced_target_keys(card)),
    )


def _accumulate_partition(
    partitioned: _PartitionCounts,
    uid: str,
    rel_label: str,
    card: ConditionalCardinality,
    src_node: "_IndexedNode | None",
    tgt_node: "_IndexedNode | None",
) -> None:
    """Increment the partition count for one edge of a conditional side.

    The partition is the absolute (source-label, target-label) discriminator key
    The count is keyed by *uid* (the counted node for this side).
    """
    partition = _absolute_partition(card, src_node, tgt_node)
    partitioned[(uid, rel_label)][partition] += 1


def _partition_counts(
    rel_records: list[_RelRecord],
    graph_definition: GraphDefinition,
    node_index: dict[str, _IndexedNode],
) -> _PartitionCounts:
    """Count directed-edge degrees partitioned by the opposite endpoint's kind.

    Only conditional sides are partitioned; constant sides keep the unpartitioned
    total-count path. The source side keys on the source uid (partitioned by the
    target's properties) and the target side keys on the target uid (partitioned
    by the source's properties).
    """
    partitioned: _PartitionCounts = defaultdict(lambda: defaultdict(int))

    for label, src_uid, tgt_uid, _ in rel_records:
        rel_type = _rel_type_by_label(graph_definition, label)
        if rel_type is None or not rel_type.__directed__:
            continue
        src_node = node_index.get(src_uid)
        tgt_node = node_index.get(tgt_uid)
        src_card = rel_type.source_cardinality()
        if isinstance(src_card, ConditionalCardinality):
            _accumulate_partition(
                partitioned,
                src_uid,
                label,
                src_card,
                src_node,
                tgt_node,
            )
        tgt_card = rel_type.target_cardinality()
        if isinstance(tgt_card, ConditionalCardinality):
            _accumulate_partition(
                partitioned,
                tgt_uid,
                label,
                tgt_card,
                src_node,
                tgt_node,
            )

    return partitioned


def _count_rel_degrees(
    rel_records: list[_RelRecord],
    graph_definition: GraphDefinition,
) -> tuple[_DegreeCounts, _DegreeCounts, _DegreeCounts]:
    """Accumulate outgoing, incoming, and undirected degree counts.

    Returns ``(outgoing_counts, incoming_counts, undirected_counts)`` where
    each maps ``(uid, rel_label)`` to the number of occurrences.
    Undirected counts include both endpoints for each undirected relationship.
    """
    outgoing: _DegreeCounts = defaultdict(int)
    incoming: _DegreeCounts = defaultdict(int)
    undirected: _DegreeCounts = defaultdict(int)

    for label, src_uid, tgt_uid, _ in rel_records:
        outgoing[(src_uid, label)] += 1
        incoming[(tgt_uid, label)] += 1
        rel_type = _rel_type_by_label(graph_definition, label)
        if rel_type and not rel_type.__directed__:
            undirected[(src_uid, label)] += 1
            undirected[(tgt_uid, label)] += 1

    return outgoing, incoming, undirected


def _check_one_side(
    uid: str,
    node_label: str,
    counted_node_props: Mapping[str, object],
    rel_type: type[RelationshipModel],
    side: str,
    card: CardinalitySpec | ConditionalCardinality,
    direction: str,
    constant_count: int,
    observed_partitions: dict[_Partition, int],
    total: int,
) -> list[ValidationIssue]:
    """Check one cardinality side (source or target) of a single node.

    A :class:`ConditionalCardinality` takes the partitioned per-pair path; a
    constant bound takes the single-count path. ``direction`` and the counts are
    resolved by the caller because they differ per side (an undirected rel is
    counted as a node's *total* degree, a directed one by its outgoing/incoming
    degree).
    """
    if isinstance(card, ConditionalCardinality):
        return _check_conditional_side(
            uid,
            node_label,
            counted_node_props,
            rel_type,
            side,
            card,
            observed_partitions,
            total,
        )
    issue = _cardinality_violation_issue(
        uid, node_label, rel_type, direction, constant_count
    )
    return [issue] if issue is not None else []


def _check_node_cardinality(
    uid: str,
    node_label: str,
    node_type: Any,
    counted_node_props: Mapping[str, object],
    graph_definition: GraphDefinition,
    outgoing: _DegreeCounts,
    incoming: _DegreeCounts,
    undirected: _DegreeCounts,
    partitioned: _PartitionCounts,
) -> list[ValidationIssue]:
    """Return cardinality violations for a single node across all its rel types.

    Reads as: for each outgoing rel check the source side; for each incoming
    *directed* rel check the target side. The directed/undirected distinction
    only matters on the outgoing walk — an undirected rel is counted as the
    node's total degree (and skipped on the incoming walk so it is not counted
    twice). :func:`_check_one_side` owns the constant-vs-conditional decision.
    """
    issues: list[ValidationIssue] = []

    for rel_type in graph_definition.get_outgoing_relationship_types(node_type):
        is_undirected = not rel_type.__directed__
        # A conditional side only partitions when the rel is directed; an
        # undirected side resolves through the constant path below.
        card: CardinalitySpec | ConditionalCardinality = (
            representative_spec(rel_type.source_cardinality())
            if is_undirected
            else rel_type.source_cardinality()
        )
        issues += _check_one_side(
            uid,
            node_label,
            counted_node_props,
            rel_type,
            "source",
            card,
            direction="total" if is_undirected else "outgoing",
            constant_count=(undirected if is_undirected else outgoing).get(
                (uid, rel_type.__label__), 0
            ),
            observed_partitions=partitioned.get((uid, rel_type.__label__), {}),
            total=outgoing.get((uid, rel_type.__label__), 0),
        )

    for rel_type in graph_definition.get_incoming_relationship_types(node_type):
        if not rel_type.__directed__:
            continue
        issues += _check_one_side(
            uid,
            node_label,
            counted_node_props,
            rel_type,
            "target",
            rel_type.target_cardinality(),
            direction="incoming",
            constant_count=incoming.get((uid, rel_type.__label__), 0),
            observed_partitions=partitioned.get((uid, rel_type.__label__), {}),
            total=incoming.get((uid, rel_type.__label__), 0),
        )

    return issues


class GraphValidator:
    """Validates graph data (nodes + relationships) against a GraphDefinition.

    Performs: label checks, property validation, referential integrity,
    cardinality checks, and entity presence checks.
    """

    def __init__(self, graph_definition: GraphDefinition) -> None:
        self.graph_definition = graph_definition

    def validate(
        self,
        nodes: Sequence[dict[str, Any] | NodeModel],
        relationships: Sequence[dict[str, Any] | RelationshipModel] | None = None,
    ) -> ValidationResult:
        """Full graph validation: nodes, relationships, references, cardinality."""
        result = ValidationResult()

        if relationships is None:
            relationships = []

        node_result, node_index = self._validate_and_index_nodes(nodes)
        result.merge(node_result)

        rel_result, rel_records = self._validate_and_collect_rels(relationships)
        result.merge(rel_result)

        # Referential integrity + endpoint type checks
        ref_result = self._check_referential_integrity(rel_records, node_index)
        result.merge(ref_result)

        # Cardinality checks
        card_result = self._check_cardinality(node_index, rel_records)
        result.merge(card_result)

        # Entity presence checks
        presence_result = self._check_entity_presence(nodes, relationships)
        result.merge(presence_result)

        return result

    def validate_nodes(
        self, nodes: Sequence[dict[str, Any] | NodeModel]
    ) -> ValidationResult:
        """Validate nodes only (no referential or cardinality checks)."""
        result, _ = self._validate_and_index_nodes(nodes)
        return result

    def validate_relationships(
        self,
        relationships: Sequence[dict[str, Any] | RelationshipModel],
    ) -> ValidationResult:
        """Validate relationships only (no referential checks)."""
        result, _ = self._validate_and_collect_rels(relationships)
        return result

    # --- Internal: node validation ---

    def _validate_and_index_nodes(
        self, nodes: Sequence[dict[str, Any] | NodeModel]
    ) -> tuple[ValidationResult, dict[str, _IndexedNode]]:
        """Validate nodes and build a uid -> _IndexedNode index.

        Returns (result, {uid: _IndexedNode}) for referential and
        conditional-cardinality checks (the latter needs endpoint properties).
        """
        result = ValidationResult()
        node_index: dict[str, _IndexedNode] = {}

        for i, node in enumerate(nodes):
            label, props = _unpack_node(node)

            if label is None:
                result.add(
                    ValidationIssue(
                        code="MISSING_LABEL",
                        severity=Severity.ERROR,
                        entity_type=EntityType.NODE,
                        entity_id=f"node[{i}]",
                        message="Node is missing __label__ field",
                    )
                )
                continue

            node_type = self.graph_definition.get_node_type(label)
            if node_type is None:
                result.add(
                    ValidationIssue(
                        code="UNKNOWN_NODE_LABEL",
                        severity=Severity.ERROR,
                        entity_type=EntityType.NODE,
                        entity_id=f"node[{i}]",
                        message=f"Unknown node label: {label}",
                        context={"label": label},
                    )
                )
                continue

            entity_id = f"node[{i}]:{label}"
            if not _validate_props(
                EntityType.NODE, entity_id, node_type, props, result
            ):
                continue

            uid_field = node_type.__uid_field__
            if uid_field and uid_field in props:
                uid_val = str(props[uid_field])
                node_index[uid_val] = _IndexedNode(
                    label=label, uid=uid_val, props=dict(props)
                )

        return result, node_index

    # --- Internal: relationship validation ---

    def _validate_and_collect_rels(
        self,
        relationships: Sequence[dict[str, Any] | RelationshipModel],
    ) -> tuple[ValidationResult, list[tuple[str, str, str, dict[str, Any]]]]:
        """Validate relationships and collect (label, src_uid, tgt_uid, props).

        Returns (result, records) for referential/cardinality checks.
        """
        result = ValidationResult()
        records: list[tuple[str, str, str, dict[str, Any]]] = []

        for i, rel in enumerate(relationships):
            label, src_uid, tgt_uid, props = _unpack_rel(rel)

            if label is None:
                result.add(
                    ValidationIssue(
                        code="MISSING_LABEL",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=f"rel[{i}]",
                        message="Relationship is missing __label__",
                    )
                )
                continue

            rel_type = _rel_type_by_label(self.graph_definition, label)
            if rel_type is None:
                result.add(
                    ValidationIssue(
                        code="UNKNOWN_RELATIONSHIP_LABEL",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=f"rel[{i}]",
                        message=f"Unknown relationship label: {label}",
                        context={"label": label},
                    )
                )
                continue

            if src_uid is None or tgt_uid is None:
                result.add(
                    ValidationIssue(
                        code="MISSING_ENDPOINT",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=f"rel[{i}]:{label}",
                        message="Relationship missing __source_uid__ or __target_uid__",
                    )
                )
                continue

            entity_id = f"rel[{i}]:{label}"
            if not _validate_props(
                EntityType.RELATIONSHIP, entity_id, rel_type, props, result
            ):
                continue

            records.append((label, str(src_uid), str(tgt_uid), props))

        return result, records

    # --- Internal: referential integrity ---

    def _check_referential_integrity(
        self,
        rel_records: list[tuple[str, str, str, dict[str, Any]]],
        node_index: dict[str, _IndexedNode],
    ) -> ValidationResult:
        result = ValidationResult()

        for label, src_uid, tgt_uid, _ in rel_records:
            rel_type = _rel_type_by_label(self.graph_definition, label)
            if rel_type is None:
                continue

            entity_id = f"{label}:{src_uid}->{tgt_uid}"

            for uid, role in ((src_uid, "source"), (tgt_uid, "target")):
                if uid not in node_index:
                    result.add(
                        ValidationIssue(
                            code="DANGLING_REFERENCE",
                            severity=Severity.ERROR,
                            entity_type=EntityType.RELATIONSHIP,
                            entity_id=entity_id,
                            message=f"{role.capitalize()} node "
                            f"'{uid}' not found in provided nodes",
                            context={"uid": uid, "role": role},
                        )
                    )

            if src_uid in node_index and tgt_uid in node_index:
                src_actual = node_index[src_uid].label
                tgt_actual = node_index[tgt_uid].label
                for issue in _check_endpoint_types(
                    label, src_uid, tgt_uid, src_actual, tgt_actual, rel_type
                ):
                    result.add(issue)

        return result

    # --- Internal: cardinality checks ---

    def _check_cardinality(
        self,
        node_index: dict[str, _IndexedNode],
        rel_records: list[tuple[str, str, str, dict[str, Any]]],
    ) -> ValidationResult:
        result = ValidationResult()
        outgoing, incoming, undirected = _count_rel_degrees(
            rel_records, self.graph_definition
        )
        partitioned = _partition_counts(rel_records, self.graph_definition, node_index)

        for uid, indexed in node_index.items():
            node_type = self.graph_definition.get_node_type(indexed.label)
            if node_type is None:
                continue
            for issue in _check_node_cardinality(
                uid,
                indexed.label,
                node_type,
                indexed.props,
                self.graph_definition,
                outgoing,
                incoming,
                undirected,
                partitioned,
            ):
                result.add(issue)

        return result

    # --- Internal: entity presence ---

    def _check_entity_presence(
        self,
        nodes: Sequence[dict[str, Any] | NodeModel],
        relationships: Sequence[dict[str, Any] | RelationshipModel],
    ) -> ValidationResult:
        result = ValidationResult()

        present_node_labels = _collect_present_labels(nodes, unpack=_unpack_node)
        for nt in self.graph_definition.node_types:
            if not nt.__optional__ and nt.__label__ not in present_node_labels:
                result.add(
                    ValidationIssue(
                        code="MISSING_REQUIRED_TYPE",
                        severity=Severity.ERROR,
                        entity_type=EntityType.NODE,
                        entity_id=nt.__label__,
                        message=f"Required node type "
                        f"'{nt.__label__}' has no instances in data",
                    )
                )

        present_rel_labels = _collect_present_labels(relationships, unpack=_unpack_rel)
        for rt in self.graph_definition.relationship_types:
            if not rt.__optional__ and rt.__label__ not in present_rel_labels:
                result.add(
                    ValidationIssue(
                        code="MISSING_REQUIRED_TYPE",
                        severity=Severity.ERROR,
                        entity_type=EntityType.RELATIONSHIP,
                        entity_id=rt.__label__,
                        message=f"Required relationship type "
                        f"'{rt.__label__}' has no instances in data",
                    )
                )

        return result
