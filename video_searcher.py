#!/usr/bin/env python3
"""
Video Search Module — Etapa 2 do Pipeline Shopee Videos

Busca 30 vídeos por produto na Pexels API (paginação + queries variadas).
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


def search_pexels_page(query: str, page: int = 1, per_page: int = 15, orientation: str = "all") -> list[VideoCandidate]:
    """Search one page of Pexels results."""
    if not PEXELS_API_KEY:
        return []

    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "per_page": per_page, "page": page, "orientation": orientation}

    candidates = []
    try:
        resp = requests.get(PEXELS_API_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for video in data.get("videos", []):
            video_files = video.get("video_files", [])
            # Get best quality file (prefer HD, then SD)
            best = None
            for f in video_files:
                q = f.get("quality", "")
                if q in ("hd", "sd"):
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
        logger.warning("Pexels search failed for '%s' page %d: %s", query, page, e)

    return candidates


def search_pexels(query: str, max_results: int = 30) -> list[VideoCandidate]:
    """Search Pexels with pagination to get up to max_results."""
    all_candidates = []
    page = 1
    per_page = min(max_results, 15)  # Pexels max per_page is 80, but 15 is safe

    while len(all_candidates) < max_results and page <= 3:
        candidates = search_pexels_page(query, page=page, per_page=per_page)
        if not candidates:
            break
        all_candidates.extend(candidates)
        page += 1
        time.sleep(0.3 + random.uniform(0.1, 0.5))

    return all_candidates[:max_results]


def search_videos_for_products(
    products: list[dict],
    output_dir: Path,
    max_videos_per_product: int = 30,
) -> dict:
    """
    Search up to max_videos_per_product videos for each trending product.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if not PEXELS_API_KEY:
        logger.warning("PEXELS_API_KEY not set.")
        return {"status": "skipped", "reason": "PEXELS_API_KEY not set", "products": []}

    results = []
    for product in products:
        name = product.get("name", "")
        logger.info("Searching up to %d videos for: %s", max_videos_per_product, name)

        # Multiple queries in English and Portuguese to maximize results
        queries = [
            name,
            f"{name} product",
            f"{name} tech",
            f"{name} gadget",
            f"{name} unboxing",
            f"{name} review",
        ]

        all_videos = []
        seen_urls = set()

        for query in queries:
            if len(all_videos) >= max_videos_per_product:
                break

            videos = search_pexels(query, max_results=15)
            for v in videos:
                if v.url not in seen_urls:
                    seen_urls.add(v.url)
                    all_videos.append(v.to_dict())

            time.sleep(0.5 + random.uniform(0.2, 1))

        product_result = {
            "product_name": name,
            "product_score": product.get("score", 0),
            "videos": all_videos[:max_videos_per_product],
            "videos_found": len(all_videos[:max_videos_per_product]),
        }
        results.append(product_result)
        logger.info("  Found %d unique video(s) for '%s'", product_result["videos_found"], name)

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
    mock_products = [{"name": "smartphone", "score": 90}]
    result = search_videos_for_products(
        products=mock_products,
        output_dir=Path("/tmp/pexels_test"),
        max_videos_per_product=30,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
