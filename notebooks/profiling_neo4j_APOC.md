# Profiling Neo4j with Orthograph - Complete Guide

Complete guide to profiling Neo4j databases and understanding APOC requirements.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Tool Comparison](#tool-comparison)
3. [APOC Guide](#apoc-guide)
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
- **Check APOC status** ⚠️
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

| Task | Tool | Setup | Speed | Output | APOC Check |
|------|------|-------|-------|--------|-----------|
| **Learn profiling** | `06.01_profile_neo4j_example.ipynb` | ⭐⭐ | Slow | Console | ✓ Yes |
| **Profile database** | `06.02_profile_neo4j_custom.ipynb` | ⭐ | Slow | Console | ✓ Yes |
| **Automate profiling** | `profile_script.py` | ⭐ | Fast | JSON | ✓ Yes |

---

## APOC Guide

### What is APOC?

**APOC** = **A**wesome **P**rocedures **O**n **C**ypher

APOC is Neo4j's library of advanced procedures for graph analysis. For profiling, it provides the `apoc.meta.*` procedures that can introspect property types.

### Why Do We Need APOC?

The **`observed_types`** field shows what data types each property contains (String, Long, Boolean, etc.).

**Without APOC**, this field shows `(APOC required)`:
```
Property    Completeness  Observed Types
name           100.0%    (APOC required)
year           100.0%    (APOC required)
```

**With APOC**, it shows actual types:
```
Property    Completeness  Observed Types
name           100.0%    String
year           100.0%    Long
```

### How It Works: Two Modes

Neo4j has **two modes** for property introspection:

#### Mode 1: With APOC ✓ (Recommended)
Uses: `apoc.meta.nodeTypeProperties()` and `apoc.meta.relTypeProperties()`
- **Detects**: String, Long, Double, Boolean, LocalDate, etc.
- **Requires**: APOC plugin installed
- **Performance**: Fast (uses metadata cache)
- **Code**: `src/orthograph/backends/neo4j/queries.py:160-166` (ApocNodePropertiesQuery)

#### Mode 2: Without APOC ✗ (Fallback)
Uses: Pure Cypher `MATCH (n:Label) UNWIND keys(n) AS key ...`
- **Detects**: Property names and completeness only
- **Requires**: Nothing (standard Cypher)
- **Performance**: Slower (scans all nodes)
- **Type detection**: ❌ Not possible → returns `[]`
- **Code**: `src/orthograph/backends/neo4j/queries.py:232-240` (CypherNodePropertiesQuery)

### What Still Works Without APOC

Even without APOC, you get:

✅ **Completeness**: 100% if property on all nodes
✅ **Property Names**: name, year, etc.
✅ **Cardinality**: Relationship degree distribution
✅ **Constraints**: Uniqueness, existence constraints
❌ **Observed Types**: String, Long, etc.

### APOC Detection Logic

All tools use `check_apoc_available()` from `utils.py`:

```python
def check_apoc_available(driver) -> bool:
    records, _, _ = driver.execute_query(
        "SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'apoc.meta' RETURN count(name) AS cnt"
    )
    return records[0]["cnt"] > 0 if records else False
```

**In notebooks and scripts**:
```python
if not check_apoc_available(driver):
    print("⚠️  WARNING: APOC not installed")
    print("   Property types will NOT be detected")
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

### Option B: Local Neo4j

```bash
# 1. Download APOC jar
cd ~/Downloads
wget https://github.com/neo4j-contrib/neo4j-apoc-procedures/releases/download/[VERSION]/apoc-[VERSION]-all.jar

# 2. Copy to plugins directory
cp apoc-*.jar $NEO4J_HOME/plugins/

# 3. Restart Neo4j
systemctl restart neo4j  # (or your restart method)

# 4. Verify installation
cypher-shell "SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'apoc.meta' RETURN count(name)"
# Should return: 1 (or higher)
```

### After Installing APOC

Run any tool and you'll see:
```
APOC: ✓ Available (property types will be detected)
```

And profiles will show actual types:
```
Property    Completeness  Observed Types
name           100.0%    String
year           100.0%    Long
```

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

3. Both notebooks and script will auto-load these

### Direct Credentials in Notebook

Edit Cell 1 of `06.02_profile_neo4j_custom.ipynb`:
```python
neo4j_uri = "bolt://your-server:7687"
neo4j_user = "your-user"
neo4j_password = "your-password"
```

### Environment Variables

Set as OS environment variables (highest priority):
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

Output:
```
Connecting to bolt://localhost:7687...
✓ Connected
Database: neo4j 5.12.0
  Nodes: 42
  Relationships: 87
  APOC: ✓ Available (property types will be detected)

Extracting profile...
✓ Profile extracted
  Node types: 3
  Relationship types: 2

... (profile display) ...

✓ Profile exported to scratch/profile_export.json
✓ Driver closed
```

### Example 2: Example Notebook

```bash
jupyter notebook
# Open: 06.01_profile_neo4j_example.ipynb
```

**Features**:
- Auto-populates sample data (Person, Movie, ACTED_IN)
- Checks APOC with warning if missing
- Extracts and displays profile
- Validates against model
- Shows full workflow

### Example 3: Custom Database

```bash
jupyter notebook
# Open: 06.02_profile_neo4j_custom.ipynb
```

**Features**:
- Connects to your database
- Checks APOC with warning if missing
- Extracts and displays profile (read-only)
- Exports JSON

### Example 4: Programmatic Usage

```python
from utils import (
    load_env,
    check_apoc_available,
    print_apoc_status,
    extract_profile,
    display_profile_summary,
    display_node_profiles,
    export_profile_json,
)
from neo4j import GraphDatabase

# Connect
driver = GraphDatabase.driver(
    load_env("NEO4J_URI", "bolt://localhost:7687"),
    auth=(
        load_env("NEO4J_USER", "neo4j"),
        load_env("NEO4J_PASSWORD", "password")
    )
)

# Check APOC
print_apoc_status(driver)

# Extract and display
profile = extract_profile(driver)
display_profile_summary(profile)
display_node_profiles(profile)

# Export
output_file = export_profile_json(profile)
print(f"Exported to {output_file}")

driver.close()
```

---

## Understanding observed_types

### The Problem

When you run the profile script/notebook, you might see:

```
Property                Completeness  Observed Types
title                        100.0%  (APOC required)
year                         100.0%  (APOC required)
name                         100.0%  (APOC required)
born                         100.0%  (APOC required)
```

The `(APOC required)` means the types couldn't be detected. **This is expected if APOC is not installed.**

### Why This Happens

**With APOC installed** → Uses `apoc.meta.nodeTypeProperties()`:
```python
class ApocNodePropertiesQuery:
    cypher = (
        "CALL apoc.meta.nodeTypeProperties({sample: -1})"
        " YIELD nodeType, nodeLabels, propertyName, propertyTypes, ..."
        f" WHERE '{label}' IN nodeLabels"
        " RETURN propertyName, propertyTypes, ..."  # ← Gets types
    )
```

**Without APOC** → Falls back to pure Cypher:
```python
class CypherNodePropertiesQuery:
    cypher_template = (
        "MATCH (n:`<<label>>`)"
        " WITH count(n) AS total"
        " MATCH (n:`<<label>>`)"
        " UNWIND keys(n) AS key"
        " WITH key, count(*) AS present, total"
        " RETURN key AS propertyName, [] AS propertyTypes, ..."  # ← Empty!
    )
```

### Solution

Install APOC (see [Installation](#installation) section above).

---

## Troubleshooting

### Profile shows "(APOC required)" for types

**Cause**: APOC is not installed

**Solution**: Install APOC (see [Installation](#installation) section)

### Script fails with "Connection failed"

**Cause**: Neo4j not running or wrong credentials

**Check**:
1. Is Neo4j running? `cypher-shell`
2. Correct credentials in `.env` or environment?
3. Correct URI, user, password?

### "Database is empty" warning

**Cause**: Database has no nodes

**Solution**:
- Populate database with your data, OR
- Use `06.01_profile_neo4j_example.ipynb` to test with sample data

### APOC detection fails

**Cause**: APOC installation issue

**Verify**:
```cypher
SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'apoc.meta'
```

Should return at least one row. If not, APOC isn't properly installed.

### APOC check shows "Not available" but I installed it

**Cause**: Neo4j hasn't been restarted after APOC installation

**Solution**:
1. Copy APOC jar to `$NEO4J_HOME/plugins/`
2. **Restart Neo4j**
3. Run profiling tool again

---

## Technical Details

### Code References

- **APOC detection**: `src/orthograph/backends/neo4j/inspector.py:113-124`
- **Query switching**: `src/orthograph/backends/neo4j/inspector.py:137`, `165`
- **APOC queries**: `src/orthograph/backends/neo4j/queries.py:142-214`
- **Cypher fallback**: `src/orthograph/backends/neo4j/queries.py:222-278`
- **TODO note**: `src/orthograph/backends/neo4j/queries.py:54-55` (ADR-015 B1)

### Utils Functions (in `utils.py`)

```python
load_env(key, default)              # Load from .env or env vars
check_apoc_available(driver)        # Returns bool
print_apoc_status(driver)           # Prints ✓ or ✗ with message
get_database_info(driver)           # Returns (name, version, nodes, rels)
extract_profile(driver)             # Returns GraphProfile
display_profile_summary(profile)    # Console output
display_node_profiles(profile)      # Console output
display_relationship_profiles(profile)  # Console output
display_constraints(profile)        # Console output
export_profile_json(profile)        # Saves to scratch/
```

### Tools Provided

| Tool | Type | Purpose |
|------|------|---------|
| `06.01_profile_neo4j_example.ipynb` | Notebook | Learn + test with sample data |
| `06.02_profile_neo4j_custom.ipynb` | Notebook | Profile your database |
| `profile_script.py` | CLI | Quick command-line profiling |
| `utils.py` | Module | Reusable functions |

### Output

All tools save profile JSON to: `notebooks/scratch/profile_export.json`

The `scratch/` folder:
- ✅ **Tracked in git** (via `.gitkeep`)
- ❌ **Output files not committed** (via `.gitignore`)
- 🔄 **Users regenerate outputs locally**

---

## References

- **Neo4j APOC**: https://neo4j.com/docs/apoc/current/
- **APOC Releases**: https://github.com/neo4j-contrib/neo4j-apoc-procedures/releases
- **Orthograph**: https://github.com/neo4j-labs/orthograph
- **Neo4j Graph Database**: https://neo4j.com/

---

## Summary

This guide provides everything needed to:
- ✅ Profile Neo4j databases using Orthograph
- ✅ Understand APOC's role in type detection
- ✅ Install and verify APOC
- ✅ Use the profiling tools (CLI, notebooks, programmatic)
- ✅ Troubleshoot common issues

All profiling tools check APOC availability and warn if it's missing. **See this guide if property types show "(APOC required)".**
