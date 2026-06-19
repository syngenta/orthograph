# Profiling Neo4j with Orthograph — Complete Guide

Complete guide to profiling Neo4j databases and understanding how property-type
detection works, including the three inspection strategies and APOC requirements.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Tool Comparison](#tool-comparison)
3. [Inspection Strategies](#inspection-strategies)
4. [Installation](#installation)
5. [Credential Management](#credential-management)
6. [Usage Examples](#usage-examples)
7. [Understanding observed_types](#understanding-observed_types)
8. [Troubleshooting](#troubleshooting)
9. [Technical Details](#technical-details)

---

## Quick Start

### Profile Your Database (Fastest)

```bash
cd notebooks
python profile_script.py
```

This will:
- Connect to Neo4j (using `.env` credentials)
- **Auto-detect the best inspection strategy** (APOC → `db.schema.*` → pure-Cypher)
- Extract profile
- Display results
- Export to `scratch/profile_export.json`

### Profile with Jupyter Notebook

```bash
jupyter notebook
# Open: 06.02_profile_neo4j_custom.ipynb
# Edit: Cell 1 - Add your credentials
# Run: All cells
```

### Learn with Sample Data

```bash
jupyter notebook
# Open: 06.01_profile_neo4j_example.ipynb
# Run: All cells
# Data is auto-populated and profiled
```

---

## Tool Comparison

| Task | Tool | Setup | Speed | Output |
|------|------|-------|-------|--------|
| **Learn profiling** | `06.01_profile_neo4j_example.ipynb` | ⭐⭐ | Slow | Console |
| **Profile database** | `06.02_profile_neo4j_custom.ipynb` | ⭐ | Slow | Console |
| **Automate profiling** | `profile_script.py` | ⭐ | Fast | JSON |

---

## Inspection Strategies

`Neo4jInspector` reads property types (`observed_types`) using one of three
strategies, **auto-detected in order**:

| Priority | Strategy | Source | `observed_types` | Completeness counts |
|----------|----------|--------|------------------|---------------------|
| 1st | **APOC** | `apoc.meta.*` (requires APOC **Core**) | populated | true |
| 2nd | **SCHEMA** | built-in `db.schema.*` + Cypher scan | populated | true |
| 3rd | **CYPHER** | pure-Cypher scan only | `[]` (empty) | true |

**Completeness counts are always true** — all three strategies use the
pure-Cypher two-pass scan for counts. The strategies differ only in whether
they can report `observed_types`.

### Strategy 1: APOC (Best — when available)

Uses `apoc.meta.nodeTypeProperties()` and `apoc.meta.relTypeProperties()`.

- Requires **APOC Core** (the plugin must register `apoc.meta.*` procedures).
- ⚠️  **APOC Extended** (`apoc5plus`) does **not** register `apoc.meta.*` — the
  inspector detects this and falls through to SCHEMA automatically.

```python
# APOC is auto-detected; you can also force it:
from orthograph.backends.neo4j.inspector import Neo4jInspector, Neo4jInspectionStrategy

profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.APOC).inspect(driver)
```

### Strategy 2: SCHEMA (Built-in fallback — available since Neo4j 4.x)

Uses the built-in `db.schema.nodeTypeProperties()` / `db.schema.relTypeProperties()`
procedures (no plugin required) for types, combined with the pure-Cypher scan for
true completeness counts.

This is the strategy that **resolves the APOC-Extended pitfall**: when APOC is
absent or only the Extended flavour is installed, types are still populated via
the built-in procedures that ship with every Neo4j 4.x+ instance.

Key constraint: `db.schema.*` returns **types but no observation counts**. Counts
always come from the Cypher scan — so completeness fidelity is identical to
pure-Cypher and the SCHEMA strategy is strictly better than falling back to CYPHER.

```python
# Force SCHEMA (e.g. on a system without APOC):
profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.SCHEMA).inspect(driver)
```

### Strategy 3: CYPHER (Last resort)

Pure-Cypher two-pass scan: true completeness counts but `observed_types = []`.
Used only when neither `apoc.meta.*` nor `db.schema.*` is available.

```python
# Force pure-Cypher (no types, but still true counts):
profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(driver)
```

### Tradeoff Table

| | `observed_types` | Completeness counts | Plugin required |
|---|---|---|---|
| **APOC** | ✅ populated | ✅ true | APOC Core |
| **SCHEMA** | ✅ populated | ✅ true | none (built-in) |
| **CYPHER** | ❌ `[]` | ✅ true | none |

> **Note:** `db.schema.*` types are schema-inferred; they reflect all types ever
> stored for a property across the graph's lifetime, not just the current snapshot.
> APOC samples actual data. In practice both agree for stable schemas.

### The APOC-Extended Pitfall

Some Neo4j deployments install **APOC Extended** (`apoc5plus`) instead of APOC
Core. APOC Extended does **not** register `apoc.meta.*`. Before E44, the inspector
detected zero `apoc.meta` procedures, fell back to pure-Cypher, and reported
`observed_types = []` for every property — even though `db.schema.*` was available
the whole time. The auto-detection order (APOC → SCHEMA → CYPHER) fixes this
silently: APOC Extended users now get types via SCHEMA.

### Explicit Strategy Selection

```python
from orthograph.backends.neo4j.inspector import Neo4jInspector, Neo4jInspectionStrategy

# Auto-detect (recommended — picks the best available)
profile = Neo4jInspector().inspect(driver)

# Force a specific strategy
profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.SCHEMA).inspect(driver)
profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER).inspect(driver)

# Deprecated — still works but emits DeprecationWarning
profile = Neo4jInspector(use_apoc=False).inspect(driver)  # → CYPHER
profile = Neo4jInspector(use_apoc=True).inspect(driver)   # → APOC
```

---

## Installation

### Option A: Docker (Recommended)

```bash
docker run --name neo4j \
  -p 7474:7474 \
  -p 7687:7687 \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:latest
```

This installs APOC Core. The inspector will use the APOC strategy automatically.

### Option B: Local Neo4j

```bash
# 1. Download APOC Core jar (not APOC Extended / apoc5plus)
cd ~/Downloads
wget https://github.com/neo4j-contrib/neo4j-apoc-procedures/releases/download/[VERSION]/apoc-[VERSION]-core.jar

# 2. Copy to plugins directory
cp apoc-*-core.jar $NEO4J_HOME/plugins/

# 3. Restart Neo4j
systemctl restart neo4j  # (or your restart method)

# 4. Verify APOC Core is available
cypher-shell "SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'apoc.meta' RETURN count(name)"
# Should return: 10 (or similar)
```

### Without APOC

`db.schema.*` is a Neo4j built-in (available since 4.x) — no installation needed.
The inspector will fall through to SCHEMA automatically if APOC is absent.

---

## Credential Management

### Using `.env` file (Recommended)

1. Create `notebooks/.env` from `.env_default`:
   ```bash
   cp notebooks/.env_default notebooks/.env
   ```

2. Edit `notebooks/.env`:
   ```
   NEO4J_URI=bolt://localhost:7687
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=your-password
   ```

3. Both notebooks and script will auto-load these.

### Direct Credentials in Notebook

Edit Cell 1 of `06.02_profile_neo4j_custom.ipynb`:
```python
neo4j_uri = "bolt://your-server:7687"
neo4j_user = "your-user"
neo4j_password = "your-password"
```

### Environment Variables

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=password
python profile_script.py
```

---

## Usage Examples

### Example 1: CLI Profiling

```bash
python profile_script.py
```

Output (APOC or SCHEMA detected):
```
Connecting to bolt://localhost:7687...
Connected

Profiling database 'neo4j' ...
[profile output with types populated]

Full profile written to: scratch/profile_export.json
```

### Example 2: Programmatic Usage

```python
from neo4j import GraphDatabase
from orthograph.api.database import inspect as ograph_inspect

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
profile = ograph_inspect("neo4j", driver)

for label, node_profile in profile.node_type_profiles.items():
    print(f"{label}:")
    for prop_name, pp in node_profile.property_profiles.items():
        print(f"  {prop_name}: {pp.completeness:.0%} complete, types={pp.observed_types}")

driver.close()
```

---

## Understanding observed_types

### What You See

When types are populated (APOC or SCHEMA strategy):
```
Node Types
  Person (100 instances)
    name: 100% complete [mandatory] types=[String]
    born: 60% complete [partial]   types=[Long]
```

When types are empty (CYPHER strategy — last resort only):
```
  Person (100 instances)
    name: 100% complete [mandatory] types=[]
    born: 60% complete [partial]   types=[]
```

### Why types=[] Still Happens

Only when **both** `apoc.meta.*` and `db.schema.*` are unavailable — an unusual
configuration. In practice, every Neo4j 4.x+ instance has `db.schema.*` built in,
so `observed_types = []` should only occur on very old or specially restricted
instances.

If you're seeing `observed_types = []` unexpectedly:

1. Check which strategy was selected:
   ```python
   inspector = Neo4jInspector()
   # Force SCHEMA to verify db.schema.* works on your instance:
   profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.SCHEMA).inspect(driver)
   ```

2. Verify `db.schema.nodeTypeProperties` is available:
   ```cypher
   SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'db.schema'
   ```

---

## Troubleshooting

### Profile shows types=[] unexpectedly

**Likely cause**: Neither APOC Core (`apoc.meta.*`) nor `db.schema.*` was detected.

**Verify**:
```cypher
-- Check APOC Core
SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'apoc.meta' RETURN count(name)

-- Check db.schema (built-in)
SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'db.schema' RETURN name
```

If `db.schema.nodeTypeProperties` is present, force SCHEMA:
```python
profile = Neo4jInspector(strategy=Neo4jInspectionStrategy.SCHEMA).inspect(driver)
```

### I have APOC but types are still empty

**Likely cause**: You have **APOC Extended** (`apoc5plus`) rather than APOC **Core**.
APOC Extended does not register `apoc.meta.*`.

The inspector now handles this automatically — it detects zero `apoc.meta.*`
procedures and falls through to SCHEMA. Verify:
```cypher
SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'apoc.meta' RETURN count(name)
-- If 0: APOC Extended only; inspector uses db.schema.* (SCHEMA strategy) instead
```

### Script fails with "Connection failed"

**Check**:
1. Is Neo4j running? `cypher-shell`
2. Correct credentials in `.env` or environment?
3. Correct URI, user, password?

### "Database is empty" warning

Use `06.01_profile_neo4j_example.ipynb` to test with auto-populated sample data.

### DeprecationWarning about use_apoc

Migrate to the new `strategy=` parameter:
```python
# Old (deprecated)
Neo4jInspector(use_apoc=False)
# New
Neo4jInspector(strategy=Neo4jInspectionStrategy.CYPHER)
```

---

## Technical Details

### Code References

- **Strategy enum**: `src/orthograph/backends/neo4j/inspector.py` — `Neo4jInspectionStrategy`
- **Auto-detection**: `src/orthograph/backends/neo4j/inspector.py` — `_detect_strategy()`
- **APOC queries**: `src/orthograph/backends/neo4j/queries.py` — `ApocNodePropertiesQuery`, `ApocRelPropertiesQuery`
- **db.schema queries**: `src/orthograph/backends/neo4j/queries.py` — `DbSchemaNodeTypesQuery`, `DbSchemaRelTypesQuery`
- **Cypher fallback**: `src/orthograph/backends/neo4j/queries.py` — `CypherNodePropertiesQuery`, `CypherRelPropertiesQuery`
- **Catalogue factories**: `src/orthograph/backends/neo4j/queries.py` — `build_apoc_catalogue()`, `build_schema_catalogue()`, `build_cypher_catalogue()`
- **ADR-033**: `.agentic/decisions/033-neo4j-db-schema-inspection-strategy.md` — full decision rationale

### db.schema.* Column Shape (Neo4j 5.12.0, confirmed E44.0)

```
nodeTypeProperties: nodeType (str, e.g. ':`Label`'), nodeLabels (list[str]),
  propertyName (str | None), propertyTypes (list[str] | None), mandatory (bool)
relTypeProperties:  relType  (str, e.g. ':`REL_TYPE`'),
  propertyName (str | None), propertyTypes (list[str] | None), mandatory (bool)
```

`propertyName` and `propertyTypes` are `None` for types that have no properties.

### Tools Provided

| Tool | Type | Purpose |
|------|------|---------|
| `06.01_profile_neo4j_example.ipynb` | Notebook | Learn + test with sample data |
| `06.02_profile_neo4j_custom.ipynb` | Notebook | Profile your database |
| `profile_script.py` | CLI | Quick command-line profiling |

---

## References

- **ADR-033**: [Three-Way Neo4j Inspection Strategy](../.agentic/decisions/033-neo4j-db-schema-inspection-strategy.md)
- **Technical note**: [Neo4j Property-Type Detection](../.agentic/notes/neo4j_property_type_detection.md)
- **Neo4j APOC**: https://neo4j.com/docs/apoc/current/
- **APOC Releases**: https://github.com/neo4j-contrib/neo4j-apoc-procedures/releases
- **Neo4j Graph Database**: https://neo4j.com/
