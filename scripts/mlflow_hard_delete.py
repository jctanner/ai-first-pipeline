#!/usr/bin/env python3
"""Hard-delete all MLflow data from the SQLite backend.

Designed to run inside the MLflow pod via ``kubectl exec`` or the dashboard's
``/api/mlflow/hard-clear`` endpoint.  Schema-aware: discovers foreign-key
relationships from ``sqlite_master`` and walks them transitively so grandchild+
tables are covered.  Deletes in topological (child-before-parent) order.

Outputs a single JSON object to stdout with counts and any errors.
Exits non-zero on any DB or artifact error so the caller can detect partial
failures.
"""

import json
import os
import shutil
import sqlite3
import sys
from collections import defaultdict

DB = "/data/mlflow.db"
ARTIFACT_DIR = "/data/artifacts"

if not os.path.exists(DB):
    print(json.dumps({"error": f"{DB} not found"}))
    sys.exit(1)

conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys = ON")

# --- discover tables and FK graph ---
tables = {r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
).fetchall()}

children = defaultdict(set)
parents = defaultdict(set)

for tbl in tables:
    for fk in conn.execute(f"PRAGMA foreign_key_list([{tbl}])").fetchall():
        parent = fk[2]
        children[parent].add(tbl)
        parents[tbl].add(parent)

# --- topological sort: children before parents ---
order = []
visited = set()


def visit(t):
    if t in visited:
        return
    visited.add(t)
    for child in children.get(t, set()):
        if child in tables:
            visit(child)
    order.append(t)


for t in tables:
    visit(t)

# --- build delete predicates transitively ---
# Each entry maps a table name to a SQL WHERE clause (with a single ? for
# experiment_id) that scopes rows to a given experiment.  Seed tables have
# experiment_id directly; child tables inherit the predicate through FK
# subqueries, walking as many hops as needed.

predicate_map = {}

for tbl in order:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info([{tbl}])").fetchall()}
    if "experiment_id" in cols:
        predicate_map[tbl] = "[experiment_id] = ?"

changed = True
while changed:
    changed = False
    for tbl in order:
        if tbl in predicate_map:
            continue
        for fk in conn.execute(f"PRAGMA foreign_key_list([{tbl}])").fetchall():
            parent_tbl = fk[2]
            fk_from = fk[3]
            fk_to = fk[4]
            if parent_tbl in predicate_map:
                predicate_map[tbl] = (
                    f"[{fk_from}] IN "
                    f"(SELECT [{fk_to}] FROM [{parent_tbl}] WHERE {predicate_map[parent_tbl]})"
                )
                changed = True
                break

result = {
    "experiments_deleted": 0,
    "default_experiment_cleared": False,
    "runs_deleted": 0,
    "traces_deleted": 0,
    "spans_deleted": 0,
    "artifacts_deleted": 0,
    "tables_cleared": [],
    "db_errors": [],
    "artifact_errors": [],
}

# --- get all experiment IDs ---
try:
    all_exps = conn.execute("SELECT experiment_id FROM experiments").fetchall()
except Exception as e:
    result["db_errors"].append(f"query experiments: {e}")
    print(json.dumps(result))
    sys.exit(1)

exp_ids = [r[0] for r in all_exps]

# --- delete data for each experiment ---
for exp_id in exp_ids:
    is_default = str(exp_id) == "0"
    for tbl in order:
        if tbl == "experiments":
            continue
        if tbl not in predicate_map:
            continue
        try:
            cur = conn.execute(
                f"DELETE FROM [{tbl}] WHERE {predicate_map[tbl]}", (exp_id,)
            )
            deleted = cur.rowcount
            if deleted > 0:
                if tbl not in result["tables_cleared"]:
                    result["tables_cleared"].append(tbl)
                if "span" in tbl.lower():
                    result["spans_deleted"] += deleted
                elif "trace" in tbl.lower():
                    result["traces_deleted"] += deleted
                elif "run" in tbl.lower():
                    result["runs_deleted"] += deleted
        except Exception as e:
            result["db_errors"].append(f"delete from {tbl} exp {exp_id}: {e}")

    if not is_default:
        try:
            conn.execute("DELETE FROM experiments WHERE experiment_id = ?", (exp_id,))
            result["experiments_deleted"] += 1
        except Exception as e:
            result["db_errors"].append(f"delete experiment {exp_id}: {e}")
    else:
        result["default_experiment_cleared"] = True

# --- bail on any DB errors ---
if result["db_errors"]:
    conn.rollback()
    print(json.dumps(result))
    sys.exit(1)

# --- FK integrity check ---
violations = conn.execute("PRAGMA foreign_key_check").fetchall()
if violations:
    result["db_errors"].append(f"FK violations after delete: {violations}")
    conn.rollback()
    print(json.dumps(result))
    sys.exit(1)

conn.commit()
conn.close()

# --- clear artifact files (after DB commit) ---
if os.path.isdir(ARTIFACT_DIR):
    count = 0
    for child in os.listdir(ARTIFACT_DIR):
        p = os.path.join(ARTIFACT_DIR, child)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.unlink(p)
            count += 1
        except Exception as e:
            result["artifact_errors"].append(f"{p}: {e}")
    result["artifacts_deleted"] = count

print(json.dumps(result))
if result["artifact_errors"]:
    sys.exit(1)
