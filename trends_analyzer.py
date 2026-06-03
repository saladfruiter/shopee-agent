#!/usr/bin/env python3
"""
Trends Analyzer — Etapa 1 do Pipeline Shopee Videos

Detecta produtos em alta no nicho tech + gadgets usando DuckDuckGo Search.
Mais simples e confiável que Google Trends (sem rate limit).

Saída: {output_dir}/{YYYY-MM-DD}.json com produtos ranqueados.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from duckduckgo_search import DDGS

logger = logging.getLogger("trends_analyzer")

BASE_DIR = Path(__file__).resolve().parent


def load_config(path: Path = BASE_DIR / "config.yaml") -> dict:
    """Load YAML config."""
    with open(path) as f:
        return yaml.safe_load(f) or {}


def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize SQLite database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS product_engagement (
            product_name TEXT PRIMARY KEY,
            total_views INTEGER DEFAULT 0,
            total_clicks INTEGER DEFAULT 0,
            total_conversions INTEGER DEFAULT 0,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trends_history (
            date TEXT,
            product_name TEXT,
            rank INTEGER,
            score REAL,
            PRIMARY KEY (date, product_name)
        )
    """)
    conn.commit()
    return conn


def fetch_search_volume(keywords: list[str], geo: str = "br-pt") -> dict[str, int]:
    """
    Use DuckDuckGo text search to estimate relative interest.
    Returns {keyword: result_count}.
    """
    scores = {}
    with DDGS() as ddgs:
        for kw in keywords:
            try:
                results = list(ddgs.text(kw, region=geo, max_results=10))
                score = len(results)
                scores[kw] = score
                logger.debug("  %s: %d results", kw, score)
            except Exception as e:
                logger.warning("DuckDuckGo search failed for '%s': %s", kw, e)
                scores[kw] = 0
            # Polite delay
            time.sleep(2 + random.uniform(1, 3))
    return scores


def normalize_text(text: str) -> str:
    """Lowercase, strip."""
    return text.lower().strip()


def filter_duplicates(keywords: list[str]) -> list[str]:
    """Remove semantically similar keywords (keep first)."""
    seen = set()
    unique = []
    for kw in keywords:
        norm = normalize_text(kw)
        if norm not in seen:
            seen.add(norm)
            unique.append(kw)
    return unique


def compute_ranked_products(
    keywords: list[str],
    search_scores: dict[str, int],
    db_conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Rank keywords by search score."""
    # Normalize scores to 0-100
    max_score = max(search_scores.values()) if search_scores else 1
    if max_score == 0:
        max_score = 1

    ranked = []
    for kw in keywords:
        raw = search_scores.get(kw, 0)
        normalized = round((raw / max_score) * 100, 2)

        ranked.append({
            "name": kw,
            "score": normalized,
            "components": {
                "search_score": normalized,
                "raw_search_results": raw,
            },
            "sources": {
                "duckduckgo_search": raw > 0,
            },
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


def run_trends_analysis(
    config: dict | None = None,
    config_path: Path = BASE_DIR / "config.yaml",
    output_dir: Path | None = None,
    use_llm: bool = True,
) -> dict:
    """
    Execute the full trends analysis pipeline.

    Args:
        config: Pre-loaded config dict (preferred when called from main.py).
        config_path: Path to config.yaml (used if config is None).
        output_dir: Directory to save output files.
        use_llm: Whether to use LLM refinement (currently no-op, reserved).

    Returns the analysis result dict (also saved to output_dir/YYYY-MM-DD.json).
    """
    if config is None:
        logger.info("Loading config from %s", config_path)
        config = load_config(config_path)
    else:
        logger.info("Using pre-loaded config")

    storage_root = Path(config.get("project", {}).get(
        "storage_root", str(BASE_DIR)
    ))

    if output_dir is None:
        output_dir = storage_root / "trends"
    output_dir.mkdir(parents=True, exist_ok=True)

    db_path = storage_root / "data.db"
    db_conn = init_db(db_path)

    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = output_dir / f"{date_str}.json"

    # Step 1: Build keyword list
    niche = config.get("niche", {})
    all_keywords = niche.get("primary", []) + niche.get("secondary", [])
    keywords = filter_duplicates(all_keywords)
    logger.info("Analyzing %d niche keywords", len(keywords))

    # Step 2: DuckDuckGo search volume
    logger.info("Fetching search data via DuckDuckGo...")
    search_scores = fetch_search_volume(keywords, geo="br-pt")

    # Step 3: Ranking
    logger.info("Computing ranking...")
    ranked = compute_ranked_products(keywords, search_scores, db_conn)

    max_products = config.get("trending", {}).get("max_products_per_day", 10)
    final_ranked = ranked[:max_products]

    # Build output
    result = {
        "date": date_str,
        "generated_at": datetime.now().isoformat(),
        "method": "duckduckgo_search",
        "total_keywords_analyzed": len(keywords),
        "ranked_products": final_ranked,
    }

    # Save to JSON
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    logger.info("Saved trends to %s", output_path)

    # Save to DB
    for idx, product in enumerate(final_ranked):
        try:
            db_conn.execute(
                "INSERT OR REPLACE INTO trends_history "
                "(date, product_name, rank, score) VALUES (?, ?, ?, ?)",
                (date_str, product["name"], idx + 1, product["score"])
            )
        except Exception as e:
            logger.warning("Failed to save trends_history: %s", e)
    db_conn.commit()
    db_conn.close()

    logger.info("Trends analysis complete. Top %d:", min(3, len(final_ranked)))
    for i, p in enumerate(final_ranked[:3]):
        logger.info("  #%d: %s (score=%.2f)", i + 1, p["name"], p["score"])

    return result


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Shopee Videos — Trends Analyzer")
    parser.add_argument("--config", type=Path, default=BASE_DIR / "config.yaml")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        config = load_config(args.config)
        niche = config.get("niche", {})
        keywords = niche.get("primary", []) + niche.get("secondary", [])
        print(f"Keywords: {len(keywords)}")
        print(f"Max products/day: {config.get('trending', {}).get('max_products_per_day', 10)}")
    else:
        result = run_trends_analysis(
            config_path=args.config,
            output_dir=args.output_dir,
            use_llm=not args.no_llm,
        )
        print(f"\nAnalysis complete. {len(result['ranked_products'])} products ranked.")
        print(f"Output: {args.output_dir or Path('trends')}")
