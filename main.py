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


def run_step_2_video_search(config: dict, day_dir: Path, trends_result: dict) -> dict:
    """Run video search (Etapa 2) for trending products."""
    from video_searcher import search_videos_for_products
    products = trends_result.get("ranked_products", [])
    max_videos = config.get("project", {}).get("max_videos_per_product", 1)
    result = search_videos_for_products(
        products=products,
        output_dir=day_dir / "raw_videos",
        max_videos_per_product=max_videos,
    )
    found = sum(1 for p in result.get("products", []) if p.get("videos"))
    logger.info("Step 2 complete: videos found for %d/%d products", found, len(products))
    return result


def run_step_3_4_download_filter(config: dict, day_dir: Path) -> dict:
    """Run video download + visual filter (Etapas 3+4)."""
    from video_processor import process_and_download

    search_path = day_dir / "raw_videos" / "search_results.json"
    if not search_path.exists():
        logger.warning("No search_results.json found. Run step 2 first.")
        return {"status": "skipped", "reason": "No search results"}

    quality = config.get("video_quality", {})
    result = process_and_download(
        search_results_path=search_path,
        output_dir=day_dir,
        min_duration=quality.get("min_duration_sec", 5),
        max_duration=quality.get("max_duration_sec", 60),
        min_height=720,
        max_approved=5,
    )
    logger.info("Step 3+4 complete: %d approved, %d rejected (from %d attempted)",
                result.get("final_approved", 0), result.get("total_rejected", 0),
                result.get("total_videos_attempted", 0))
    return result


def run_step_5_compliance(config: dict, day_dir: Path, use_llm: bool = True) -> dict:
    """Run compliance check (Etapa 5) on approved videos."""
    from compliance_checker import run_compliance_check
    approved_dir = day_dir / "approved"
    output_dir = day_dir / "compliance"
    result = run_compliance_check(
        approved_dir=approved_dir,
        output_dir=output_dir,
        use_llm=use_llm,
    )
    logger.info("Step 5 complete: %d passed, %d failed",
                result.get("passed", 0), result.get("failed", 0))
    return result


def run_step_6_affiliate(config: dict, day_dir: Path, compliance_result: dict) -> dict:
    """Generate affiliate links (Etapa 6) for compliant videos."""
    from affiliate_linker import generate_affiliate_links
    compliant_videos = [
        d for d in compliance_result.get("details", [])
        if d.get("passed")
    ]
    result = generate_affiliate_links(
        videos=compliant_videos,
        output_dir=day_dir / "links",
        config=config,
    )
    logger.info("Step 6 complete: %d links generated", result.get("links_generated", 0))
    return result


def run_step_7_caption(config: dict, day_dir: Path, compliance_result: dict, affiliate_result: dict) -> dict:
    """Generate PT-BR captions (Etapa 7) for compliant videos."""
    from caption_generator import generate_captions
    compliant_videos = [
        d for d in compliance_result.get("details", [])
        if d.get("passed")
    ]
    result = generate_captions(
        videos=compliant_videos,
        affiliate_links=affiliate_result.get("links", []),
        output_dir=day_dir / "captions",
        config=config,
    )
    logger.info("Step 7 complete: %d captions generated", result.get("captions_generated", 0))
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
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Skip LLM refinement in trend analysis"
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
        run_step_1_trends(cfg, day_dir, use_llm=not args.no_llm)

    # Step 2: Video Search
    if args.step is None or args.step == 2:
        logger.info("=" * 60)
        logger.info("STEP 2: Video Search")
        logger.info("=" * 60)
        trends_result = json.loads((day_dir / "trends" / f"{date_str}.json").read_text())
        run_step_2_video_search(cfg, day_dir, trends_result)

    # Step 3+4: Download + Visual Filter
    if args.step is None or args.step == 3 or args.step == 4:
        logger.info("=" * 60)
        logger.info("STEP 3+4: Download + Visual Filter")
        logger.info("=" * 60)
        run_step_3_4_download_filter(cfg, day_dir)

    # Step 5: Compliance Check
    if args.step is None or args.step == 5:
        logger.info("=" * 60)
        logger.info("STEP 5: Compliance Check")
        logger.info("=" * 60)
        compliance_result = run_step_5_compliance(cfg, day_dir, use_llm=not args.no_llm)
    else:
        compliance_result = None

    # Step 6: Affiliate Links
    if args.step is None or args.step == 6:
        logger.info("=" * 60)
        logger.info("STEP 6: Affiliate Links")
        logger.info("=" * 60)
        if compliance_result is None:
            compliance_path = day_dir / "compliance" / "compliance_summary.json"
            if compliance_path.exists():
                with open(compliance_path) as f:
                    compliance_result = json.load(f)
            else:
                logger.warning("No compliance results. Run step 5 first.")
                compliance_result = {"details": [], "passed": 0}
        affiliate_result = run_step_6_affiliate(cfg, day_dir, compliance_result)
    else:
        affiliate_result = None

    # Step 7: Caption Generation
    if args.step is None or args.step == 7:
        logger.info("=" * 60)
        logger.info("STEP 7: Caption Generation")
        logger.info("=" * 60)
        if compliance_result is None:
            compliance_path = day_dir / "compliance" / "compliance_summary.json"
            if compliance_path.exists():
                with open(compliance_path) as f:
                    compliance_result = json.load(f)
            else:
                compliance_result = {"details": [], "passed": 0}
        if affiliate_result is None:
            links_path = day_dir / "links" / "affiliate_links.json"
            if links_path.exists():
                with open(links_path) as f:
                    affiliate_result = json.load(f)
            else:
                affiliate_result = {"links": []}
        run_step_7_caption(cfg, day_dir, compliance_result, affiliate_result)

    # Update metadata with completion
    meta["pipeline_end"] = datetime.now().isoformat()
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    logger.info("Pipeline complete. Output: %s", day_dir)


if __name__ == "__main__":
    main()
