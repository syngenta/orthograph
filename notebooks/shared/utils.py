"""Utility functions for database profiling notebooks and scripts.

Includes:
- Environment variable loading (from .env files)
- APOC detection and status reporting
- Database profiling and display functions
"""

import os
from pathlib import Path

from orthograph.api.database import inspect


# ============================================================================
# Environment Variable Loading
# ============================================================================


def load_env(key: str, default: str = "") -> str:
    """Load environment variable from .env file or fallback to default.

    Searches in this order:
    1. Already-set environment variable (e.g., from OS or pytest)
    2. .env file in the repository root
    3. .env_default file in the repository root
    4. Provided default value

    Args:
        key: Environment variable name (e.g., "NEO4J_PASSWORD")
        default: Fallback value if not found in .env or environment

    Returns:
        The environment variable value or default

    Example:
        >>> neo4j_password = load_env("NEO4J_PASSWORD", "password")
    """
    # Check if already in environment (e.g., from pytest CLI or OS)
    value = os.environ.get(key)
    if value:
        return value

    # Try .env file (git-ignored, contains actual credentials)
    root = _find_repo_root()
    env_file = root / ".env"
    if env_file.exists():
        _load_dotenv(env_file)
        value = os.environ.get(key)
        if value:
            return value

    # Try .env_default file (git-tracked template)
    env_default = root / ".env_default"
    if env_default.exists():
        _load_dotenv(env_default)
        value = os.environ.get(key)
        if value:
            return value

    # Fall back to provided default
    return default


def _find_repo_root() -> Path:
    """Find the repository root by looking for .env or .env_default.

    Walks up from the notebooks directory until it finds one of these files.
    """
    current = Path(__file__).parent  # notebooks/ directory
    for _ in range(5):  # Search up to 5 levels
        if (current / ".env").exists() or (current / ".env_default").exists():
            return current
        current = current.parent
    # Fallback: return the directory where this script lives
    return Path(__file__).parent


def _load_dotenv(path: Path) -> None:
    """Load .env file into os.environ, skipping comments and empty lines.

    Lines starting with # are treated as comments.
    Empty lines are ignored.
    Format: KEY=VALUE (no quotes needed)
    """
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()
    except FileNotFoundError:
        pass


# ============================================================================
# APOC Detection
# ============================================================================


def check_apoc_available(driver) -> bool:
    """Check if APOC procedures are available in Neo4j.

    Args:
        driver: Neo4j GraphDatabase driver instance

    Returns:
        True if apoc.meta.* procedures are available, False otherwise
    """
    try:
        records, _, _ = driver.execute_query(
            "SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'apoc.meta' "
            "RETURN count(name) AS cnt"
        )
        return records[0]["cnt"] > 0 if records else False
    except Exception:
        return False


def print_apoc_status(driver) -> None:
    """Print APOC availability status with tips.

    Args:
        driver: Neo4j GraphDatabase driver instance
    """
    if check_apoc_available(driver):
        print("  APOC: ✓ Available (property types will be detected)")
    else:
        print("  APOC: ✗ Not available (property types will be empty)")
        print("       Install APOC plugin to see observed_types in profiles")


# ============================================================================
# Database Profiling Functions
# ============================================================================


def get_database_info(driver) -> tuple[str, str, int, int]:
    """Get database component info and node/relationship counts.

    Args:
        driver: Neo4j GraphDatabase driver instance

    Returns:
        Tuple of (database_name, version, node_count, rel_count)
    """
    # Get database info
    info = driver.execute_query("CALL dbms.components() YIELD name, versions").records
    db_name = ""
    db_version = ""
    if info:
        db_name = info[0]["name"]
        db_version = str(info[0]["versions"])

    # Get counts
    records, _, _ = driver.execute_query("MATCH (n) RETURN count(n) as cnt")
    node_count = records[0]["cnt"] if records else 0

    records, _, _ = driver.execute_query("MATCH ()-[r]->() RETURN count(r) as cnt")
    rel_count = records[0]["cnt"] if records else 0

    return db_name, db_version, node_count, rel_count


def extract_profile(driver):
    """Extract a comprehensive database profile.

    Args:
        driver: Neo4j GraphDatabase driver instance

    Returns:
        GraphProfile object
    """
    return inspect("neo4j", driver)


def display_profile_summary(profile) -> None:
    """Display a summary of the profile.

    Args:
        profile: GraphProfile object from inspect()
    """
    print("\n✓ Profile extracted")
    print(f"  Source: {profile.source}")
    print(f"  Timestamp: {profile.timestamp}")
    print(f"  Node types detected: {len(profile.node_type_profiles)}")
    print(f"  Relationship types detected: {len(profile.rel_type_profiles)}")
    constraints_count = len(profile.constraints) if profile.constraints else 0
    print(f"  Constraints found: {constraints_count}")


def display_node_profiles(profile) -> None:
    """Display all node type profiles with properties and completeness.

    Args:
        profile: GraphProfile object from inspect()
    """
    print("\n" + "=" * 80)
    print("NODE TYPE PROFILES")
    print("=" * 80)

    if not profile.node_type_profiles:
        print("\nNo node types found in database.")
    else:
        for label, ntp in sorted(profile.node_type_profiles.items()):
            print(f"\n{label} (count: {ntp.count} instances)")
            print("-" * 80)

            if not ntp.property_profiles:
                print("  No properties detected")
            else:
                print(f"  {'Property':<25} {'Completeness':>15}  {'Observed Types'}")
                print(f"  {'-' * 25} {'-' * 15}  {'-' * 30}")

                for prop_name in sorted(ntp.property_profiles.keys()):
                    pp = ntp.property_profiles[prop_name]
                    completeness_pct = f"{pp.completeness * 100:.1f}%"
                    types_str = (
                        ", ".join(sorted(pp.observed_types))
                        if pp.observed_types
                        else "(APOC required)"
                    )
                    print(f"  {prop_name:<25} {completeness_pct:>15}  {types_str}")


def display_relationship_profiles(profile) -> None:
    """Display all relationship type profiles with properties and cardinality.

    Args:
        profile: GraphProfile object from inspect()
    """
    print("\n" + "=" * 80)
    print("RELATIONSHIP TYPE PROFILES")
    print("=" * 80)

    if not profile.rel_type_profiles:
        print("\nNo relationship types found in database.")
    else:
        for label, rtp in sorted(profile.rel_type_profiles.items()):
            source_labels = rtp.source_labels if rtp.source_labels else {"<any>"}
            target_labels = rtp.target_labels if rtp.target_labels else {"<any>"}
            source_str = ", ".join(sorted(source_labels))
            target_str = ", ".join(sorted(target_labels))

            print(f"\n{label} (count: {rtp.count} instances)")
            print(f"  Direction: ({source_str}) -[:{label}]-> ({target_str})")
            print("-" * 80)

            if rtp.cardinality_stats:
                cs = rtp.cardinality_stats
                avg_str = f"{cs.mean:.2f}" if cs.mean is not None else "N/A"
                degree_info = f"min={cs.min}, max={cs.max}, avg={avg_str}"
                print(f"  Degree cardinality: {degree_info}")

            if rtp.property_profiles:
                print(f"\n  {'Property':<25} {'Completeness':>15}  {'Observed Types'}")
                print(f"  {'-' * 25} {'-' * 15}  {'-' * 30}")

                for prop_name in sorted(rtp.property_profiles.keys()):
                    pp = rtp.property_profiles[prop_name]
                    completeness_pct = f"{pp.completeness * 100:.1f}%"
                    types_str = (
                        ", ".join(sorted(pp.observed_types))
                        if pp.observed_types
                        else "(APOC required)"
                    )
                    print(f"  {prop_name:<25} {completeness_pct:>15}  {types_str}")
            else:
                print("  No properties")


def display_constraints(profile) -> None:
    """Display all database constraints.

    Args:
        profile: GraphProfile object from inspect()
    """
    print("\n" + "=" * 80)
    print("DATABASE CONSTRAINTS")
    print("=" * 80)

    if not profile.constraints:
        print("\nNo constraints defined in the database.")
    else:
        for constraint in profile.constraints:
            print(f"\nConstraint: {constraint.name}")
            print(f"  Type: {constraint.constraint_type}")
            properties_str = (
                ", ".join(constraint.properties) if constraint.properties else "<none>"
            )
            print(f"  Property(ies): {properties_str}")
            if constraint.labels:
                print(f"  Labels: {', '.join(constraint.labels)}")


def export_profile_json(profile, output_dir: str = "scratch") -> Path:
    """Export profile to JSON file.

    Args:
        profile: GraphProfile object from inspect()
        output_dir: Directory to save the JSON file (default: "scratch")

    Returns:
        Path to the exported JSON file
    """
    scratch_dir = Path(output_dir)
    scratch_dir.mkdir(exist_ok=True)

    profile_json = profile.model_dump_json(indent=2)
    output_file = scratch_dir / "profile_export.json"

    with open(output_file, "w") as f:
        f.write(profile_json)

    return output_file
