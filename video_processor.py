#!/usr/bin/env python3
"""
Video Processor — Etapas 3+4 do Pipeline Shopee Videos

Baixa vídeos da Pexels e aplica filtro visual:
- Download direto (Pexels fornece link MP4 direto)
- Validação ffprobe (codec, duração, resolução)
- Detecção de faces (Haar cascade — leve, sem YOLO pesado)
- Verificação de watermark (perceptual hash)
- Move aprovados para approved/, rejeitados para rejected/
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import imagehash
import numpy as np
from PIL import Image

logger = logging.getLogger("video_processor")


def download_video(url: str, output_path: Path, timeout: int = 120) -> bool:
    """Download video from direct URL using requests with streaming."""
    import requests

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        resp = requests.get(url, stream=True, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (compatible; ShopeeAgent/1.0)"
        })
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
                f.write(chunk)
                downloaded += len(chunk)

        logger.info("Downloaded %d MB to %s", downloaded // (1024 * 1024), output_path.name)
        return True
    except Exception as e:
        logger.warning("Download failed for %s: %s", url, e)
        if output_path.exists():
            output_path.unlink()
        return False


def validate_video(video_path: Path) -> dict[str, Any]:
    """Validate video with ffprobe. Returns metadata dict."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(video_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {"valid": False, "error": "ffprobe failed"}

        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]

        if not video_streams:
            return {"valid": False, "error": "No video stream found"}

        vs = video_streams[0]
        fmt = data.get("format", {})
        duration = float(fmt.get("duration", 0))
        height = int(vs.get("height", 0))
        width = int(vs.get("width", 0))
        codec = vs.get("codec_name", "unknown")
        size_bytes = int(fmt.get("size", 0))

        return {
            "valid": True,
            "duration": duration,
            "width": width,
            "height": height,
            "codec": codec,
            "size_bytes": size_bytes,
            "fps": vs.get("r_frame_rate", "0/1"),
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


def detect_faces(video_path: Path, sample_interval: int = 2, max_frames: int = 10) -> int:
    """Detect faces in video using Haar cascade. Returns max faces in any frame."""
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return 0

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30
    frame_step = int(fps * sample_interval)

    max_faces = 0
    frame_idx = 0
    frames_analyzed = 0

    while True:
        ret, frame = cap.read()
        if not ret or frames_analyzed >= max_frames:
            break

        if frame_idx % frame_step == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 4)
            max_faces = max(max_faces, len(faces))
            frames_analyzed += 1

        frame_idx += 1

    cap.release()
    return max_faces


def check_watermark(video_path: Path, sample_time: int = 5) -> bool:
    """
    Check for common watermarks by analyzing corner regions.
    Returns True if watermark-like pattern detected.
    """
    try:
        cmd = [
            "ffmpeg", "-ss", str(sample_time), "-i", str(video_path),
            "-vframes", "1", "-f", "image2", "-c:v", "png",
            "-loglevel", "error", "-"
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            return False

        img = Image.open(__import__("io").BytesIO(result.stdout))
        img_array = np.array(img)
        h, w = img_array.shape[:2]

        # Check corners for consistent text/logo patterns
        # Watermarks are usually in bottom-right or bottom-left
        corner_size = min(h, w) // 8
        corners = [
            img_array[:corner_size, :corner_size],  # top-left
            img_array[:corner_size, w - corner_size:],  # top-right
            img_array[h - corner_size:, :corner_size],  # bottom-left
            img_array[h - corner_size:, w - corner_size:],  # bottom-right
        ]

        # Check for high-frequency content (text/logo indicator)
        for corner in corners:
            gray = cv2.cvtColor(corner, cv2.COLOR_RGB2GRAY)
            # High variance in corner = likely watermark/text
            variance = np.var(gray)
            if variance > 1000:  # heuristic threshold
                return True

        return False
    except Exception:
        return False


def process_and_download(
    search_results_path: Path,
    output_dir: Path,
    min_duration: float = 10.0,
    max_duration: float = 60.0,
    min_height: int = 720,
    reject_faces: bool = True,
) -> dict:
    """
    Download videos from search results and apply visual filter.

    Args:
        search_results_path: Path to search_results.json from Etapa 2
        output_dir: Directory for approved/rejected videos
        min_duration: Minimum video duration (seconds)
        max_duration: Maximum video duration (seconds)
        min_height: Minimum video height (pixels)
        reject_faces: Reject videos with detected faces

    Returns:
        Processing results summary
    """
    with open(search_results_path) as f:
        search_data = json.load(f)

    approved_dir = output_dir / "approved"
    rejected_dir = output_dir / "rejected"
    approved_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "processed_at": datetime.now().isoformat(),
        "total_products": 0,
        "total_videos_attempted": 0,
        "approved": 0,
        "rejected": 0,
        "skipped": 0,
        "results": [],
    }

    for product in search_data.get("products", []):
        product_name = product.get("product_name", "unknown")
        videos = product.get("videos", [])

        if not videos:
            summary["skipped"] += 1
            continue

        summary["total_products"] += 1
        product_approved = []

        for video_info in videos:
            url = video_info.get("url", "")
            if not url:
                continue

            summary["total_videos_attempted"] += 1

            # Sanitize filename
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in product_name)[:40]
            video_filename = f"{safe_name}.mp4"
            temp_path = output_dir / f"temp_{video_filename}"

            # Download
            logger.info("Downloading: %s", url)
            if not download_video(url, temp_path):
                summary["rejected"] += 1
                summary["results"].append({
                    "product": product_name,
                    "url": url,
                    "status": "download_failed",
                })
                continue

            # Validate
            metadata = validate_video(temp_path)
            if not metadata.get("valid"):
                temp_path.unlink(missing_ok=True)
                summary["rejected"] += 1
                summary["results"].append({
                    "product": product_name,
                    "url": url,
                    "status": "validation_failed",
                    "error": metadata.get("error"),
                })
                continue

            # Check duration
            duration = metadata.get("duration", 0)
            if duration < min_duration or duration > max_duration:
                temp_path.unlink(missing_ok=True)
                summary["rejected"] += 1
                summary["results"].append({
                    "product": product_name,
                    "url": url,
                    "status": "duration_failed",
                    "duration": duration,
                })
                continue

            # Check resolution
            height = metadata.get("height", 0)
            if height < min_height:
                temp_path.unlink(missing_ok=True)
                summary["rejected"] += 1
                summary["results"].append({
                    "product": product_name,
                    "url": url,
                    "status": "resolution_failed",
                    "height": height,
                })
                continue

            # Face detection (informative, not auto-reject)
            face_count = 0
            if reject_faces:
                face_count = detect_faces(temp_path)
                # Only reject if MANY faces (crowd scene, not product demo)
                if face_count > 3:
                    temp_path.unlink(missing_ok=True)
                    summary["rejected"] += 1
                    summary["results"].append({
                        "product": product_name,
                        "url": url,
                        "status": "too_many_faces",
                        "face_count": face_count,
                    })
                    continue

            # Watermark check
            watermark = check_watermark(temp_path)
            if watermark:
                temp_path.unlink(missing_ok=True)
                summary["rejected"] += 1
                summary["results"].append({
                    "product": product_name,
                    "url": url,
                    "status": "watermark_detected",
                })
                continue

            # APPROVED — move to approved/
            final_path = approved_dir / video_filename
            shutil.move(str(temp_path), str(final_path))

            # Save metadata
            meta_path = approved_dir / f"{safe_name}.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({
                    "product_name": product_name,
                    "source_url": url,
                    "file_path": str(final_path),
                    "duration": duration,
                    "resolution": f"{metadata.get('width')}x{metadata.get('height')}",
                    "codec": metadata.get("codec"),
                    "size_bytes": metadata.get("size_bytes"),
                    "face_count": face_count,
                    "watermark": watermark,
                    "processed_at": datetime.now().isoformat(),
                }, f, indent=2, ensure_ascii=False)

            product_approved.append(str(final_path))
            summary["approved"] += 1
            logger.info("✅ Approved: %s (%.1fs, %dp)", video_filename, duration, height)

        summary["results"].append({
            "product": product_name,
            "approved_count": len(product_approved),
            "approved_files": product_approved,
        })

    # Save summary
    summary_path = output_dir / "processing_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info("Processing complete: %d approved, %d rejected, %d skipped",
                summary["approved"], summary["rejected"], summary["skipped"])

    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--search-results", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    if args.search_results and args.search_results.exists():
        result = process_and_download(args.search_results, args.output_dir or Path("."))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Usage: python video_processor.py --search-results path/to/search_results.json --output-dir /output/dir")
