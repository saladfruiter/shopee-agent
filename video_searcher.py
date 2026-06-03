#!/usr/bin/env python3
"""
Video Search Module — Etapa 2 do Pipeline Shopee Videos

Busca videos com licença comercial (Pexels API) para os produtos trending.
Salva URLs e metadata em raw_videos/search_results.json.
"""

from __future__ import annotations

import json
import logging
import os
import time
import random
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent / ".env")

logger = logging.getLogger("video_searcher")

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
PEXELS_API_URL = "https://api.pexels.com/videos/search"


@dataclass
class VideoCandidate:
    url: str
    source: str
    title: str = ""
    duration: float = 0
    width: int = 0
    height: int = 0
    thumbnail: str = ""
    video_files: list[dict] = None

    def __post_init__(self):
        if self.video_files is None:
            self.video_files = []

    def to_dict(self) -> dict:
        return asdict(self)


def search_pexels(query: str, max_results: int = 5) -> list[VideoCandidate]:
    """Search Pexels for free commercial license videos."""
    if not PEXELS_API_KEY:
        logger.warning("PEXELS_API_KEY not set. Set env var to enable video search.")
        return []

    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "per_page": max_results, "orientation": "portrait"}

    candidates = []
    try:
        resp = requests.get(PEXELS_API_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for video in data.get("videos", []):
            # Get best quality file
            video_files = video.get("video_files", [])
            best = None
            for f in video_files:
                if f.get("quality") == "hd" or f.get("quality") == "sd":
                    best = f
                    break
            if not best and video_files:
                best = video_files[0]

            if best:
                candidates.append(VideoCandidate(
                    url=best.get("link", ""),
                    source="pexels",
                    title=video.get("url", "").split("/")[-1] or query,
                    duration=video.get("duration", 0),
                    width=best.get("width", 0),
                    height=best.get("height", 0),
                    thumbnail=video.get("image", ""),
                    video_files=video_files,
                ))
    except Exception as e:
        logger.warning("Pexels search failed for '%s': %s", query, e)

    return candidates


def search_videos_for_products(
    products: list[dict],
    output_dir: Path,
    max_videos_per_product: int = 1,
) -> dict:
    """
    Search videos for each trending product.

    Args:
        products: List from trends_analyzer ranked_products
        output_dir: Directory to save search results
        max_videos_per_product: Max videos to find per product

    Returns:
        Dict with search results per product
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if not PEXELS_API_KEY:
        logger.warning(
            "Skipping video search: PEXELS_API_KEY not set.\n"
            "Get a free key at https://www.pexels.com/api/ and set:\n"
            "  export PEXELS_API_KEY='your_key_here'\n"
            "  # or add to .env file"
        )
        result = {
            "status": "skipped",
            "reason": "PEXELS_API_KEY not set",
            "products": [],
        }
        return result

    results = []
    for product in products:
        name = product.get("name", "")
        logger.info("Searching videos for: %s", name)

        # Search in English and Portuguese
        queries = [name, f"{name} product", f"{name} tech"]
        all_videos = []

        for query in queries:
            videos = search_pexels(query, max_results=max_videos_per_product)
            all_videos.extend(videos)
            time.sleep(0.5 + random.uniform(0.2, 1))

            if len(all_videos) >= max_videos_per_product:
                break

        # Deduplicate by URL
        seen = set()
        unique = []
        for v in all_videos:
            if v.url not in seen:
                seen.add(v.url)
                unique.append(v.to_dict())

        product_result = {
            "product_name": name,
            "product_score": product.get("score", 0),
            "videos": unique[:max_videos_per_product],
            "videos_found": len(unique[:max_videos_per_product]),
        }
        results.append(product_result)
        logger.info("  Found %d video(s) for '%s'", product_result["videos_found"], name)

    # Save results
    search_results = {
        "products": results,
        "total_products": len(results),
        "products_with_videos": sum(1 for p in results if p["videos"]),
        "total_videos": sum(p["videos_found"] for p in results),
    }

    results_path = output_dir / "search_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(search_results, f, indent=2, ensure_ascii=False)
    logger.info("Saved search results to %s", results_path)

    return search_results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Test with mock products
    mock_products = [
        {"name": "smartphone", "score": 90},
        {"name": "headphones", "score": 70},
    ]
    result = search_videos_for_products(
        products=mock_products,
        output_dir=Path("/tmp/pexels_test"),
        max_videos_per_product=2,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
