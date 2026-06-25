"""Shared filmography profile fixtures for tutorial notebooks.

Parallel to ``shared/filmography.py`` (which holds the *declared* side —
``FILMOGRAPHY_MODEL``).  This module holds the *observed* side: canonical
``GraphProfile`` objects built against the same filmography domain.

All profiles use the current ``RelationshipTypeProfile`` API:
- ``source_label: str`` / ``target_label: str``  (scalar, ADR-037)
- Relationship-type keys are ``"source:LABEL:target"`` triples.

Public names
------------
FILMOGRAPHY_PROFILE
    A complete, valid filmography profile that satisfies ``FILMOGRAPHY_MODEL``.
    Includes constraints, property completeness, cardinality stats with
    histogram, and value distributions.  Use as the "good" baseline.

FILMOGRAPHY_PROFILE_INVALID
    A deliberately broken profile for comparison / error-demonstration
    notebooks (05.02).  Contains a missing required property, a type
    mismatch, a cardinality violation, and an unexpected node label.

FILMOGRAPHY_PROFILE_STAGING
    A "staging snapshot" profile — used in 05.03 (profile-vs-profile diff).
    City is absent, Genre appeared, Person.name changed type, LIVES_IN
    removed, IN_GENRE added.

Serialisation helpers
---------------------
**JSON is the canonical format for profiles.**  It is natively supported by
Pydantic (``model_dump_json`` / ``model_validate_json``) with no extra
dependencies and an exact round-trip.  The pre-serialised fixtures live in
``notebooks/data/*.json``.

Note: ``orthograph.api.model`` currently has ``load``/``save`` only for
``GraphDefinition`` (YAML-backed).  Profile save/load is not yet in the
public API; the helpers below are notebook-local utilities.  When profile
persistence is promoted to ``api.model``, the format decision (JSON vs YAML)
should be made there.

save_profile_json(profile, path)
    Write *profile* as JSON (Pydantic ``model_dump_json``).  No extra deps.

load_profile_json(path)
    Load and validate a ``GraphProfile`` from a JSON file at *path*.

save_profile(profile, path)   [optional — requires pyyaml]
    Write *profile* as YAML.  Convenience only; the data/ fixtures use JSON.

load_profile(path)            [optional — requires pyyaml]
    Load a ``GraphProfile`` from a YAML file at *path*.
"""

from __future__ import annotations

from pathlib import Path

from orthograph.graph_profile.models import (
    BoundedDistribution,
    CardinalityStats,
    ConstraintInfo,
    GraphProfile,
    NodeTypeProfile,
    PropertyProfile,
    RelationshipTypeProfile,
)


# ---------------------------------------------------------------------------
# FILMOGRAPHY_PROFILE — valid, full filmography snapshot
# ---------------------------------------------------------------------------

FILMOGRAPHY_PROFILE = GraphProfile(
    source="demo — synthetic filmography profile",
    node_type_profiles={
        "Person": NodeTypeProfile(
            label="Person",
            count=120,
            property_profiles={
                "name": PropertyProfile(
                    name="name",
                    present_count=120,
                    total_count=120,
                    observed_types=["String"],
                    constraint_required=True,
                ),
                "born": PropertyProfile(
                    name="born",
                    present_count=90,
                    total_count=120,
                    observed_types=["Long"],
                    constraint_required=False,
                ),
            },
        ),
        "Movie": NodeTypeProfile(
            label="Movie",
            count=38,
            property_profiles={
                "title": PropertyProfile(
                    name="title",
                    present_count=38,
                    total_count=38,
                    observed_types=["String"],
                    constraint_required=True,
                    value_distribution=BoundedDistribution(
                        count=38,
                        histogram={
                            "The Matrix": 1,
                            "Inception": 1,
                            "Avatar": 1,
                            "Dune": 1,
                        },
                        sample_complete=False,
                        limit=4,
                        other_count=34,
                    ),
                ),
                "released": PropertyProfile(
                    name="released",
                    present_count=38,
                    total_count=38,
                    observed_types=["Long"],
                    constraint_required=False,
                ),
            },
        ),
        "City": NodeTypeProfile(
            label="City",
            count=12,
            property_profiles={
                "name": PropertyProfile(
                    name="name",
                    present_count=12,
                    total_count=12,
                    observed_types=["String"],
                    constraint_required=True,
                ),
            },
        ),
    },
    rel_type_profiles={
        "Person:ACTED_IN:Movie": RelationshipTypeProfile(
            rel_type="ACTED_IN",
            count=253,
            source_label="Person",
            target_label="Movie",
            property_profiles={
                "role": PropertyProfile(
                    name="role",
                    present_count=253,
                    total_count=253,
                    observed_types=["String"],
                    constraint_required=True,
                ),
            },
            cardinality_stats=CardinalityStats(
                count=120,
                min=1.0,
                max=8.0,
                mean=2.1,
                variance=3.5,
                histogram={
                    "1": 45,
                    "2": 30,
                    "3": 20,
                    "4": 15,
                    "5": 7,
                    "6": 2,
                    "7": 0,
                    "8": 1,
                },
            ),
        ),
        "Person:DIRECTED:Movie": RelationshipTypeProfile(
            rel_type="DIRECTED",
            count=38,
            source_label="Person",
            target_label="Movie",
            cardinality_stats=CardinalityStats(
                count=30,
                min=1.0,
                max=3.0,
                mean=1.27,
                histogram={"1": 22, "2": 6, "3": 2},
            ),
        ),
        "Person:LIVES_IN:City": RelationshipTypeProfile(
            rel_type="LIVES_IN",
            count=90,
            source_label="Person",
            target_label="City",
        ),
    },
    constraints=[
        ConstraintInfo(
            name="person_name_exists",
            constraint_type="NODE_PROPERTY_EXISTENCE",
            entity_type="NODE",
            labels=["Person"],
            properties=["name"],
        ),
        ConstraintInfo(
            name="movie_title_exists",
            constraint_type="NODE_PROPERTY_EXISTENCE",
            entity_type="NODE",
            labels=["Movie"],
            properties=["title"],
        ),
        ConstraintInfo(
            name="city_name_exists",
            constraint_type="NODE_PROPERTY_EXISTENCE",
            entity_type="NODE",
            labels=["City"],
            properties=["name"],
        ),
        ConstraintInfo(
            name="acted_in_role_exists",
            constraint_type="RELATIONSHIP_PROPERTY_EXISTENCE",
            entity_type="RELATIONSHIP",
            labels=["ACTED_IN"],
            properties=["role"],
        ),
    ],
)


# ---------------------------------------------------------------------------
# FILMOGRAPHY_PROFILE_INVALID — deliberately broken for error demonstration
# ---------------------------------------------------------------------------
# Problems introduced (used in 05.02 §3):
#   - City node label missing           → MISSING_NODE_LABEL (ERROR)
#   - DIRECTED / LIVES_IN missing       → MISSING_REL_TYPE (ERROR)
#   - Movie.released absent             → MISSING_PROPERTY (ERROR)
#   - ACTED_IN.role observed as Long    → PROPERTY_TYPE_MISMATCH (ERROR)
#   - ACTED_IN cardinality min=0        → CARDINALITY_VIOLATION (ERROR)
#   - Genre unexpected                  → UNEXPECTED_NODE_LABEL (WARNING)

FILMOGRAPHY_PROFILE_INVALID = GraphProfile(
    source="neo4j://staging:7687",
    node_type_profiles={
        "Person": NodeTypeProfile(
            label="Person",
            count=50,
            property_profiles={
                "name": PropertyProfile(
                    name="name",
                    present_count=50,
                    total_count=50,
                    observed_types=["String"],
                ),
            },
        ),
        "Movie": NodeTypeProfile(
            label="Movie",
            count=20,
            property_profiles={
                "title": PropertyProfile(
                    name="title",
                    present_count=20,
                    total_count=20,
                    observed_types=["String"],
                ),
                # released is intentionally absent
            },
        ),
        "Genre": NodeTypeProfile(label="Genre", count=5),
    },
    rel_type_profiles={
        "Person:ACTED_IN:Movie": RelationshipTypeProfile(
            rel_type="ACTED_IN",
            count=40,
            source_label="Person",
            target_label="Movie",
            property_profiles={
                "role": PropertyProfile(
                    name="role",
                    present_count=40,
                    total_count=40,
                    observed_types=["Long"],  # wrong type
                ),
            },
            cardinality_stats=CardinalityStats(
                count=50,
                min=0,
                max=5,
                mean=0.8,
            ),  # min=0 violates 1..*
        ),
    },
)


# ---------------------------------------------------------------------------
# FILMOGRAPHY_PROFILE_STAGING — "staging" snapshot for profile-vs-profile diff
# ---------------------------------------------------------------------------
# Differences vs. FILMOGRAPHY_PROFILE (used in 05.03):
#   - City absent                                → NODE_LABEL_ONLY_IN_LEFT
#   - Genre added                                → NODE_LABEL_ONLY_IN_RIGHT
#   - Person.born absent                         → PROPERTY_ONLY_IN_LEFT
#   - Person.name type: String → Integer         → PROPERTY_TYPE_CHANGED
#   - LIVES_IN removed                           → REL_TYPE_ONLY_IN_LEFT
#   - Movie:IN_GENRE:Genre added                 → REL_TYPE_ONLY_IN_RIGHT
#   - ACTED_IN cardinality min changed 1→2       → CARDINALITY_CHANGED

FILMOGRAPHY_PROFILE_STAGING = GraphProfile(
    source="neo4j://staging:7687",
    node_type_profiles={
        "Person": NodeTypeProfile(
            label="Person",
            count=115,
            property_profiles={
                "name": PropertyProfile(
                    name="name",
                    present_count=115,
                    total_count=115,
                    observed_types=["Integer"],  # type changed
                ),
                # born absent
            },
        ),
        "Movie": NodeTypeProfile(
            label="Movie",
            count=40,
            property_profiles={
                "title": PropertyProfile(
                    name="title",
                    present_count=40,
                    total_count=40,
                    observed_types=["String"],
                ),
            },
        ),
        "Genre": NodeTypeProfile(label="Genre", count=5),
    },
    rel_type_profiles={
        "Person:ACTED_IN:Movie": RelationshipTypeProfile(
            rel_type="ACTED_IN",
            count=248,
            source_label="Person",
            target_label="Movie",
            cardinality_stats=CardinalityStats(
                count=115,
                min=2,
                max=10,
                mean=2.2,
            ),
        ),
        "Movie:IN_GENRE:Genre": RelationshipTypeProfile(
            rel_type="IN_GENRE",
            count=40,
            source_label="Movie",
            target_label="Genre",
        ),
        # LIVES_IN intentionally absent
    },
)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------
# JSON is the canonical format — no extra dependency, exact Pydantic round-trip.
# The data/ fixtures are JSON.  YAML is an optional convenience; it requires
# pyyaml and should only be used when human-editability of the snapshot matters.


def save_profile_json(profile: GraphProfile, path: str | Path) -> None:
    """Serialise *profile* to JSON at *path* (no extra dependencies).

    Parameters
    ----------
    profile:
        The :class:`~orthograph.graph_profile.models.GraphProfile` to save.
    path:
        Destination file path (created or overwritten).
    """
    Path(path).write_text(profile.model_dump_json(indent=2), encoding="utf-8")


def load_profile_json(path: str | Path) -> GraphProfile:
    """Load and validate a :class:`~orthograph.graph_profile.models.GraphProfile`
    from a JSON file at *path* (no extra dependencies).

    Parameters
    ----------
    path:
        Source JSON file previously written by :func:`save_profile_json`.
    """
    return GraphProfile.model_validate_json(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Optional YAML helpers (requires pyyaml)
# ---------------------------------------------------------------------------

try:
    import yaml as _yaml

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


def save_profile(profile: GraphProfile, path: str | Path) -> None:
    """Serialise *profile* to YAML at *path*.

    Optional convenience — requires ``pyyaml`` (``pip install pyyaml``).
    The canonical data/ fixtures use JSON; prefer :func:`save_profile_json`
    unless human-editability of the snapshot is important.

    Parameters
    ----------
    profile:
        The :class:`~orthograph.graph_profile.models.GraphProfile` to save.
    path:
        Destination file path (created or overwritten).
    """
    if not _YAML_AVAILABLE:
        raise ImportError(
            "pyyaml is required for YAML serialisation: pip install pyyaml"
        )
    data = profile.model_dump(mode="json")  # datetime -> ISO string
    Path(path).write_text(
        _yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def load_profile(path: str | Path) -> GraphProfile:
    """Load and validate a :class:`~orthograph.graph_profile.models.GraphProfile`
    from a YAML file at *path*.

    Optional convenience — requires ``pyyaml`` (``pip install pyyaml``).
    Prefer :func:`load_profile_json` for the data/ fixtures.

    Parameters
    ----------
    path:
        Source YAML file previously written by :func:`save_profile`.
    """
    if not _YAML_AVAILABLE:
        raise ImportError(
            "pyyaml is required for YAML deserialisation: pip install pyyaml"
        )
    data = _yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return GraphProfile.model_validate(data)
