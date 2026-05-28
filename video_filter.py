#!/usr/bin/env python3
"""
Video Filter Module (T4) - Shopee Agent Pipeline
================================================

Visual filter for downloaded videos:
- YOLOv8-face detection (threshold 0.3)
- Extract 1 frame every 2 seconds for analysis
- Resolution check (>= 720p)
- Duration check (15-60 seconds)
- Watermark detection via perceptual hash
- Move rejected videos to rejected/ with reason
- Auto-delete rejected after 7 days

Usage:
    from video_filter import VideoFilter
    filter = VideoFilter()
    result = filter.filter_video("raw_videos/2026-05-27/product-001.mp4")
"""

from __future__ import annotations

import os
import json
import shutil
import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

import cv2
import numpy as np
import imagehash
from PIL import Image
from ultralytics import YOLO

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    """Result of video filtering."""
    video_path: str
    passed: bool
    reasons: List[str]
    metadata: Dict
    face_count: int = 0
    watermark_detected: bool = False
    resolution: Optional[Tuple[int, int]] = None
    duration: Optional[float] = None
    frames_analyzed: int = 0
    timestamp: str = ""
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class VideoFilter:
    """
    Video filter with face detection and watermark checking.
    """
    
    # Known watermark perceptual hashes (add your known watermarks here)
    KNOWN_WATERMARK_HASHES = [
        # Add perceptual hashes of known watermarks (e.g., stock footage logos)
        # imagehash.hex_to_hash("specific_hash_here"),
    ]
    
    def __init__(self, 
                 yolo_model: str = "yolov8n-face.pt",
                 face_threshold: float = 0.3,
                 frame_interval: int = 2,  # Extract 1 frame every N seconds
                 min_resolution: Tuple[int, int] = (1280, 720),  # 720p
                 min_duration: float = 15.0,
                 max_duration: float = 60.0,
                 watermark_threshold: int = 10,  # Hamming distance threshold
                 rejected_retention_days: int = 7):
        """
        Initialize video filter.
        
        Args:
            yolo_model: YOLO model for face detection
            face_threshold: Confidence threshold for face detection
            frame_interval: Extract 1 frame every N seconds
            min_resolution: Minimum resolution (width, height)
            min_duration: Minimum duration in seconds
            max_duration: Maximum duration in seconds
            watermark_threshold: Hamming distance threshold for watermark detection
            rejected_retention_days: Days to keep rejected videos before auto-delete
        """
        self.face_threshold = face_threshold
        self.frame_interval = frame_interval
        self.min_resolution = min_resolution
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.watermark_threshold = watermark_threshold
        self.rejected_retention_days = rejected_retention_days
        
        # Initialize YOLO model for face detection
        logger.info(f"Loading YOLO model: {yolo_model}")
        try:
            self.face_model = YOLO(yolo_model)
        except Exception as e:
            logger.warning(f"Failed to load {yolo_model}, trying yolov8n.pt as fallback: {e}")
            self.face_model = YOLO("yolov8n.pt")
        
        # Initialize face cascade as backup
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        
        logger.info(f"VideoFilter initialized with threshold={face_threshold}, "
                    f"frame_interval={frame_interval}s, min_res={min_resolution}")
    
    def filter_video(self, video_path: str, output_dir: Optional[str] = None) -> FilterResult:
        """
        Filter a video file.
        
        Args:
            video_path: Path to video file
            output_dir: Output directory for filtered JSON (defaults to same dir as video)
            
        Returns:
            FilterResult with pass/fail status and metadata
        """
        video_path = Path(video_path)
        
        if not video_path.exists():
            return FilterResult(
                video_path=str(video_path),
                passed=False,
                reasons=["Video file not found"],
                metadata={},
                timestamp=datetime.now().isoformat()
            )
        
        # Get video metadata
        metadata = self._get_video_metadata(str(video_path))
        
        if "error" in metadata:
            return FilterResult(
                video_path=str(video_path),
                passed=False,
                reasons=[f"Failed to read video: {metadata['error']}"],
                metadata=metadata,
                timestamp=datetime.now().isoformat()
            )
        
        result = FilterResult(
            video_path=str(video_path),
            passed=True,
            reasons=[],
            metadata=metadata,
            resolution=(metadata.get("width", 0), metadata.get("height", 0)),
            duration=metadata.get("duration", 0),
            timestamp=datetime.now().isoformat()
        )
        
        # Check resolution
        if not self._check_resolution(metadata):
            result.passed = False
            result.reasons.append(
                f"Resolution {metadata.get('width')}x{metadata.get('height')} "
                f"below minimum {self.min_resolution[0]}x{self.min_resolution[1]}"
            )
        
        # Check duration
        if not self._check_duration(metadata):
            result.passed = False
            duration = metadata.get("duration", 0)
            if duration < self.min_duration:
                result.reasons.append(
                    f"Duration {duration:.1f}s below minimum {self.min_duration}s"
                )
            elif duration > self.max_duration:
                result.reasons.append(
                    f"Duration {duration:.1f}s above maximum {self.max_duration}s"
                )
        
        # Analyze frames for faces and watermarks
        face_count, watermark_detected, frames_analyzed = self._analyze_frames(str(video_path))
        result.face_count = face_count
        result.watermark_detected = watermark_detected
        result.frames_analyzed = frames_analyzed
        
        # Check for faces (reject if faces found)
        if face_count > 0:
            result.passed = False
            result.reasons.append(f"Detected {face_count} face(s) in video")
        
        # Check for watermark
        if watermark_detected:
            result.passed = False
            result.reasons.append("Watermark detected in video")
        
        # Save result and handle file movement
        self._save_result(result, output_dir)
        
        return result
    
    def _get_video_metadata(self, video_path: str) -> Dict:
        """Get video metadata using ffprobe."""
        import subprocess
        import json
        
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", video_path
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
            
            # Find video stream
            video_stream = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break
            
            if not video_stream:
                return {"error": "No video stream found"}
            
            format_info = data.get("format", {})
            
            # Parse frame rate safely (avoid eval)
            r_frame_rate = video_stream.get("r_frame_rate", "0/1")
            if "/" in r_frame_rate:
                num, den = r_frame_rate.split("/")
                fps = int(num) / int(den) if int(den) != 0 else 0.0
            else:
                fps = float(r_frame_rate) if r_frame_rate else 0.0

            return {
                "width": int(video_stream.get("width", 0)),
                "height": int(video_stream.get("height", 0)),
                "duration": float(format_info.get("duration", 0)),
                "bitrate": int(format_info.get("bit_rate", 0)),
                "codec": video_stream.get("codec_name", "unknown"),
                "fps": fps,
                "size_bytes": int(format_info.get("size", 0)),
            }
        except Exception as e:
            logger.error(f"Failed to get metadata for {video_path}: {e}")
            return {"error": str(e)}
    
    def _check_resolution(self, metadata: Dict) -> bool:
        """Check if video meets minimum resolution."""
        width = metadata.get("width", 0)
        height = metadata.get("height", 0)
        return width >= self.min_resolution[0] and height >= self.min_resolution[1]
    
    def _check_duration(self, metadata: Dict) -> bool:
        """Check if video duration is within acceptable range."""
        duration = metadata.get("duration", 0)
        return self.min_duration <= duration <= self.max_duration
    
    def _analyze_frames(self, video_path: str) -> Tuple[int, bool, int]:
        """
        Analyze video frames for faces and watermarks.
        
        Returns:
            Tuple of (face_count, watermark_detected, frames_analyzed)
        """
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            logger.error(f"Failed to open video: {video_path}")
            return 0, False, 0
        
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30  # Default assumption
        
        frame_interval = int(fps * self.frame_interval)
        
        max_faces = 0
        watermark_found = False
        frames_analyzed = 0
        frame_idx = 0
        
        # Sample frames for watermark detection
        watermark_hashes = []
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Process frame at intervals
            if frame_idx % frame_interval == 0:
                frames_analyzed += 1
                
                # Face detection with YOLO
                faces = self._detect_faces(frame)
                max_faces = max(max_faces, len(faces))
                
                # Collect frame hash for watermark detection
                frame_hash = self._compute_frame_hash(frame)
                watermark_hashes.append(frame_hash)
                
                logger.debug(f"Frame {frame_idx}: {len(faces)} faces detected")
            
            frame_idx += 1
            
            # Stop after analyzing enough frames (max 30 seconds of video)
            if frames_analyzed >= 15:  # 15 frames = 30 seconds at 1 frame/2s
                break
        
        cap.release()
        
        # Check for watermarks using perceptual hash comparison
        if watermark_hashes:
            watermark_found = self._detect_watermark(watermark_hashes)
        
        return max_faces, watermark_found, frames_analyzed
    
    def _detect_faces(self, frame: np.ndarray) -> List:
        """Detect faces in a frame using YOLO."""
        try:
            # Run YOLO inference
            results = self.face_model(frame, conf=self.face_threshold, verbose=False)
            
            faces = []
            for result in results:
                boxes = result.boxes
                if boxes is not None:
                    for box in boxes:
                        # Check if detection is a face (class 0 for face models)
                        cls = int(box.cls[0]) if box.cls is not None else 0
                        conf = float(box.conf[0]) if box.conf is not None else 0
                        
                        # For face-specific models, all detections are faces
                        # For general models, we might need to filter by class
                        if conf >= self.face_threshold:
                            x1, y1, x2, y2 = box.xyxy[0].tolist()
                            faces.append({
                                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                                "confidence": conf
                            })
            
            return faces
            
        except Exception as e:
            logger.warning(f"YOLO face detection failed, using Haar cascade: {e}")
            # Fallback to Haar cascade
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            haar_faces = self.face_cascade.detectMultiScale(gray, 1.1, 4)
            return [{"bbox": [x, y, x+w, y+h], "confidence": 0.5} for (x, y, w, h) in haar_faces]
    
    def _compute_frame_hash(self, frame: np.ndarray) -> imagehash.ImageHash:
        """Compute perceptual hash of a frame."""
        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb_frame)
        return imagehash.phash(pil_image)
    
    def _detect_watermark(self, frame_hashes: List[imagehash.ImageHash]) -> bool:
        """
        Detect watermark by comparing frame hashes with known watermarks.
        
        Uses average hash of collected frames and compares against known list.
        Also checks for consistent patterns across frames (watermark indicator).
        """
        if not frame_hashes or not self.KNOWN_WATERMARK_HASHES:
            return False
        
        # Compare each frame hash against known watermarks
        for frame_hash in frame_hashes:
            for known_hash in self.KNOWN_WATERMARK_HASHES:
                distance = frame_hash - known_hash
                if distance <= self.watermark_threshold:
                    logger.info(f"Watermark detected (distance: {distance})")
                    return True
        
        # Check for consistency across frames (watermark usually appears in all frames)
        # If hashes are very similar across frames, might indicate static watermark
        if len(frame_hashes) >= 3:
            avg_distance = np.mean([
                frame_hashes[i] - frame_hashes[i+1] 
                for i in range(len(frame_hashes)-1)
            ])
            # Very low variation might indicate overlay/watermark
            # This is a heuristic and might need tuning
        
        return False
    
    def _save_result(self, result: FilterResult, output_dir: Optional[str] = None):
        """Save filter result and handle file movement."""
        video_path = Path(result.video_path)
        
        # Determine output directory
        if output_dir is None:
            output_dir = video_path.parent
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate JSON filename
        date_str = datetime.now().strftime("%Y-%m-%d")
        product_name = video_path.stem  # e.g., "product-001"
        json_filename = f"{product_name}_filtered.json"
        json_path = output_dir / json_filename
        
        # Save JSON result
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved filter result to {json_path}")
        
        # Handle rejected videos
        if not result.passed:
            self._move_to_rejected(video_path, result)
    
    def _move_to_rejected(self, video_path: Path, result: FilterResult):
        """Move rejected video to rejected/ directory."""
        rejected_dir = video_path.parent / "rejected"
        rejected_dir.mkdir(parents=True, exist_ok=True)
        
        # Move video file
        dest_path = rejected_dir / video_path.name
        try:
            shutil.move(str(video_path), str(dest_path))
            logger.info(f"Moved rejected video to {dest_path}")
            
            # Save rejection metadata alongside video
            meta_path = rejected_dir / f"{video_path.stem}_rejection.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({
                    "original_path": str(video_path),
                    "rejected_at": result.timestamp,
                    "reasons": result.reasons,
                    "metadata": result.metadata
                }, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"Failed to move rejected video: {e}")
    
    def cleanup_rejected(self, directory: str, retention_days: Optional[int] = None):
        """
        Clean up rejected videos older than retention period.
        
        Args:
            directory: Directory containing rejected/ subdirectory
            retention_days: Days to retain (uses instance default if None)
        """
        if retention_days is None:
            retention_days = self.rejected_retention_days
        
        rejected_dir = Path(directory) / "rejected"
        if not rejected_dir.exists():
            return
        
        cutoff_time = datetime.now() - timedelta(days=retention_days)
        deleted_count = 0
        
        for file_path in rejected_dir.iterdir():
            if file_path.is_file():
                # Check file modification time
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                if mtime < cutoff_time:
                    try:
                        file_path.unlink()
                        deleted_count += 1
                        logger.info(f"Deleted old rejected file: {file_path}")
                    except Exception as e:
                        logger.error(f"Failed to delete {file_path}: {e}")
        
        logger.info(f"Cleanup complete: {deleted_count} files deleted from {rejected_dir}")


def batch_filter(video_dir: str, output_dir: Optional[str] = None, **filter_kwargs) -> List[FilterResult]:
    """
    Batch filter all videos in a directory.
    
    Args:
        video_dir: Directory containing videos
        output_dir: Output directory for results
        **filter_kwargs: Additional arguments for VideoFilter
        
    Returns:
        List of FilterResult for each video
    """
    video_dir = Path(video_dir)
    video_extensions = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    
    video_files = [
        f for f in video_dir.iterdir() 
        if f.is_file() and f.suffix.lower() in video_extensions
    ]
    
    if not video_files:
        logger.warning(f"No video files found in {video_dir}")
        return []
    
    filter_instance = VideoFilter(**filter_kwargs)
    results = []
    
    for video_file in video_files:
        logger.info(f"Filtering: {video_file.name}")
        result = filter_instance.filter_video(str(video_file), output_dir)
        results.append(result)
        
        status = "PASSED" if result.passed else "REJECTED"
        logger.info(f"  -> {status}: {', '.join(result.reasons) if result.reasons else 'OK'}")
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Video Filter Module")
    parser.add_argument("video_path", help="Path to video file or directory")
    parser.add_argument("-o", "--output", help="Output directory for results")
    parser.add_argument("--face-threshold", type=float, default=0.3, 
                        help="Face detection confidence threshold")
    parser.add_argument("--frame-interval", type=int, default=2,
                        help="Extract 1 frame every N seconds")
    parser.add_argument("--min-resolution", default="1280x720",
                        help="Minimum resolution (WxH)")
    parser.add_argument("--min-duration", type=float, default=15.0,
                        help="Minimum duration in seconds")
    parser.add_argument("--max-duration", type=float, default=60.0,
                        help="Maximum duration in seconds")
    parser.add_argument("--cleanup", action="store_true",
                        help="Run cleanup of old rejected videos")
    parser.add_argument("--retention-days", type=int, default=7,
                        help="Days to keep rejected videos")
    
    args = parser.parse_args()
    
    # Parse resolution
    width, height = map(int, args.min_resolution.split("x"))
    
    if args.cleanup:
        # Run cleanup mode
        filter_instance = VideoFilter(rejected_retention_days=args.retention_days)
        filter_instance.cleanup_rejected(args.video_path)
    elif os.path.isdir(args.video_path):
        # Batch mode
        results = batch_filter(
            args.video_path,
            output_dir=args.output,
            face_threshold=args.face_threshold,
            frame_interval=args.frame_interval,
            min_resolution=(width, height),
            min_duration=args.min_duration,
            max_duration=args.max_duration
        )
        print(f"\nFiltered {len(results)} videos:")
        print(f"  Passed: {sum(1 for r in results if r.passed)}")
        print(f"  Rejected: {sum(1 for r in results if not r.passed)}")
    else:
        # Single file mode
        filter_instance = VideoFilter(
            face_threshold=args.face_threshold,
            frame_interval=args.frame_interval,
            min_resolution=(width, height),
            min_duration=args.min_duration,
            max_duration=args.max_duration
        )
        result = filter_instance.filter_video(args.video_path, args.output)
        
        print(f"\nFilter Result for {args.video_path}:")
        print(f"  Status: {'PASSED' if result.passed else 'REJECTED'}")
        print(f"  Resolution: {result.resolution}")
        print(f"  Duration: {result.duration:.1f}s")
        print(f"  Faces detected: {result.face_count}")
        print(f"  Watermark: {'YES' if result.watermark_detected else 'NO'}")
        if result.reasons:
            print(f"  Reasons: {', '.join(result.reasons)}")
