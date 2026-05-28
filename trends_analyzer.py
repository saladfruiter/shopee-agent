#!/usr/bin/env python3
"""
Trends Analyzer — Etapa 1 do Pipeline Shopee Videos

Detecta produtos em alta no nicho tech + gadgets adjacentes combinando:
1. Google Trends (pytrends) — EUA e BR
2. RSS feeds de blogs de tech
3. Amazon Movers & Shakers scraper
4. Feedback loop de engajamento (data.db)

Ranking ponderado: Buscas 40% + Social 30% + Vendas 30%
Saída: trends/YYYY-MM-DD.json com até 10 produtos ranqueados.
"""

import json
import logging
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import feedparser
import requests
import yaml
from pytrends.request import TrendReq

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.yaml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("trends_analyzer")

# Retry defaults
MAX_RETRIES = 3
BASE_DELAY = 2
BACKOFF_MULTIPLIER = 2


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Load YAML config with validation."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Validate weights sum to ~1.0
    weights = cfg.get("trending", {}).get("weights", {})
    total = sum(weights.values())
    if not 0.99 <= total <= 1.01:
        logger.warning("Trending weights sum to %.2f (expected ~1.0)", total)
    return cfg


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def retry(func, max_attempts: int = MAX_RETRIES, base_delay: float = BASE_DELAY,
          backoff: float = BACKOFF_MULTIPLIER, label: str = "operation"):
    """Retry a callable with exponential backoff."""
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            logger.warning("%s attempt %d/%d failed: %s", label, attempt, max_attempts, exc)
            if attempt < max_attempts:
                delay = base_delay * (backoff ** (attempt - 1))
                time.sleep(delay)
    logger.error("%s failed after %d attempts", label, max_attempts)
    return None


# ---------------------------------------------------------------------------
# 1. Google Trends (pytrends)
# ---------------------------------------------------------------------------

def fetch_google_trends(keywords: list[str], geo: str = "US",
                        timeframe: str = "today 1-m") -> dict[str, float]:
    """
    Fetch Google Trends interest for a list of keywords.
    Returns {keyword: normalized_interest_0_to_100}.
    """
    scores: dict[str, float] = {}
    try:
        pytrends = TrendReq(hl="en-US", tz=360)
        # pytrends only allows 5 keywords per request
        for i in range(0, len(keywords), 5):
            batch = keywords[i:i+5]
            pytrends.build_payload(batch, cat=0, timeframe=timeframe, geo=geo)
            try:
                data = pytrends.interest_over_time()
                if not data.empty:
                    for kw in batch:
                        if kw in data.columns:
                            scores[kw] = float(data[kw].mean())
            except Exception as e:
                logger.warning("pytrends interest_over_time failed for batch %s: %s", batch, e)
            time.sleep(5)  # Rate limit courtesy
    except Exception as e:
        logger.error("Google Trends fetch failed (geo=%s): %s", geo, e)
    return scores


def get_trends_combined(keywords: list[str]) -> dict[str, float]:
    """
    Combined Google Trends score: average of US and BR interest.
    Returns {keyword: combined_score_0_to_100}.
    """
    def _fetch_us():
        return fetch_google_trends(keywords, geo="US")
    def _fetch_br():
        return fetch_google_trends(keywords, geo="BR")

    us_scores = retry(_fetch_us, label="Google Trends US") or {}
    br_scores = retry(_fetch_br, label="Google Trends BR") or {}

    combined: dict[str, float] = {}
    all_keys = set(us_scores) | set(br_scores)
    for kw in all_keys:
        us = us_scores.get(kw, 0)
        br = br_scores.get(kw, 0)
        # Weighted average: BR is target market, slightly higher weight
        combined[kw] = round(us * 0.4 + br * 0.6, 2)
    return combined


# ---------------------------------------------------------------------------
# 2. RSS Feed Analysis (Social/Blog mentions)
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^a-záàãâéèêíóòôõúüç0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_rss_mentions(keywords: list[str], feeds: list[str]) -> dict[str, int]:
    """
    Count how many times each keyword appears across RSS feeds in last 7 days.
    Returns {keyword: mention_count}.
    """
    cutoff = datetime.now() - timedelta(days=7)
    mentions: dict[str, int] = defaultdict(int)
    normalized_keywords = [normalize_text(kw) for kw in keywords]

    for feed_url in feeds:
        def _fetch():
            resp = requests.get(feed_url, timeout=15)
            resp.raise_for_status()
            return feedparser.parse(resp.content)

        feed = retry(_fetch, label=f"RSS {feed_url}")
        if not feed or not feed.entries:
            logger.warning("No entries from RSS: %s", feed_url)
            continue

        for entry in feed.entries:
            # Check entry date
            entry_date = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                entry_date = datetime(*entry.published_parsed[:6])
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                entry_date = datetime(*entry.updated_parsed[:6])

            if entry_date and entry_date < cutoff:
                continue

            # Search in title + summary
            search_text = normalize_text(
                (entry.get("title", "") or "") + " " +
                (entry.get("summary", "") or "")
            )

            for idx, kw_normalized in enumerate(normalized_keywords):
                # Match whole word or phrase
                if kw_normalized in search_text:
                    mentions[keywords[idx]] += 1

    return dict(mentions)


# ---------------------------------------------------------------------------
# 3. Amazon Movers & Shakers Scraper
# ---------------------------------------------------------------------------

def fetch_amazon_movers_shakers() -> list[dict[str, Any]]:
    """
    Scrape Amazon Movers & Shakers for electronics/tech products.
    Returns list of {name, category, rank_change, url}.
    Uses simple HTTP scraping with desktop User-Agent.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    url = "https://www.amazon.com/gp/movers-and-shakers/electronics"

    def _fetch():
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.text

    html = retry(_fetch, label="Amazon Movers & Shakers")
    products = []

    if not html:
        logger.warning("Amazon scrape returned empty")
        return products

    # Extract product names from the page
    # Amazon's HTML structure changes; use robust regex patterns
    name_pattern = re.compile(
        r'class="[^"]*a-link-normal[^"]*"[^>]*>\s*'
        r'<span[^>]*class="[^"]*a-size-base[^"]*"[^>]*>\s*'
        r'<!\[CDATA\[\s*\n?\s*([^<]+?)\s*\n?\s*\]\]>',
        re.DOTALL,
    )
    # Fallback: find any span with product-like text near "movers" context
    fallback_pattern = re.compile(
        r'<span[^>]*class="[^"]*(?:p13n-sc-truncate|a-size-base)[^"]*"[^>]*>'
        r'\s*<!\[CDATA\[\s*(.*?)\s*\]\]>',
        re.DOTALL,
    )

    for match in name_pattern.finditer(html):
        name = match.group(1).strip()
        if name and len(name) > 2:
            products.append({
                "name": name,
                "category": "electronics",
                "source": "amazon_movers_shakers",
            })

    for match in fallback_pattern.finditer(html):
        name = match.group(1).strip()
        if name and len(name) > 2:
            products.append({
                "name": name,
                "category": "electronics",
                "source": "amazon_movers_shakers",
            })

    # Deduplicate
    seen = set()
    unique = []
    for p in products:
        key = p["name"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)

    logger.info("Amazon Movers & Shakers: found %d products", len(unique))
    return unique


# ---------------------------------------------------------------------------
# 4. Niche Filter
# ---------------------------------------------------------------------------

def matches_niche(text: str, config: dict) -> bool:
    """Check if text matches tech + gadgets niche keywords."""
    text_lower = normalize_text(text)
    primary = [normalize_text(k) for k in config.get("niche", {}).get("primary", [])]
    secondary = [normalize_text(k) for k in config.get("niche", {}).get("secondary", [])]

    # Primary keywords get higher priority
    for kw in primary:
        if kw in text_lower:
            return True

    for kw in secondary:
        if kw in text_lower:
            return True

    return False


def filter_niche(candidates: list[str], config: dict) -> list[str]:
    """Filter candidate product names to only those matching the niche."""
    return [c for c in candidates if matches_niche(c, config)]


# ---------------------------------------------------------------------------
# 5. Feedback Loop (data.db)
# ---------------------------------------------------------------------------

def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize SQLite database with engagement table if not exists."""
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


def get_engagement_boost(conn: sqlite3.Connection, product: str,
                         multiplier: float = 1.2) -> float:
    """
    Get engagement boost factor for a product from data.db.
    Returns multiplier (1.0 = no boost, higher = more engagement).
    """
    try:
        cursor = conn.execute(
            "SELECT total_views, total_clicks, total_conversions "
            "FROM product_engagement WHERE product_name = ?",
            (product,)
        )
        row = cursor.fetchone()
        if row:
            views, clicks, conversions = row
            # Simple engagement score: weighted sum
            engagement = views * 0.1 + clicks * 0.5 + conversions * 2.0
            # Normalize: cap at 10x multiplier
            boost = 1.0 + min(engagement / 100.0, multiplier - 1.0)
            return round(boost, 3)
    except Exception as e:
        logger.warning("Failed to read engagement for '%s': %s", product, e)
    return 1.0


# ---------------------------------------------------------------------------
# 6. Weighted Ranking
# ---------------------------------------------------------------------------

def compute_ranked_products(
    candidates: list[str],
    trends_scores: dict[str, float],
    social_mentions: dict[str, int],
    amazon_products: list[dict],
    config: dict,
    db_conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """
    Compute weighted ranking for candidate products.

    Score = (search_score * w_search) + (social_score * w_social) + (sales_score * w_sales)
    Then apply feedback multiplier from data.db.
    """
    weights = config.get("trending", {}).get("weights", {})
    w_search = weights.get("search", 0.4)
    w_social = weights.get("social", 0.3)
    w_sales = weights.get("sales", 0.3)

    # Normalize social mentions to 0-100
    max_mentions = max(social_mentions.values()) if social_mentions else 1
    social_normalized = {
        kw: round((count / max_mentions) * 100, 2)
        for kw, count in social_mentions.items()
    }

    # Build amazon name set for sales scoring
    amazon_names = set()
    for p in amazon_products:
        amazon_names.add(normalize_text(p["name"]))

    ranked = []
    for product in candidates:
        norm_product = normalize_text(product)

        # Search score (0-100)
        search_score = trends_scores.get(product, 0)

        # Social score (0-100)
        social_score = social_normalized.get(product, 0)

        # Sales score: 100 if on Amazon movers, 0 otherwise
        sales_score = 100.0 if norm_product in amazon_names else 0.0

        # Raw weighted score
        raw_score = (
            search_score * w_search +
            social_score * w_social +
            sales_score * w_sales
        )

        # Feedback multiplier
        feedback_mult = 1.0
        if db_conn:
            feedback_mult = get_engagement_boost(
                db_conn, product,
                config.get("trending", {}).get("feedback_multiplier", 1.2)
            )

        final_score = round(raw_score * feedback_mult, 2)

        ranked.append({
            "name": product,
            "score": final_score,
            "components": {
                "search_score": round(search_score, 2),
                "social_score": round(social_score, 2),
                "sales_score": round(sales_score, 2),
                "feedback_multiplier": feedback_mult,
            },
            "sources": {
                "google_trends": search_score > 0,
                "rss_mentioned": social_score > 0,
                "amazon_movers": sales_score > 0,
            },
        })

    # Sort by score descending
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


# ---------------------------------------------------------------------------
# 7. LLM-based Structured Ranking (optional enhancement)
# ---------------------------------------------------------------------------

def llm_refine_ranking(
    ranked: list[dict],
    max_products: int = 10,
) -> list[dict]:
    """
    Use LLM (qwen3.5:7b via opencode-go) to refine ranking with
    cross-market relevance analysis (US -> BR transfer potential).

    Falls back gracefully if LLM is unavailable.
    """
    if not ranked:
        return ranked

    # Prepare prompt for LLM
    top_candidates = ranked[:max_products * 2]  # Give LLM more to work with
    candidate_str = json.dumps([
        {"name": p["name"], "score": p["score"], "sources": p["sources"]}
        for p in top_candidates
    ], indent=2, ensure_ascii=False)

    prompt = (
        f"You are an expert at identifying trending tech products for the Brazilian market.\n"
        f"Given these candidates with their trend scores, rank the top {max_products} "
        f"products most likely to sell well on Shopee Brazil.\n\n"
        f"Consider:\n"
        f"- US-to-BR trend transfer potential\n"
        f"- Price accessibility (under R$200 is ideal)\n"
        f"- Visual appeal for short-form video\n\n"
        f"Candidates:\n{candidate_str}\n\n"
        f"Respond with a JSON array of exactly {max_products} product names in order, "
        f"highest potential first. Only include names that appear in the candidates list.\n"
        f"Format: [\"product1\", \"product2\", ...]"
    )

    try:
        # Try calling via opencode-go
        result = call_opencode(prompt)
        if result:
            # Parse LLM response
            llm_order = parse_llm_ranking(result, [p["name"] for p in ranked])
            if llm_order:
                # Reorder based on LLM output while preserving scores
                name_to_item = {p["name"]: p for p in ranked}
                reordered = []
                for name in llm_order:
                    if name in name_to_item:
                        reordered.append(name_to_item[name])
                # Add remaining items
                for p in ranked:
                    if p not in reordered:
                        reordered.append(p)
                return reordered[:max_products]
    except Exception as e:
        logger.warning("LLM refinement failed, using raw ranking: %s", e)

    # Fallback: just return top N by raw score
    return ranked[:max_products]


def call_opencode(prompt: str) -> str | None:
    """Call opencode-go with qwen3.5:7b model."""
    import subprocess
    try:
        result = subprocess.run(
            ["opencode-go", "--model", "qwen3.5:7b", "--prompt", prompt],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        logger.debug("opencode-go not found, skipping LLM refinement")
    except subprocess.TimeoutExpired:
        logger.warning("LLM call timed out")
    return None


def parse_llm_ranking(llm_output: str, valid_names: list[str]) -> list[str]:
    """Extract product names from LLM JSON response."""
    try:
        # Try to find JSON array in the output
        match = re.search(r'\[.*?\]', llm_output, re.DOTALL)
        if match:
            names = json.loads(match.group())
            valid_lower = [n.lower() for n in valid_names]
            result = []
            for name in names:
                # Match case-insensitively
                for vn in valid_names:
                    if vn.lower() == name.lower() and vn not in result:
                        result.append(vn)
                        break
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return []


# ---------------------------------------------------------------------------
# 8. Main Pipeline
# ---------------------------------------------------------------------------

def build_keyword_list(config: dict) -> list[str]:
    """Build a deduplicated list of niche keywords for trend analysis."""
    niche = config.get("niche", {})
    all_keywords = niche.get("primary", []) + niche.get("secondary", [])
    # Deduplicate (case-insensitive)
    seen = set()
    unique = []
    for kw in all_keywords:
        lower = kw.lower()
        if lower not in seen:
            seen.add(lower)
            unique.append(kw)
    return unique


def run_trends_analysis(config_path: Path = CONFIG_PATH,
                        output_dir: Path | None = None,
                        use_llm: bool = True) -> dict:
    """
    Execute the full trends analysis pipeline.

    Returns the analysis result dict (also saved to trends/YYYY-MM-DD.json).
    """
    logger.info("Loading config from %s", config_path)
    config = load_config(config_path)

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
    keywords = build_keyword_list(config)
    logger.info("Analyzing %d niche keywords", len(keywords))

    # Step 2: Google Trends
    logger.info("Fetching Google Trends (US + BR)...")
    trends_scores = get_trends_combined(keywords)

    # Step 3: RSS Feed Analysis
    logger.info("Scanning RSS feeds for mentions...")
    rss_feeds = config.get("rss_feeds", [])
    social_mentions = fetch_rss_mentions(keywords, rss_feeds)

    # Step 4: Amazon Movers & Shakers
    logger.info("Scraping Amazon Movers & Shakers...")
    amazon_products = fetch_amazon_movers_shakers()

    # Step 5: Combine all candidate names
    all_candidates = list(set(keywords))
    for p in amazon_products:
        name = p.get("name", "")
        if name and matches_niche(name, config):
            all_candidates.append(name)

    # Deduplicate candidates
    seen = set()
    unique_candidates = []
    for c in all_candidates:
        lower = normalize_text(c)
        if lower not in seen and lower:
            seen.add(lower)
            unique_candidates.append(c)

    # Niche filter
    niche_filtered = filter_niche(unique_candidates, config)
    logger.info("Candidates after niche filter: %d", len(niche_filtered))

    # Step 6: Weighted ranking
    logger.info("Computing weighted ranking...")
    ranked = compute_ranked_products(
        niche_filtered, trends_scores, social_mentions,
        amazon_products, config, db_conn
    )

    # Step 7: LLM refinement (optional)
    max_products = config.get("trending", {}).get("max_products_per_day", 10)
    if use_llm:
        logger.info("Refining ranking with LLM...")
        final_ranked = llm_refine_ranking(ranked, max_products)
    else:
        final_ranked = ranked[:max_products]

    # Step 8: Build output
    result = {
        "date": date_str,
        "generated_at": datetime.now().isoformat(),
        "config": {
            "weights": config.get("trending", {}).get("weights", {}),
            "niche_keywords": {
                "primary": config.get("niche", {}).get("primary", []),
                "secondary": config.get("niche", {}).get("secondary", []),
            },
        },
        "total_candidates_analyzed": len(unique_candidates),
        "total_after_niche_filter": len(niche_filtered),
        "trends_summary": {
            "google_trends_keywords": len(trends_scores),
            "rss_feeds_scanned": len(rss_feeds),
            "rss_total_mentions": sum(social_mentions.values()),
            "amazon_products_found": len(amazon_products),
        },
        "ranked_products": final_ranked,
    }

    # Save to JSON
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    logger.info("Saved trends to %s", output_path)

    # Also save to trends_history in DB
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

    logger.info("Trends analysis complete. Top 3:")
    for p in final_ranked[:3]:
        logger.info("  #%d: %s (score=%.2f)", final_ranked.index(p) + 1, p["name"], p["score"])

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Shopee Videos — Trends Analyzer")
    parser.add_argument(
        "--config", type=Path, default=CONFIG_PATH,
        help="Path to config.yaml"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Override output directory"
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Skip LLM refinement step"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without saving"
    )
    args = parser.parse_args()

    if args.dry_run:
        logger.info("=== DRY RUN MODE ===")
        config = load_config(args.config)
        keywords = build_keyword_list(config)
        print(f"Config: {args.config}")
        print(f"Keywords ({len(keywords)}): {', '.join(keywords[:10])}...")
        print(f"Weights: {config.get('trending', {}).get('weights', {})}")
        print(f"Max products/day: {config.get('trending', {}).get('max_products_per_day', 10)}")
        print(f"RSS feeds: {len(config.get('rss_feeds', []))}")
        print("Dry run complete — no data fetched or saved.")
    else:
        result = run_trends_analysis(
            config_path=args.config,
            output_dir=args.output_dir,
            use_llm=not args.no_llm,
        )
        print(f"\nAnalysis complete. {len(result['ranked_products'])} products ranked.")
        print(f"Output: {Path(__file__).parent / 'trends' / f'{datetime.now().strftime('%Y-%m-%d')}.json'}")
