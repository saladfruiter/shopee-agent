#!/usr/bin/env python3
"""
Configuration Loader for Shopee Agent
=====================================

Loads configuration from config.yaml in project root.
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional


def find_project_root() -> Path:
    """Find project root by looking for config.yaml."""
    current = Path.cwd()
    
    # Check current directory and parents
    for path in [current] + list(current.parents):
        if (path / "config.yaml").exists():
            return path
        if (path / "shopee-agent").exists():
            return path / "shopee-agent"
    
    # Default to current directory
    return current


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration from YAML file.
    
    Args:
        config_path: Path to config.yaml (auto-detected if None)
        
    Returns:
        Configuration dictionary
    """
    if config_path is None:
        project_root = find_project_root()
        config_path = project_root / "config.yaml"
    else:
        config_path = Path(config_path)
    
    default_config = {
        "video_filter": {
            "face_threshold": 0.3,
            "frame_interval": 2,
            "min_resolution": [1280, 720],
            "min_duration": 15,
            "max_duration": 60,
            "watermark_threshold": 10,
            "rejected_retention_days": 7,
            "yolo_model": "yolov8n-face.pt"
        },
        "paths": {
            "raw_videos": "raw_videos",
            "rejected": "rejected",
            "output": "output"
        }
    }
    
    if not config_path.exists():
        return default_config
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        
        # Merge with defaults
        config = deep_merge(default_config, user_config)
        return config
        
    except Exception as e:
        print(f"Warning: Failed to load config from {config_path}: {e}")
        return default_config


def deep_merge(base: Dict, override: Dict) -> Dict:
    """Deep merge two dictionaries."""
    result = base.copy()
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    
    return result


if __name__ == "__main__":
    config = load_config()
    print("Loaded config:")
    print(yaml.dump(config, default_flow_style=False))
