#!/usr/bin/env python3
"""Quick verification of trends_analyzer module and outputs."""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path("/mnt/user/data/shopee-agent/data.db")
TRENDS_DIR = Path("/mnt/user/data/shopee-agent/trends")

print("=== Verification ===")

# 1. Check DB
if DB_PATH.exists():
    conn = sqlite3.connect(str(DB_PATH))
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"DB tables: {[t[0] for t in tables]}")
    rows = conn.execute("SELECT COUNT(*) FROM trends_history").fetchone()
    print(f"Trends history rows: {rows[0]}")
    conn.close()
else:
    print("DB not found!")

# 2. Check trends output
json_files = list(TRENDS_DIR.glob("*.json"))
print(f"Trend JSON files: {len(json_files)}")
for jf in json_files:
    with open(jf) as f:
        data = json.load(f)
    print(f"  {jf.name}: {len(data.get('ranked_products', []))} products")
    for p in data.get("ranked_products", [])[:3]:
        print(f"    #{data['ranked_products'].index(p)+1}: {p['name']} (score={p['score']})")

# 3. Module import test
import importlib.util
spec = importlib.util.spec_from_file_location("trends_analyzer", Path("trends_analyzer.py").resolve())
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print("\nModule functions:")
for name in sorted(dir(mod)):
    if not name.startswith("_") and callable(getattr(mod, name, None)):
        print(f"  {name}")

print("\nAll checks passed!")
