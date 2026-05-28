# Video Filter Module (T4)

Visual filtering module for Shopee video pipeline. Detects faces, watermarks, and validates video quality.

## Features

- **Face Detection**: YOLOv8-face (threshold 0.3) with Haar cascade fallback
- **Resolution Check**: Minimum 720p (1280x720)
- **Duration Check**: 15-60 seconds range
- **Watermark Detection**: Perceptual hash comparison against known list
- **Auto-cleanup**: Rejected videos deleted after 7 days

## Usage

```python
from video_filter import VideoFilter

# Initialize filter
filter = VideoFilter(
    face_threshold=0.3,
    frame_interval=2,  # 1 frame every 2s
    min_resolution=(1280, 720),
    min_duration=15.0,
    max_duration=60.0
)

# Filter single video
result = filter.filter_video("raw_videos/2026-05-27/product-001.mp4")

# Batch filter directory
from video_filter import batch_filter
results = batch_filter("raw_videos/2026-05-27/")

# Cleanup old rejected videos
filter.cleanup_rejected("raw_videos/", retention_days=7)
```

## Output Format

Results saved as `{product}_filtered.json`:

```json
{
  "video_path": "raw_videos/2026-05-27/product-001.mp4",
  "passed": true,
  "reasons": [],
  "metadata": {
    "width": 1280,
    "height": 720,
    "duration": 30.5,
    "bitrate": 1500000,
    "codec": "h264",
    "fps": 30.0,
    "size_bytes": 5242880
  },
  "face_count": 0,
  "watermark_detected": false,
  "resolution": [1280, 720],
  "duration": 30.5,
  "frames_analyzed": 15,
  "timestamp": "2026-05-27T20:57:00"
}
```

## Rejected Videos

Failed videos are moved to `rejected/` with a `{product}_rejection.json` file.

## CLI Usage

```bash
# Single video
python3 video_filter.py raw_videos/2026-05-27/product-001.mp4

# Batch mode
python3 video_filter.py raw_videos/2026-05-27/ -o results/

# Cleanup old rejected
python3 video_filter.py raw_videos/ --cleanup --retention-days 7
```

## Dependencies

- opencv-python-headless
- ultralytics (YOLOv8)
- imagehash
- Pillow
- PyYAML

## Configuration

Uses `config.yaml` in project root (auto-detected):

```yaml
video_filter:
  face_threshold: 0.3
  frame_interval: 2
  min_resolution: [1280, 720]
  min_duration: 15
  max_duration: 60
  watermark_threshold: 10
  rejected_retention_days: 7
  yolo_model: "yolov8n-face.pt"
```

## Adding Known Watermarks

Edit `KNOWN_WATERMARK_HASHES` in `video_filter.py`:

```python
import imagehash
from PIL import Image

# Load watermark image
wm = Image.open("watermark.png")
wm_hash = imagehash.phash(wm)

# Add to list
KNOWN_WATERMARK_HASHES = [wm_hash]
```
