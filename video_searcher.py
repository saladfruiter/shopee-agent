#!/usr/bin/env python3
"""Video Search Module for Shopee Videos Pipeline.

Searches for videos from Tier 1 sources (Pexels, Pixabay, Coverr, Mixkit) using yt-dlp,
with Brave Search API as fallback for general video discovery.
"""

from __future__ import annotations

import os
import logging
import json
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from urllib.parse import quote_plus

import yt_dlp
import requests

from config_loader import load_config

logger = logging.getLogger(__name__)


@dataclass
class VideoCandidate:
    """Represents a potential video to download."""
    url: str
    source: str  # e.g., "pexels", "pixabay", "brave_search"
    title: Optional[str] = None
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    thumbnail: Optional[str] = None
    description: Optional[str] = None
    uploader: Optional[str] = None
    upload_date: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class VideoSearcher:
    """Searches for videos across multiple sources."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.tier1_sources = self.config.get("video_sources", {}).get("tier1", [])
        self.brave_api_key = os.environ.get("BRAVE_API_KEY")
        self.quality_thresholds = self.config.get("video_quality", {})
        self.min_resolution = self.quality_thresholds.get("min_resolution", "720p")
        self.min_duration = self.quality_thresholds.get("min_duration_sec", 10)
        self.max_duration = self.quality_thresholds.get("max_duration_sec", 120)
        self.min_bitrate = self.quality_thresholds.get("min_bitrate_kbps", 2000)

        # yt-dlp options for metadata extraction
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "forcejson": True,
            "extract_flat": False,
            "format": "bestvideo[height>=720]+bestaudio/best[height>=720]/best",
        }

    def _resolution_to_pixels(self, resolution: str) -> int:
        """Convert resolution string like '720p' to height in pixels."""
        mapping = {
            "360p": 360,
            "480p": 480,
            "720p": 720,
            "1080p": 1080,
            "1440p": 1440,
            "2160p": 2160,
        }
        return mapping.get(resolution, 720)

    def _meets_quality(self, video_info: Dict[str, Any]) -> bool:
        """Check if video meets minimum quality thresholds."""
        # Check duration
        duration = video_info.get("duration")
        if duration is not None:
            if duration < self.min_duration or duration > self.max_duration:
                logger.debug(f"Video duration {duration}s outside range [{self.min_duration}, {self.max_duration}]")
                return False

        # Check resolution (height)
        height = video_info.get("height")
        min_height = self._resolution_to_pixels(self.min_resolution)
        if height is not None and height < min_height:
            logger.debug(f"Video height {height} below minimum {min_height}")
            return False

        # Check bitrate (approximate via tbr)
        tbr = video_info.get("tbr")
        if tbr is not None and tbr < self.min_bitrate:
            logger.debug(f"Video bitrate {tbr} kbps below minimum {self.min_bitrate}")
            return False

        return True

    def _extract_video_info(self, url: str, source: str) -> Optional[VideoCandidate]:
        """Extract video metadata using yt-dlp."""
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return None

                # Filter out playlists
                if info.get("_type") == "playlist" or "entries" in info:
                    # For playlists, we might want to iterate entries; for now skip
                    logger.debug(f"Skipping playlist URL: {url}")
                    return None

                # Check quality thresholds
                if not self._meets_quality(info):
                    return None

                candidate = VideoCandidate(
                    url=info.get("webpage_url", url),
                    source=source,
                    title=info.get("title"),
                    duration=info.get("duration"),
                    width=info.get("width"),
                    height=info.get("height"),
                    thumbnail=info.get("thumbnail"),
                    description=info.get("description"),
                    uploader=info.get("uploader"),
                    upload_date=info.get("upload_date"),
                    view_count=info.get("view_count"),
                    like_count=info.get("like_count"),
                    comment_count=info.get("comment_count"),
                    metadata={
                        "formats": info.get("formats"),
                        "tags": info.get("tags"),
                        "categories": info.get("categories"),
                    },
                )
                return candidate
        except Exception as e:
            logger.warning(f"Failed to extract info from {url}: {e}")
            return None

    def _search_tier1_source(self, source: Dict[str, Any], query: str) -> List[VideoCandidate]:
        """Search a Tier 1 source using yt-dlp's built-in search (if supported)."""
        source_name = source.get("name", "").lower()
        base_url = source.get("url", "")
        candidates = []

        # yt-dlp supports search on some sites via search URLs
        search_url = None
        if source_name == "pexels":
            search_url = f"{base_url}{quote_plus(query)}"
        elif source_name == "pixabay":
            search_url = f"{base_url}videos/search/{quote_plus(query)}"
        elif source_name == "coverr":
            # Coverr doesn't have direct search via yt-dlp; fallback to Brave Search
            pass
        elif source_name == "mixkit":
            search_url = f"{base_url}free-videos/{quote_plus(query)}"

        if search_url:
            logger.info(f"Searching {source_name} via yt-dlp: {search_url}")
            candidate = self._extract_video_info(search_url, source_name)
            if candidate:
                candidates.append(candidate)

        # If yt-dlp search fails, fallback to Brave Search for this source
        if not candidates and self.brave_api_key:
            brave_candidates = self._brave_search(query, source=source_name)
            candidates.extend(brave_candidates)

        return candidates

    def _brave_search(self, query: str, source: Optional[str] = None) -> List[VideoCandidate]:
        """Search videos using Brave Search API."""
        if not self.brave_api_key:
            logger.warning("BRAVE_API_KEY not set, skipping Brave Search")
            return []

        # Construct search query with source site filter
        search_query = f"{query} video"
        if source:
            site_map = {
                "pexels": "site:pexels.com",
                "pixabay": "site:pixabay.com",
                "coverr": "site:coverr.co",
                "mixkit": "site:mixkit.co",
            }
            site_filter = site_map.get(source)
            if site_filter:
                search_query = f"{search_query} {site_filter}"

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.brave_api_key,
        }
        params = {
            "q": search_query,
            "count": 5,
            "search_lang": "pt",
            "video_search": True,
        }

        try:
            resp = requests.get(
                "https://api.search.brave.com/res/v1/video/search",
                headers=headers,
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("video", {}).get("results", [])
            candidates = []
            for item in results:
                url = item.get("url")
                if not url:
                    continue
                # Extract metadata from Brave result
                candidate = VideoCandidate(
                    url=url,
                    source="brave_search",
                    title=item.get("title"),
                    description=item.get("description"),
                    thumbnail=item.get("thumbnail", {}).get("src"),
                    duration=item.get("duration"),
                    metadata={
                        "brave_meta": item.get("meta_url"),
                        "page_age": item.get("page_age"),
                        "age": item.get("age"),
                    },
                )
                # Further quality check via yt-dlp (optional, could be heavy)
                # For now, accept all results; filtering later
                candidates.append(candidate)
            return candidates
        except Exception as e:
            logger.error(f"Brave Search failed: {e}")
            return []

    def search(self, query: str, max_results: int = 10) -> List[VideoCandidate]:
        """Search for videos across all configured sources.

        Args:
            query: Search query (product name, keywords in Portuguese)
            max_results: Maximum number of candidates to return

        Returns:
            List of VideoCandidate objects sorted by relevance/quality
        """
        all_candidates = []

        # Search Tier 1 sources via yt-dlp
        for source in self.tier1_sources:
            candidates = self._search_tier1_source(source, query)
            all_candidates.extend(candidates)
            if len(all_candidates) >= max_results:
                break

        # If we still need more, use Brave Search across all sources
        if len(all_candidates) < max_results and self.brave_api_key:
            brave_candidates = self._brave_search(query)
            all_candidates.extend(brave_candidates)

        # Deduplicate by URL
        seen_urls = set()
        unique_candidates = []
        for cand in all_candidates:
            if cand.url not in seen_urls:
                seen_urls.add(cand.url)
                unique_candidates.append(cand)

        # Sort by relevance (view_count, like_count, duration)
        # For now, simple heuristic: prefer videos with higher engagement and suitable duration
        def score(cand: VideoCandidate) -> float:
            s = 0.0
            if cand.view_count:
                s += min(cand.view_count / 10000, 10)  # up to 10 points
            if cand.like_count:
                s += min(cand.like_count / 1000, 5)  # up to 5 points
            if cand.duration:
                # Prefer middle range (30-60 sec)
                if 30 <= cand.duration <= 60:
                    s += 5
                elif 10 <= cand.duration <= 120:
                    s += 2
            return s

        unique_candidates.sort(key=score, reverse=True)
        return unique_candidates[:max_results]


if __name__ == "__main__":
    # Simple test
    import sys
    logging.basicConfig(level=logging.INFO)
    searcher = VideoSearcher()
    query = "smartphone unboxing" if len(sys.argv) < 2 else sys.argv[1]
    results = searcher.search(query, max_results=3)
    for i, cand in enumerate(results, 1):
        print(f"\n--- Result {i} ---")
        print(f"URL: {cand.url}")
        print(f"Source: {cand.source}")
        print(f"Title: {cand.title}")
        print(f"Duration: {cand.duration}s")
        print(f"Resolution: {cand.width}x{cand.height}")
        print(f"Views: {cand.view_count}")