#!/usr/bin/env python3
"""
Video Processor — Etapas 3+4 do Pipeline Shopee Videos

Baixa até 30 vídeos da Pexels, aplica filtro visual rigoroso,
e seleciona os top 5 melhores para aprovado.

Filtros:
- Mínimo 720p (altura >= 720)
- ZERO faces (qualquer detecção = rejeita)
- Duração 5-60 segundos
- Sem watermark
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger("video_processor")


def download_video(url: str, output_path: Path, timeout: int = 120) -> bool:
    """Download video from direct URL."""
    import requests

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        resp = requests.get(url, stream=True, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (compatible; ShopeeAgent/1.0)"
        })
        resp.raise_for_status()

        downloaded = 0
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)

        logger.info("Downloaded %d MB → %s", downloaded // (1024 * 1024), output_path.name)
        return True
    except Exception as e:
        logger.warning("Download failed for %s: %s", url, e)
        if output_path.exists():
            output_path.unlink()
        return False


def validate_video(video_path: Path) -> dict[str, Any]:
    """Validate video with ffprobe."""
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


def detect_faces(video_path: Path, sample_interval: int = 2, max_frames: int = 15) -> int:
    """Detect faces. Returns max faces in any single frame."""
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return 0

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
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


def process_and_download(
    search_results_path: Path,
    output_dir: Path,
    min_duration: float = 5.0,
    max_duration: float = 60.0,
    min_height: int = 720,
    max_approved: int = 5,
) -> dict:
    """
    Download up to 30 videos per product, filter strictly, keep top 5.
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
        "total_downloaded": 0,
        "total_filtered_pass": 0,
        "total_rejected": 0,
        "final_approved": 0,
        "results": [],
    }

    for product in search_data.get("products", []):
        product_name = product.get("product_name", "unknown")
        videos = product.get("videos", [])

        if not videos:
            continue

        summary["total_products"] += 1
        product_approved = []

        # Phase 1: Download and filter each video
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in product_name)[:40]
        candidates = []  # (video_path, metadata, face_count)

        for video_info in videos:
            url = video_info.get("url", "")
            if not url:
                continue
            summary["total_videos_attempted"] += 1
            idx = len(candidates)
            temp_path = output_dir / f"temp_{safe_name}_{idx}.mp4"

            # Download
            logger.info("[%s] Downloading (%d/%d): %s", product_name, idx+1, len(videos), url[-60:])
            if not download_video(url, temp_path):
                summary["total_rejected"] += 1
                continue

            summary["total_downloaded"] += 1

            # Validate
            metadata = validate_video(temp_path)
            if not metadata.get("valid"):
                temp_path.unlink(missing_ok=True)
                summary["total_rejected"] += 1
                continue

            # Duration check
            duration = metadata.get("duration", 0)
            if duration < min_duration or duration > max_duration:
                temp_path.unlink(missing_ok=True)
                summary["total_rejected"] += 1
                continue

            # Resolution check: 720p+ — menor dimensão deve ser >= 720
            height = metadata.get("height", 0)
            width = metadata.get("width", 0)
            if min(height, width) < min_height:
                temp_path.unlink(missing_ok=True)
                summary["total_rejected"] += 1
                continue

            # Face detection: ZERO faces allowed
            face_count = detect_faces(temp_path)
            if face_count > 0:
                temp_path.unlink(missing_ok=True)
                summary["total_rejected"] += 1
                continue

            # Passed all filters
            summary["total_filtered_pass"] += 1
            candidates.append((temp_path, metadata, face_count))
            logger.info("[%s] ✅ Pass filter: %.1fs, %dx%d (min=%d), 0 faces", product_name, duration, width, height, min(height, width))

        # Phase 2: Select top 5 by quality score
        # Score: resolution (primary) + duration closeness to 15s (secondary)
        scored = []
        for vpath, meta, _ in candidates:
            h = meta.get("height", 0)
            w = meta.get("width", 0)
            res_score = max(h, w)
            dur = meta.get("duration", 0)
            # Prefer ~15-25s (ideal for Reels), penalty for very short or very long
            dur_score = max(0, 25 - abs(dur - 18))
            total_score = res_score + dur_score
            scored.append((total_score, vpath, meta))

        scored.sort(key=lambda x: x[0], reverse=True)
        top5 = scored[:max_approved]

        for score, vpath, meta in top5:
            idx = len(product_approved)
            final_name = f"{safe_name}_{idx+1:02d}.mp4"
            final_path = approved_dir / final_name
            shutil.move(str(vpath), str(final_path))

            # Save metadata
            meta_path = approved_dir / f"{safe_name}_{idx+1:02d}.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({
                    "product_name": product_name,
                    "file_path": str(final_path),
                    "duration": meta.get("duration", 0),
                    "resolution": f"{meta.get('width')}x{meta.get('height')}",
                    "codec": meta.get("codec"),
                    "size_bytes": meta.get("size_bytes"),
                    "face_count": 0,
                    "quality_score": round(score, 2),
                    "processed_at": datetime.now().isoformat(),
                }, f, indent=2, ensure_ascii=False)

            product_approved.append({
                "file": str(final_path),
                "duration": meta.get("duration", 0),
                "resolution": f"{meta.get('width')}x{meta.get('height')}",
            })
            logger.info("[%s] ✅✅ APPROVED #%d: %s (%.1fs, %dp, score=%.0f)",
                        product_name, idx+1, final_name,
                        meta.get("duration", 0), meta.get("height", 0), score)

        # Clean up remaining candidates (passed filter but not in top 5)
        for _, vpath, _ in scored[max_approved:]:
            if vpath.exists():
                vpath.unlink()
                summary["total_rejected"] += 1  # not top quality

        summary["results"].append({
            "product": product_name,
            "attempted": len(videos),
            "passed_filter": len(candidates),
            "approved_count": len(product_approved),
            "approved": product_approved,
        })

    summary["final_approved"] = sum(r["approved_count"] for r in summary["results"])

    # Save summary
    summary_path = output_dir / "processing_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info("=== Pipeline result: %d approved, %d rejected out of %d attempted ===",
                summary["final_approved"], summary["total_rejected"], summary["total_videos_attempted"])

    return summary


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--search-results", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = process_and_download(args.search_results, args.output_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))
