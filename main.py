#!/usr/bin/env python3
"""
Shopee Videos Pipeline — Main Entry Point

Orchestrates the pipeline:
1. Trend analysis (trends_analyzer)
2. Video search
3. Visual filter
4. Download
5. Compliance check
6. Affiliate link generation
7. Caption generation

Output is stored in /mnt/user/data/shopee_execute/YYYY-MM-DD/

Usage:
    python3 main.py [--step STEP] [--dry-run] [--config PATH] [--date DATE]
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

BASE_DIR = Path(__file__).resolve().parent


def get_today_dir(storage_root: Path, date_str: str = None) -> Path:
    """Return the date-based output directory: /storage_root/YYYY-MM-DD/"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    day_dir = storage_root / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir


def run_step_1_trends(config: dict, day_dir: Path, use_llm: bool = True) -> dict:
    """Run trends analysis (Etapa 1) into the day's directory."""
    from trends_analyzer import run_trends_analysis
    result = run_trends_analysis(
        config=config,
        output_dir=day_dir / "trends",
        use_llm=use_llm,
    )
    logger.info("Step 1 complete: %d products ranked", len(result.get("ranked_products", [])))
    return result


def main():
    parser = argparse.ArgumentParser(description="Shopee Videos Pipeline")
    parser.add_argument(
        "--step", type=int, default=None,
        help="Run a specific step (1-7). Default: all steps."
    )
    parser.add_argument(
        "--config", type=Path, default=BASE_DIR / "config.yaml",
        help="Path to config.yaml"
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Override date for output folder (YYYY-MM-DD). Default: today."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate without executing external calls"
    )
    args = parser.parse_args()

    logger.info("Shopee Videos Pipeline starting...")
    logger.info("Config: %s", args.config)

    # Load config to get storage_root
    import yaml
    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    storage_root = Path(cfg.get("project", {}).get("storage_root", str(BASE_DIR)))
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    day_dir = storage_root / date_str
    day_dir.mkdir(parents=True, exist_ok=True)

    # Ensure subdirectories exist
    for subdir in ["trends", "raw_videos", "approved", "rejected", "links", "reports", "logs"]:
        (day_dir / subdir).mkdir(exist_ok=True)

    # Also ensure global logs dir
    (storage_root / "logs").mkdir(exist_ok=True)

    logger.info("Storage root: %s", storage_root)
    logger.info("Output directory: %s", day_dir)

    # Save execution metadata
    meta = {
        "pipeline_start": datetime.now().isoformat(),
        "date": date_str,
        "output_dir": str(day_dir),
        "config_path": str(args.config),
    }
    meta_path = day_dir / "pipeline_meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    if args.dry_run:
        logger.info("DRY RUN MODE — no external calls will be made")
        logger.info("Config valid. Weights: %s", cfg.get("trending", {}).get("weights"))
        logger.info("Would output to: %s", day_dir)
        logger.info("Dry run complete.")
        return

    # Step 1: Trends Analysis
    if args.step is None or args.step == 1:
        logger.info("=" * 60)
        logger.info("STEP 1: Trend Analysis")
        logger.info("=" * 60)
        run_step_1_trends(cfg, day_dir, use_llm=True)

    # Steps 2-7: TODO — implemented in subsequent tasks
    for step_num in range(2, 8):
        if args.step is not None and args.step != step_num:
            continue
        logger.info("STEP %d: NOT YET IMPLEMENTED", step_num)

    # Update metadata with completion
    meta["pipeline_end"] = datetime.now().isoformat()
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    logger.info("Pipeline complete. Output: %s", day_dir)


if __name__ == "__main__":
    main()
