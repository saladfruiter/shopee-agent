#!/usr/bin/env python3
"""Quick smoke test for video_searcher and video_downloader."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from config_loader import load_config
from video_searcher import VideoSearcher
from video_downloader import VideoDownloader

def test_config():
    print("Loading config...")
    config = load_config("config.yaml")
    assert config is not None
    print(f"Config keys: {list(config.keys())}")

def test_searcher():
    print("\nInitializing VideoSearcher...")
    searcher = VideoSearcher()
    print(f"Tier 1 sources: {len(searcher.tier1_sources)}")
    print(f"Brave API key present: {bool(searcher.brave_api_key)}")

def test_downloader():
    print("\nInitializing VideoDownloader...")
    downloader = VideoDownloader()
    print(f"Base path: {downloader.base_path}")
    print(f"Raw videos dir: {downloader.raw_videos_dir}")
    print(f"Max retries: {downloader.max_retries}")

if __name__ == "__main__":
    try:
        test_config()
        test_searcher()
        test_downloader()
        print("\nSmoke test passed.")
    except Exception as e:
        print(f"\nSmoke test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)