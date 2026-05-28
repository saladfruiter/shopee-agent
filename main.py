#!/usr/bin/env python3
"""
Shopee Videos Pipeline — Main Entry Point

Orchestrates the 7-step pipeline:
1. Trend analysis (trends_analyzer)
2. Video search
3. Visual filter
4. Download
5. Compliance check
6. Affiliate link generation
7. Caption generation

Usage:
    python3 main.py [--step STEP] [--dry-run] [--config PATH]
"""

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

BASE_DIR = Path(__file__).resolve().parent


def run_step_1_trends(config_path: Path, dry_run: bool = False):
    """Run trends analysis (Etapa 1)."""
    from trends_analyzer import run_trends_analysis
    result = run_trends_analysis(config_path=config_path, use_llm=not dry_run)
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
        "--dry-run", action="store_true",
        help="Validate without executing external calls"
    )
    args = parser.parse_args()

    logger.info("Shopee Videos Pipeline starting...")
    logger.info("Config: %s", args.config)

    if args.dry_run:
        logger.info("DRY RUN MODE — no external calls will be made")
        # Just validate config
        import yaml
        with open(args.config) as f:
            cfg = yaml.safe_load(f)
        logger.info("Config valid. Weights: %s", cfg.get("trending", {}).get("weights"))
        logger.info("Dry run complete.")
        return

    # Step 1: Trends Analysis
    if args.step is None or args.step == 1:
        logger.info("=" * 60)
        logger.info("STEP 1: Trend Analysis")
        logger.info("=" * 60)
        run_step_1_trends(args.config)

    # Steps 2-7: TODO — implemented in subsequent tasks
    for step_num in range(2, 8):
        if args.step is not None and args.step != step_num:
            continue
        logger.info("STEP %d: NOT YET IMPLEMENTED", step_num)

    logger.info("Pipeline complete.")


if __name__ == "__main__":
    main()
