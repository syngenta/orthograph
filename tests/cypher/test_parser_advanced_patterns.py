"""Advanced Cypher query pattern validation tests.

Tests the validation machinery against 21 distinct structural


Domain: Film/Filmography (equivalent to the original biolab domain).

Covers:
  - All syntactically valid patterns (passes)
  - Parse gaps (G1: pipe rel-types in VL paths, G2: FOREACH)
  - False-positive endpoint checks (B1: reversed undirected traversals)
  - Endpoint check blind spots (B2: multi-MATCH MERGE chains)

Each test is a simple function with a docstring explaining:
  - What pattern it tests
  - What the machinery catches (or fails to catch)
  - Why we fail (root cause if applicable)
"""

from typing import Optional

import pytest

from orthograph.cypher.parser import (
    ReturnKind,
    _validate_cypher,
    extract_return_columns,
)
from orthograph.graph_definition.graph_definition import GraphDefinition
from orthograph.graph_definition.models import NodeModel, RelationshipModel


# ============================================================================
# Domain Model: Film/Filmography
# ============================================================================


class Person(NodeModel):
    __label__ = "Person"
    __uid_field__ = "name"
    name: str
    age: int
    role: Optional[str] = None


class Movie(NodeModel):
    __label__ = "Movie"
    __uid_field__ = "title"
    title: str
    year: int
    technique: Optional[str] = None
    instrument: Optional[str] = None
    method: Optional[str] = None
    comment: Optional[str] = None


class Review(NodeModel):
    __label__ = "Review"
    __uid_field__ = "id"
    id: str
    data: Optional[str] = None


class Screening(NodeModel):
    __label__ = "Screening"
    __uid_field__ = "id"
    id: str
    type: Optional[str] = None
    description: Optional[str] = None
    duration_minutes: Optional[int] = None
    comment: Optional[str] = None


class Festival(NodeModel):
    __label__ = "Festival"
    __uid_field__ = "id"
    id: str
    name: str


class Award(NodeModel):
    __label__ = "Award"
    __uid_field__ = "id"
    id: str


class ActedIn(RelationshipModel):
    __label__ = "ACTED_IN"
    __source_label__ = "Person"
    __target_label__ = "Movie"
    role: str


class Directed(RelationshipModel):
    __label__ = "DIRECTED"
    __source_label__ = "Person"
    __target_label__ = "Movie"


class FeaturedIn(RelationshipModel):
    __label__ = "FEATURED_IN"
    __source_label__ = "Movie"
    __target_label__ = "Festival"


class HasReview(RelationshipModel):
    __label__ = "HAS_REVIEW"
    __source_label__ = "Movie"
    __target_label__ = "Review"


class IsReviewedBy(RelationshipModel):
    __label__ = "IS_REVIEWED_BY"
    __source_label__ = "Person"
    __target_label__ = "Screening"


class HasScreening(RelationshipModel):
    __label__ = "HAS_SCREENING"
    __source_label__ = "Festival"
    __target_label__ = "Screening"


class Generates(RelationshipModel):
    __label__ = "GENERATES"
    __source_label__ = "Screening"
    __target_label__ = "Review"


class Induces(RelationshipModel):
    __label__ = "INDUCES"
    __source_label__ = "Review"
    __target_label__ = "Award"


@pytest.fixture(scope="session")
def graph_definition() -> GraphDefinition:
    """Film/Filmography domain with 6 node types and 8 relationship types."""
    return GraphDefinition(
        name="Filmography",
        node_types=[Person, Movie, Review, Screening, Festival, Award],
        relationship_types=[
            ActedIn,
            Directed,
            FeaturedIn,
            HasReview,
            IsReviewedBy,
            HasScreening,
            Generates,
            Induces,
        ],
    )


# ============================================================================
# P1: MERGE node + SET multiple properties + RETURN
# ============================================================================


def test_p1_merge_set_return_is_valid(graph_definition: GraphDefinition) -> None:
    """P1: Basic MERGE + SET multi-property + RETURN node is valid.

    Pattern: MERGE (m:Movie {title: $title}) SET m.year = $year, m.comment = $comment RETURN m

    What we catch:
      - Node label "Movie" is in the model ✓
      - Properties "year" and "comment" are in the Movie model ✓
      - Query intent detected as "read_write" ✓

    Result: Validates correctly ✓
    """  # NOQA E501
    query = "MERGE (m:Movie {title: $title}) SET m.year = $year, m.comment = $comment RETURN m"  # NOQA E501
    result = _validate_cypher(query, graph_definition)
    assert result.is_valid


def test_p1_merge_set_return_classifies_node_column(
    graph_definition: GraphDefinition,
) -> None:
    """P1: RETURN m is classified as WHOLE_NODE with correct label.

    What we catch:
      - RETURN column classification into SCALAR / WHOLE_NODE / WHOLE_REL ✓
      - Label extraction from pattern ✓

    Result: Correctly identifies m as whole-node return of Movie ✓
    """
    query = "MERGE (m:Movie {title: $title}) SET m.year = $year RETURN m"
    cols = extract_return_columns(query)
    assert cols is not None
    assert len(cols) == 1
    assert cols[0].kind == ReturnKind.WHOLE_NODE
    assert cols[0].label == "Movie"


def test_p1_merge_set_unknown_label_rejected(graph_definition: GraphDefinition) -> None:
    """P1: Unknown node label in MERGE is rejected as QUERY_UNKNOWN_NODE_LABEL.

    Pattern: MERGE (f:Film {...})  where "Film" is not in model (only "Movie" is)

    What we catch:
      - Unknown node label "Film" ✓
      - Issue code: QUERY_UNKNOWN_NODE_LABEL ✓

    Result: Correctly rejects ✓
    """
    query = "MERGE (f:Film {title: $title}) SET f.year = $year RETURN f"
    result = _validate_cypher(query, graph_definition)
    assert not result.is_valid
    assert any(e.code == "QUERY_UNKNOWN_NODE_LABEL" for e in result.errors)


def test_p1_merge_set_unknown_property_rejected(
    graph_definition: GraphDefinition,
) -> None:
    """P1: Unknown property name in SET is rejected as QUERY_UNKNOWN_PROPERTY.

    Pattern: SET m.budget = $budget  where "budget" is not a Movie property

    What we catch:
      - Unknown property "budget" on node "Movie" ✓
      - Issue code: QUERY_UNKNOWN_PROPERTY ✓

    Result: Correctly rejects ✓
    """
    query = "MERGE (m:Movie {title: $title}) SET m.budget = $budget RETURN m"
    result = _validate_cypher(query, graph_definition)
    assert not result.is_valid
    assert any(e.code == "QUERY_UNKNOWN_PROPERTY" for e in result.errors)


# ============================================================================
# P2: 2×MATCH + MERGE rel + RETURN (node, rel, node)
# ============================================================================


def test_p2_two_match_merge_return_three_is_valid(
    graph_definition: GraphDefinition,
) -> None:
    """P2: Two separate MATCH clauses + MERGE rel + RETURN three columns is valid.

    Pattern:
      MATCH (p:Person {name: $name})
      MATCH (m:Movie {title: $title})
      MERGE (p)-[r:ACTED_IN]->(m)
      RETURN p, r, m

    What we catch:
      - Node labels "Person" and "Movie" in model ✓
      - Relationship type "ACTED_IN" in model ✓
      - Query intent detected as "read_write" ✓
      - Three-column RETURN classification ✓

    Why we FAIL to catch:
      - Endpoint validation is SKIPPED for multi-MATCH patterns (B2) ✗
      - Bindings are not consecutive in lineage graph, so no NODE-EDGE-NODE triple is formed
      - Even if endpoints were wrong (Movie→Person for ACTED_IN), we wouldn't catch it

    Result: Validates correctly but blind to endpoint errors ⚠️
    """  # NOQA E501
    query = (
        "MATCH (p:Person {name: $name}) MATCH (m:Movie {title: $title}) "
        "MERGE (p)-[r:ACTED_IN]->(m) RETURN p, r, m"
    )
    result = _validate_cypher(query, graph_definition)
    assert result.is_valid


def test_p2_two_match_merge_endpoint_blind_spot(
    graph_definition: GraphDefinition,
) -> None:
    """P2: Two-MATCH MERGE endpoints are NOT validated (B2 blind spot).

    Pattern: MATCH (m:Movie) MATCH (p:Person) MERGE (m)-[r:ACTED_IN]->(p)

    This is WRONG because ACTED_IN should go Person→Movie, not Movie→Person.

    What we FAIL to catch:
      - Multi-MATCH patterns do not produce NODE-EDGE-NODE triples in the lineage graph
      - _check_endpoints is never called for this pattern
      - Wrong endpoints pass validation silently ✗

    Why:
      - Root cause: Pattern extraction (graphqlot lineage) doesn't handle non-consecutive bindings
      - Separate MATCH clauses create separate binding sequences
      - Algorithm expects consecutive NODE-EDGE-NODE in the bindings list

    Workaround: Use MATCH-chain syntax or manual review of multi-MATCH patterns

    Status: DOCUMENTED BUG (B2) - requires pattern extraction redesign to fix
    """  # NOQA E501
    # Query with WRONG endpoints: Movie→Person instead of Person→Movie
    query = (
        "MATCH (m:Movie {title: $title}) MATCH (p:Person {name: $name}) "
        "MERGE (m)-[r:ACTED_IN]->(p) RETURN m, r, p"
    )
    result = _validate_cypher(query, graph_definition)
    # This should fail but doesn't because endpoints are not checked
    assert result.is_valid  # Documents the blind spot


# ============================================================================
# P4: MATCH + RETURN single node
# ============================================================================


def test_p4_match_return_node_is_valid(graph_definition: GraphDefinition) -> None:
    """P4: Simple MATCH + RETURN node is fully validated.

    Pattern: MATCH (m:Movie {title: $title}) RETURN m

    What we catch:
      - Node label "Movie" in model ✓
      - Property "title" in WHERE clause checked ✓
      - RETURN column classified as WHOLE_NODE with label ✓
      - Query intent detected as "read" ✓

    Result: All validation passes ✓
    """
    query = "MATCH (m:Movie {title: $title}) RETURN m"
    result = _validate_cypher(query, graph_definition)
    assert result.is_valid


def test_p4_match_unknown_property_in_where_rejected(
    graph_definition: GraphDefinition,
) -> None:
    """P4: Unknown property in WHERE clause is caught as QUERY_UNKNOWN_PROPERTY.

    Pattern: WHERE m.budget > 100  where "budget" is not a Movie property

    What we catch:
      - Property access m.budget in WHERE clause ✓
      - "budget" is not in Movie model properties ✓
      - Issue code: QUERY_UNKNOWN_PROPERTY ✓

    Result: Correctly rejects ✓
    """
    query = "MATCH (m:Movie {title: $title}) WHERE m.budget > 100 RETURN m"
    result = _validate_cypher(query, graph_definition)
    assert not result.is_valid
    assert any(e.code == "QUERY_UNKNOWN_PROPERTY" for e in result.errors)


# ============================================================================
# P5: UNWIND + MATCH with local variable + RETURN
# ============================================================================


def test_p5_unwind_local_var_is_valid(graph_definition: GraphDefinition) -> None:
    """P5: UNWIND + MATCH using local variable (not $param) is valid.

    Pattern:
      UNWIND $titles AS title
      MATCH (m:Movie {title: title})
      RETURN m

    What we catch:
      - Node label "Movie" in model ✓
      - Property "title" in WHERE clause ✓
      - Local variable 'title' distinguished from $param syntax ✓
      - Query intent detected as "read" ✓

    Note: The local variable 'title' shadows the UNWIND alias correctly.

    Result: Validates correctly ✓
    """
    query = "UNWIND $titles AS title MATCH (m:Movie {title: title}) RETURN m"
    result = _validate_cypher(query, graph_definition)
    assert result.is_valid


# ============================================================================
# G1: Pipe rel-types in variable-length paths (PARSE GAP)
# ============================================================================


@pytest.mark.xfail(
    reason="G1 GAP: graphqlot treats pipe string as literal rel-type. "
    "Should support [:TYPE1|TYPE2*] syntax. Requires graphqlot upgrade."
)
def test_g1_pipe_rel_types_vl_path_unknown_rel_type(
    graph_definition: GraphDefinition,
) -> None:
    """G1 (GAP): Pipe rel-types in VL paths are treated as single unknown rel-type.

    Pattern: MATCH (a)-[:TYPE1|TYPE2|...*]-(b) RETURN b

    This is VALID Cypher syntax in Neo4j but graphqlot parses it as a literal rel-type name.

    What we catch:
      - Parser treats pipe string as a single rel-type name "FEATURED_IN|HAS_SCREENING" ✓
      - That literal doesn't exist in model, so QUERY_UNKNOWN_REL_TYPE is raised ✓

    What we FAIL to understand:
      - The intent was to match multiple rel-types, not a literal one ✗
      - We cannot validate which rel-types are intended ✗

    Why this matters:
      - Common use case: traverse through different relationship types

    Workaround: Split into single rel-type or use separate queries

    Status: KNOWN GAP - requires graphqlot upgrade to support pipe syntax in rel-types
    """  # NOQA E501
    query = (
        "MATCH (f:Festival) -[:FEATURED_IN|HAS_SCREENING*]-(m:Movie) RETURN DISTINCT m"
    )
    result = _validate_cypher(query, graph_definition)
    # Parser treats the pipe string as a literal rel-type,
    # so we get QUERY_UNKNOWN_REL_TYPE
    assert any(e.code == "QUERY_UNKNOWN_REL_TYPE" for e in result.errors)
    assert not result.is_valid


@pytest.mark.xfail(
    reason="G1 GAP: Multiple VL paths with pipes unparseable. "
    "Requires graphqlot upgrade to support pipe syntax in multiple patterns."
)
def test_g1_double_vl_path_with_pipes_parse_error(
    graph_definition: GraphDefinition,
) -> None:
    """G1 (GAP): Double VL path traversal with pipes also fails to parse.

    Pattern: Sibling discovery - traverse out and then back with multiple rel-types
      UNWIND $titles AS title
      MATCH (seed:Movie {title: title}) -[:ACTED_IN|DIRECTED*]-(p:Person)
      MATCH (p)-[:IS_REVIEWED_BY|HAS_SCREENING*]->(s:Screening)

    What we FAIL to catch:
      - Neither pipe pattern is parseable ✗
      - No validation occurs at all ✗

    What we DO:
      - Returns QUERY_PARSE_ERROR (graceful) ✓

    Impact: Complex multi-step traversals with pipe rel-types cannot be validated

    Status: KNOWN GAP (same root as G1)
    """
    query = (
        "UNWIND $titles AS title "
        "MATCH (seed:Movie {title: title}) -[:ACTED_IN|DIRECTED*]-(p:Person) "
        "MATCH (p)-[:IS_REVIEWED_BY|HAS_SCREENING*]->(s:Screening) "
        "RETURN DISTINCT s"
    )
    result = _validate_cypher(query, graph_definition)
    assert any(e.code == "QUERY_PARSE_ERROR" for e in result.errors)


# ============================================================================
# B1: False-positive endpoint check on reversed undirected traversals
# ============================================================================


@pytest.mark.xfail(
    reason="B1 BUG: graphqlot normalizes by syntactic position, "
    "ignoring arrow direction. "
    "Undirected VL paths are valid Cypher but fire false-positive "
    "QUERY_INVALID_ENDPOINT. "
    "Requires PatternInfo.direction field "
    "and arrow-direction decoding."
)
def test_b1_reverse_vl_path_false_positive_endpoint_check(
    graph_definition: GraphDefinition,
) -> None:
    """B1 (BUG): Reversed VL path traversal triggers false-positive endpoint check.

    Pattern: MATCH (m:Movie)-[:ACTED_IN*]-(p:Person) RETURN p.name

    This is VALID Cypher (undirected VL traversal from Movie) but validator rejects it.

    What we FAIL to catch correctly:
      - graphqlot normalizes pattern bindings by SYNTACTIC POSITION only ✗
      - Ignores Cypher arrow direction (<-, ->, -) ✗
      - Always extracts PatternInfo as: left=source, right=target ✗

    Example extraction:
      Query:   (Movie)-[:ACTED_IN*]-(Person)
      Extracted: PatternInfo(source="Movie", rel="ACTED_IN", target="Person")
      Check: Movie→ACTED_IN→Person vs model Person→ACTED_IN→Movie
      Result: QUERY_INVALID_ENDPOINT ❌ (false positive)

    Why this is wrong:
      - Undirected syntax (-) means traversal is bidirectional
      - Movie can traverse ACTED_IN to reach Person (semantically valid)
      - Validator doesn't understand this semantics

    Root cause:
      - PatternInfo doesn't include direction field
      - Extraction algorithm doesn't decode arrow syntax

    Status: DOCUMENTED BUG (B1) - requires direction decoding in pattern extraction

    xfail: This test FAILS with current machinery (correct assertion below)
    """
    query = (
        "MATCH (m:Movie)-[:ACTED_IN*]-(p:Person) RETURN p.name AS person_name LIMIT 1"
    )
    result = _validate_cypher(query, graph_definition)
    # Current (incorrect) behavior: fires QUERY_INVALID_ENDPOINT
    assert any(e.code == "QUERY_INVALID_ENDPOINT" for e in result.errors)
    # Desired (correct) behavior: should be valid
    # assert result.is_valid  ← This is what we want, but currently fails


def test_b1_forward_vl_path_is_valid_control(graph_definition: GraphDefinition) -> None:
    """B1 (CONTROL): Forward VL path passes validation (no false positive here).

    Pattern: MATCH (p:Person)-[:ACTED_IN*]-(m:Movie) RETURN m.title

    This follows the model direction (Person→ACTED_IN→Movie) so it passes.

    What we catch:
      - PatternInfo(source="Person", target="Movie") matches model ✓
      - Validation passes ✓

    Result: Correct validation (no false positive in this direction)

    This contrasts with B1 to show the directional bias in the validator.
    """
    query = "MATCH (p:Person)-[:ACTED_IN*]-(m:Movie) RETURN m.title AS title LIMIT 1"
    result = _validate_cypher(query, graph_definition)
    assert result.is_valid


# ============================================================================
# B2: Endpoint check blind spot (see P2 test above)
# ============================================================================


def test_b2_multi_match_merge_blind_to_wrong_endpoints(
    graph_definition: GraphDefinition,
) -> None:
    """B2 (BUG): Multi-MATCH MERGE does not validate endpoint relationships.

    Pattern:
      MATCH (a:NodeTypeA)
      MATCH (b:NodeTypeB)
      MERGE (a)-[r:RELATIONSHIP]->(b)

    This pattern doesn't validate that RELATIONSHIP endpoints match NodeTypeA→NodeTypeB.

    What we FAIL to catch:
      - Endpoints are NEVER validated for multi-MATCH patterns ✗
      - Wrong endpoints pass silently ✗

    Example of missed error:
      MATCH (m:Movie)
      MATCH (p:Person)
      MERGE (m)-[r:ACTED_IN]->(p)  ← WRONG (model says Person→Movie)
      → Passes validation (blind spot) ✗

    Root cause:
      - Pattern extraction expects consecutive NODE-EDGE-NODE in bindings list
      - Two separate MATCH clauses don't form consecutive bindings
      - Algorithm never enters _check_endpoints code path

    Why this matters:
      - Silent pass of wrong endpoints is dangerous (data integrity issue)

    Workaround:
      - Use MATCH-chain (connected) syntax instead of two separate MATCHes
      - Or perform manual review of multi-MATCH MERGE patterns

    Status: DOCUMENTED BUG (B2) - requires pattern extraction redesign
    """
    # Query with WRONG endpoints (Movie→Person instead of Person→Movie for ACTED_IN)
    query = (
        "MATCH (m:Movie {title: $title}) MATCH (p:Person {name: $name}) "
        "MERGE (m)-[r:ACTED_IN]->(p) RETURN m, r, p"
    )
    result = _validate_cypher(query, graph_definition)
    # Currently passes (documents blind spot)
    assert result.is_valid


# ============================================================================
# G2: FOREACH clause (PARSE GAP)
# ============================================================================


def test_g2_foreach_parse_error(graph_definition: GraphDefinition) -> None:
    """G2 (GAP): FOREACH loops cause parse error (graphqlot limitation).

    Pattern: FOREACH (var IN collection | statement)

    This is VALID Cypher syntax but graphqlot cannot parse it.

    What we FAIL to catch:
      - Parser raises exception before validation ✗
      - Cannot validate labels or relationships in FOREACH body ✗

    What we DO (gracefully degrade):
      - validate_cypher catches exception ✓
      - Returns QUERY_PARSE_ERROR (does not raise) ✓


    Impact: Cascading cleanup queries cannot be validated

    Workaround: Use separate DELETE statements or imperative code

    Status: KNOWN GAP - requires graphqlot upgrade to support FOREACH
    """
    query = (
        "MATCH (m:Movie {title: $title}) WITH m, collect(m) AS items "
        "FOREACH (node IN items | DETACH DELETE node)"
    )
    result = _validate_cypher(query, graph_definition)
    assert any(e.code == "QUERY_PARSE_ERROR" for e in result.errors)


# ============================================================================
# Valid patterns that pass all checks (positive tests)
# ============================================================================


def test_match_chain_linear_path_validated(graph_definition: GraphDefinition) -> None:
    """Valid pattern: MATCH linear chain with multiple nodes and rels.

    Pattern:
      MATCH (p:Person {name: $name})-[r1:ACTED_IN]->(m:Movie)
            -[r2:HAS_REVIEW]->(rv:Review)
      RETURN p, r1, m, r2, rv

    What we catch:
      - All node labels in model ✓
      - All relationship types in model ✓
      - Five-column RETURN classified correctly (node, rel, node, rel, node) ✓
      - First pattern validates endpoints ✓

    Why first pattern but not others?
      - Pattern extraction forms consecutive NODE-EDGE-NODE triples
      - Only first triple (Person-ACTED_IN-Movie) is validated
      - Second pattern (Movie-HAS_REVIEW-Review) is also extracted but less prominent

    Result: Validates correctly for linear chains ✓
    """
    query = (
        "MATCH (p:Person {name: $name})-[r1:ACTED_IN]->(m:Movie)"
        "-[r2:HAS_REVIEW]->(rv:Review) "
        "RETURN p, r1, m, r2, rv ORDER BY rv.id"
    )
    result = _validate_cypher(query, graph_definition)
    assert result.is_valid
    cols = extract_return_columns(query)
    assert cols is not None
    assert len(cols) == 5


def test_match_with_delete_and_return_props_validated(
    graph_definition: GraphDefinition,
) -> None:
    """Valid pattern: MATCH + WITH + DETACH DELETE + RETURN properties().

    Pattern:
      MATCH (m:Movie {title: $title})
      WITH m, properties(m) AS deleted_movie
      DETACH DELETE m
      RETURN deleted_movie AS m

    What we catch:
      - Node label "Movie" in model ✓
      - Query intent detected as "read_write" ✓
      - DETACH DELETE validated ✓

    What we don't validate:
      - properties() return type is opaque (literal expr) - not classified
      - Return columns = [] (not WHOLE_NODE, not SCALAR) ✓

    Result: Validates correctly (literal expressions are gracefully skipped) ✓
    """
    query = (
        "MATCH (m:Movie {title: $title}) WITH m, properties(m) AS deleted_movie "
        "DETACH DELETE m RETURN deleted_movie AS m"
    )
    result = _validate_cypher(query, graph_definition)
    assert result.is_valid


def test_unwind_match_delete_validated(graph_definition: GraphDefinition) -> None:
    """Valid pattern: UNWIND + MATCH + DETACH DELETE (no RETURN).

    Pattern:
      UNWIND $titles AS title
      MATCH (m:Movie {title: title})
      DETACH DELETE m

    What we catch:
      - Node label "Movie" in model ✓
      - Local variable 'title' used in property match ✓
      - Query intent detected as "write" ✓
      - No RETURN clause (extract_return_columns returns None) ✓

    Result: Validates correctly ✓
    """
    query = "UNWIND $titles AS title MATCH (m:Movie {title: title}) DETACH DELETE m"
    result = _validate_cypher(query, graph_definition)
    assert result.is_valid


def test_optional_match_with_aliased_return_validated(
    graph_definition: GraphDefinition,
) -> None:
    """Valid pattern: MATCH + OPTIONAL MATCH + aliased RETURN.

    Pattern:
      MATCH (p:Person {name: $name})-[:ACTED_IN]->(m:Movie)-[:HAS_REVIEW]->(rv:Review)
      OPTIONAL MATCH (rv)-[:INDUCES]->(a:Award)
      RETURN p AS person, m AS movie, rv AS review, a AS award

    What we catch:
      - All node labels in model ✓
      - All relationship types in model ✓
      - Aliased columns classified correctly with correct labels ✓
      - Four-column RETURN with aliases ✓

    Result: Validates correctly and handles OPTIONAL MATCH well ✓
    """
    query = (
        "MATCH (p:Person {name: $name})-[:ACTED_IN]->(m:Movie)"
        "-[:HAS_REVIEW]->(rv:Review) "
        "OPTIONAL MATCH (rv)-[:INDUCES]->(a:Award) "
        "RETURN p AS person, m AS movie, rv AS review, a AS award"
    )
    result = _validate_cypher(query, graph_definition)
    assert result.is_valid
    cols = extract_return_columns(query)
    assert cols is not None
    assert len(cols) == 4
    assert all(c.kind == ReturnKind.WHOLE_NODE for c in cols)


def test_aggregation_skips_return_validation(graph_definition: GraphDefinition) -> None:
    """Valid pattern: Aggregation queries skip return-column alignment.

    Pattern: RETURN count(DISTINCT m)

    What we catch:
      - Node labels validated ✓
      - Relationship types validated ✓
      - Aggregation detected (is_aggregated flag) ✓

    What we skip:
      - Return column extraction returns None (by design) ✓
      - No alignment check between aggregated result and Output model ✓

    Why skip:
      - Aggregation results are scalars, not whole nodes
      - Alignment check is for structured returns

    Result: Validates correctly ✓
    """
    query = (
        "MATCH (p:Person)-[:ACTED_IN]->(m:Movie {title: $title}) "
        "MATCH (p)-[:ACTED_IN]->(m2:Movie) "
        "RETURN count(DISTINCT m2) AS total"
    )
    result = _validate_cypher(query, graph_definition)
    assert result.is_valid
    cols = extract_return_columns(query)
    assert cols is None  # Aggregation skips extraction


def test_set_map_update_validated(graph_definition: GraphDefinition) -> None:
    """Valid pattern: MATCH + SET with map update (+=) + RETURN.

    Pattern: SET m += $properties

    What we catch:
      - Node label "Movie" in model ✓
      - Query intent detected as "read_write" ✓
      - RETURN node classified correctly ✓

    What we DON'T check:
      - Individual property names in $properties map are opaque ✓
      - No QUERY_UNKNOWN_PROPERTY even if map contains unknown properties ✓

    Why skip map validation:
      - Map parameters are dynamic (only known at runtime)
      - We cannot validate property names in map parameters

    Result: Validates correctly (with known limitation) ✓
    """
    query = "MATCH (m:Movie {title: $title}) SET m += $properties RETURN m"
    result = _validate_cypher(query, graph_definition)
    assert result.is_valid
