#!/usr/bin/env python3
"""
Test script for VideoFilter module
===================================

Creates a test video and runs the filter to verify functionality.
"""

import os
import sys
import json
import subprocess
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))


def create_test_video(output_path: str, duration: int = 30, resolution: str = "1280x720"):
    """
    Create a simple test video using ffmpeg.
    
    Args:
        output_path: Output video path
        duration: Duration in seconds
        resolution: Video resolution (WxH)
    """
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=blue:s={resolution}:d={duration}:r=30",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "28",
        "-c:a", "aac",
        "-shortest",
        output_path
    ]
    
    print(f"Creating test video: {output_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error creating video: {result.stderr}")
        return False
    
    print(f"Created: {output_path}")
    return True


def test_video_filter():
    """Run tests on VideoFilter module."""
    print("=" * 60)
    print("VideoFilter Test Suite")
    print("=" * 60)
    
    # Create test directory
    test_dir = Path("test_videos")
    test_dir.mkdir(exist_ok=True)
    
    # Test 1: Valid video (should pass)
    print("\n[Test 1] Creating valid video (30s, 720p)...")
    valid_video = test_dir / "valid_test.mp4"
    create_test_video(str(valid_video), duration=30, resolution="1280x720")
    
    # Test 2: Too short video (should fail duration check)
    print("\n[Test 2] Creating short video (5s)...")
    short_video = test_dir / "short_test.mp4"
    create_test_video(str(short_video), duration=5, resolution="1280x720")
    
    # Test 3: Low resolution video (should fail resolution check)
    print("\n[Test 3] Creating low resolution video (480p)...")
    lowres_video = test_dir / "lowres_test.mp4"
    create_test_video(str(lowres_video), duration=30, resolution="640x480")
    
    # Import and test VideoFilter
    print("\n" + "=" * 60)
    print("Running VideoFilter tests...")
    print("=" * 60)
    
    try:
        from video_filter import VideoFilter, batch_filter
        
        # Initialize filter
        filter_instance = VideoFilter(
            face_threshold=0.3,
            frame_interval=2,
            min_resolution=(1280, 720),
            min_duration=15.0,
            max_duration=60.0
        )
        
        # Test each video
        test_videos = [
            (valid_video, True, "Valid 30s 720p video"),
            (short_video, False, "Too short (5s)"),
            (lowres_video, False, "Low resolution (480p)")
        ]
        
        results = []
        for video_path, should_pass, description in test_videos:
            print(f"\n--- Testing: {description} ---")
            result = filter_instance.filter_video(str(video_path), str(test_dir))
            
            status = "PASS" if result.passed else "FAIL"
            expected = "PASS" if should_pass else "FAIL (expected)"
            
            print(f"  Video: {video_path.name}")
            print(f"  Resolution: {result.resolution}")
            print(f"  Duration: {result.duration:.1f}s")
            print(f"  Faces: {result.face_count}")
            print(f"  Watermark: {result.watermark_detected}")
            print(f"  Status: {status} (expected: {expected})")
            
            if result.reasons:
                print(f"  Reasons: {', '.join(result.reasons)}")
            
            # Check result
            test_passed = (result.passed == should_pass)
            results.append((description, test_passed))
            
            # Check JSON was created
            json_file = test_dir / f"{video_path.stem}_filtered.json"
            if json_file.exists():
                with open(json_file) as f:
                    json_data = json.load(f)
                print(f"  JSON saved: {json_file.name}")
        
        # Test batch filter
        print("\n--- Testing batch_filter() ---")
        batch_results = batch_filter(str(test_dir), str(test_dir / "batch_output"))
        print(f"Batch processed: {len(batch_results)} videos")
        
        # Summary
        print("\n" + "=" * 60)
        print("Test Summary")
        print("=" * 60)
        
        passed = sum(1 for _, p in results if p)
        total = len(results)
        
        for description, test_passed in results:
            status = "OK" if test_passed else "FAIL"
            print(f"  [{status}] {description}")
        
        print(f"\nTotal: {passed}/{total} tests passed")
        
        # Cleanup
        print("\nCleaning up test files...")
        import shutil
        if test_dir.exists():
            shutil.rmtree(test_dir)
        
        return passed == total
        
    except Exception as e:
        print(f"\nError during testing: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_video_filter()
    sys.exit(0 if success else 1)
