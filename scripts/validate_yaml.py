#!/usr/bin/env python3
"""Validate all YAML files in the project."""
import yaml
import sys

files = [
    "config.yaml",
    "config/prompts/trend_ranking.yaml",
    "config/prompts/compliance_check.yaml",
    "config/prompts/caption_generation.yaml",
]

for f in files:
    try:
        with open(f) as fh:
            yaml.safe_load(fh)
        print(f"{f}: OK")
    except Exception as e:
        print(f"{f}: ERROR - {e}")
        sys.exit(1)

print("All YAML files valid.")
