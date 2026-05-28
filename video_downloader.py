#!/usr/bin/env python3
"""Video Downloader Module for Shopee Videos Pipeline.

Downloads videos using yt-dlp, validates with ffprobe, computes perceptual hash,
and saves metadata.
"""

import os
import sys
import json
import subprocess
import hashlib
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

import yt_dlp
import imagehash
from PIL import Image
import cv2

from config_loader import load_config

logger = logging.getLogger(__name__)


class VideoDownloader:
    """Downloads and processes videos."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.base_path = Path(self.config.get("paths", {}).get("base", "."))
        self.raw_videos_dir = self.base_path / self.config.get("paths", {}).get("raw_videos", "raw_videos")
        self.pipeline_config = self.config.get("pipeline", {})
        self.max_retries = self.pipeline_config.get("max_retries", 3)
        self.retry_backoff = self.pipeline_config.get("retry_backoff", "exponential")
        self.concurrency = self.pipeline_config.get("concurrency", 2)

        # Ensure directories exist
        self.raw_videos_dir.mkdir(parents=True, exist_ok=True)
        self._hash_store_path = self.raw_videos_dir / ".perceptual_hashes.json"
        self._load_hash_store()

        # yt-dlp options for download
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": str(self.raw_videos_dir / "%(title)s.%(ext)s"),
            "merge_output_format": "mp4",
            "retries": self.max_retries,
            "fragment_retries": self.max_retries,
            "extractor_retries": self.max_retries,
            "socket_timeout": 30,
        }

    def _load_hash_store(self):
        """Load existing perceptual hashes from JSON."""
        self._hash_store = {}
        if self._hash_store_path.exists():
            try:
                with open(self._hash_store_path, "r") as f:
                    self._hash_store = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load hash store: {e}")

    def _save_hash_store(self):
        """Save perceptual hashes to JSON."""
        try:
            with open(self._hash_store_path, "w") as f:
                json.dump(self._hash_store, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save hash store: {e}")

    def _compute_perceptual_hash(self, video_path: Path, sample_time: int = 5) -> Optional[str]:
        """Extract a frame from video and compute perceptual hash."""
        try:
            # Use ffmpeg to extract frame at sample_time seconds
            cmd = [
                "ffmpeg",
                "-ss", str(sample_time),
                "-i", str(video_path),
                "-vframes", "1",
                "-f", "image2",
                "-c:v", "png",
                "-loglevel", "error",
                "-"
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode != 0:
                logger.warning(f"ffmpeg failed to extract frame: {result.stderr}")
                # Fallback: use thumbnail if available? Not now.
                return None
            
            # Convert raw bytes to PIL Image
            from io import BytesIO
            img = Image.open(BytesIO(result.stdout))
            # Compute perceptual hash (average hash)
            phash = imagehash.phash(img)
            return str(phash)
        except Exception as e:
            logger.warning(f"Failed to compute perceptual hash: {e}")
            return None

    def _is_duplicate(self, phash: str, threshold: int = 5) -> bool:
        """Check if perceptual hash is similar to any existing hash."""
        if not phash:
            return False
        new_hash = imagehash.hex_to_hash(phash)
        for existing_hash_str in self._hash_store.values():
            existing_hash = imagehash.hex_to_hash(existing_hash_str)
            if new_hash - existing_hash <= threshold:
                return True
        return False

    def _validate_with_ffprobe(self, video_path: Path) -> Tuple[bool, Dict[str, Any]]:
        """Validate video file using ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(video_path)
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.error(f"ffprobe error: {result.stderr}")
                return False, {}
            data = json.loads(result.stdout)
            # Basic validation: at least one video stream
            streams = data.get("streams", [])
            video_streams = [s for s in streams if s.get("codec_type") == "video"]
            if not video_streams:
                logger.warning("No video stream found")
                return False, data
            
            # Check duration
            format_info = data.get("format", {})
            duration = float(format_info.get("duration", 0))
            if duration < self.config.get("video_quality", {}).get("min_duration_sec", 10):
                logger.warning(f"Video too short: {duration}s")
                return False, data
            
            # Check resolution
            height = int(video_streams[0].get("height", 0))
            min_height = 720  # default
            if height < min_height:
                logger.warning(f"Resolution too low: {height}p")
                return False, data
            
            return True, data
        except Exception as e:
            logger.error(f"ffprobe validation failed: {e}")
            return False, {}

    def _generate_filename(self, product_name: str, video_index: int = 0) -> Tuple[Path, Path]:
        """Generate filename based on date and product name."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        # Sanitize product name
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in product_name)
        safe_name = safe_name[:50]  # limit length
        video_filename = f"{date_str}/{safe_name}-{video_index:03d}.mp4"
        json_filename = f"{date_str}/{safe_name}-{video_index:03d}.json"
        video_path = self.raw_videos_dir / video_filename
        json_path = self.raw_videos_dir / json_filename
        video_path.parent.mkdir(parents=True, exist_ok=True)
        return video_path, json_path

    def download(self, candidate: Dict[str, Any], product_name: str, video_index: int = 0) -> Optional[Path]:
        """Download a video candidate.

        Args:
            candidate: VideoCandidate as dict (from search module)
            product_name: Product name for filename
            video_index: Index for multiple videos per product

        Returns:
            Path to downloaded video file, or None on failure
        """
        url = candidate.get("url")
        if not url:
            logger.error("No URL provided")
            return None

        # Prepare output path
        video_path, json_path = self._generate_filename(product_name, video_index)
        
        # Update yt-dlp output template
        self.ydl_opts["outtmpl"] = str(video_path.with_suffix(""))  # yt-dlp adds extension
        
        # Retry loop
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Downloading attempt {attempt+1}/{self.max_retries}: {url}")
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if not info:
                        raise Exception("yt-dlp returned no info")
                    
                    # Determine actual downloaded file (yt-dlp may add extension)
                    # The outtmpl we gave might have been changed by yt-dlp
                    # Let's find the file that was created
                    # For simplicity, we assume the filename we gave plus .mp4
                    actual_video_path = video_path.with_suffix(".mp4")
                    if not actual_video_path.exists():
                        # Search for files matching pattern
                        pattern = f"{video_path.stem}.*"
                        matches = list(video_path.parent.glob(pattern))
                        if matches:
                            actual_video_path = matches[0]
                        else:
                            raise FileNotFoundError(f"Downloaded file not found: {actual_video_path}")
                    
                    # Validate with ffprobe
                    is_valid, ffprobe_data = self._validate_with_ffprobe(actual_video_path)
                    if not is_valid:
                        raise Exception("Video validation failed")
                    
                    # Compute perceptual hash
                    phash = self._compute_perceptual_hash(actual_video_path)
                    if phash and self._is_duplicate(phash):
                        logger.warning("Duplicate video detected, skipping")
                        # Delete the duplicate file
                        actual_video_path.unlink()
                        return None
                    
                    # Save perceptual hash
                    if phash:
                        self._hash_store[str(actual_video_path)] = phash
                        self._save_hash_store()
                    
                    # Save metadata JSON
                    metadata = {
                        "product_name": product_name,
                        "url": url,
                        "source": candidate.get("source"),
                        "title": candidate.get("title"),
                        "duration": candidate.get("duration"),
                        "resolution": f"{candidate.get('width')}x{candidate.get('height')}",
                        "download_timestamp": datetime.now().isoformat(),
                        "file_size_bytes": actual_video_path.stat().st_size,
                        "ffprobe": ffprobe_data,
                        "perceptual_hash": phash,
                        "candidate_metadata": candidate.get("metadata"),
                    }
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(metadata, f, indent=2, ensure_ascii=False)
                    
                    logger.info(f"Download successful: {actual_video_path}")
                    return actual_video_path
                    
            except Exception as e:
                logger.warning(f"Download attempt {attempt+1} failed: {e}")
                if attempt < self.max_retries - 1:
                    # Exponential backoff
                    sleep_time = 2 ** attempt
                    time.sleep(sleep_time)
                else:
                    logger.error(f"All download attempts failed for {url}")
                    return None
        
        return None

    def download_batch(self, candidates: List[Dict[str, Any]], product_name: str) -> List[Path]:
        """Download multiple candidates, respecting concurrency."""
        downloaded = []
        # Simple sequential for now; concurrency can be added with ThreadPoolExecutor
        for i, cand in enumerate(candidates):
            result = self.download(cand, product_name, video_index=i)
            if result:
                downloaded.append(result)
            if len(downloaded) >= self.concurrency:
                break  # limit per product
        return downloaded


if __name__ == "__main__":
    # Simple test
    logging.basicConfig(level=logging.INFO)
    downloader = VideoDownloader()
    # Mock candidate
    mock_candidate = {
        "url": "https://www.pexels.com/video/smartphone-unboxing-1920x1080-12345/",
        "source": "pexels",
        "title": "Smartphone Unboxing",
        "duration": 30,
        "width": 1920,
        "height": 1080,
    }
    result = downloader.download(mock_candidate, "smartphone_test")
    if result:
        print(f"Downloaded: {result}")
    else:
        print("Download failed")