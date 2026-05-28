#!/usr/bin/env python3
"""
Quick syntax and import test for video_filter module
====================================================

This verifies the module loads correctly without running full tests.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def test_import():
    """Test that all imports work."""
    print("Testing imports...")
    
    try:
        import cv2
        print(f"  ✓ OpenCV {cv2.__version__}")
    except ImportError as e:
        print(f"  ✗ OpenCV: {e}")
        return False
    
    try:
        import numpy as np
        print(f"  ✓ NumPy {np.__version__}")
    except ImportError as e:
        print(f"  ✗ NumPy: {e}")
        return False
    
    try:
        import imagehash
        print(f"  ✓ imagehash")
    except ImportError as e:
        print(f"  ✗ imagehash: {e}")
        return False
    
    try:
        from PIL import Image
        print(f"  ✓ Pillow")
    except ImportError as e:
        print(f"  ✗ Pillow: {e}")
        return False
    
    try:
        from ultralytics import YOLO
        print(f"  ✓ Ultralytics")
    except ImportError as e:
        print(f"  ✗ Ultralytics: {e}")
        return False
    
    return True

def test_video_filter_class():
    """Test VideoFilter class can be instantiated (without model download)."""
    print("\nTesting VideoFilter class...")
    
    try:
        from video_filter import VideoFilter, FilterResult, batch_filter
        print("  ✓ VideoFilter imported")
        print("  ✓ FilterResult imported")
        print("  ✓ batch_filter imported")
        
        # Test FilterResult
        result = FilterResult(
            video_path="/test.mp4",
            passed=True,
            reasons=[],
            metadata={"duration": 30, "width": 1280, "height": 720}
        )
        d = result.to_dict()
        assert d["video_path"] == "/test.mp4"
        assert d["passed"] == True
        print("  ✓ FilterResult works")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_config_loader():
    """Test config loader."""
    print("\nTesting config_loader...")
    
    try:
        from config_loader import load_config, find_project_root
        config = load_config()
        print(f"  ✓ Config loaded: {list(config.keys())}")
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("Video Filter Module - Quick Test")
    print("=" * 50)
    
    results = []
    
    results.append(("Imports", test_import()))
    results.append(("VideoFilter class", test_video_filter_class()))
    results.append(("Config loader", test_config_loader()))
    
    print("\n" + "=" * 50)
    print("Results:")
    print("=" * 50)
    
    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_passed = False
    
    print()
    sys.exit(0 if all_passed else 1)
