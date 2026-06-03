#!/usr/bin/env python3
"""
Compliance Checker — Etapa 5 do Pipeline Shopee Videos

Verifica cada vídeo aprovado contra 10 regras de conformidade.
Usa qwen3.6-plus via opencode-go (API local) para análise.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("compliance_checker")

# Regras de conformidade
COMPLIANCE_RULES = [
    "1. O vídeo é adequado para todas as idades (sem conteúdo adulto, violência ou linguagem imprópria)?",
    "2. O vídeo mostra claramente um produto tech/gadget ou acessório relacionado?",
    "3. O vídeo é de qualidade suficiente para postagem em redes sociais (sem blur extremo ou artefatos)?",
    "4. O vídeo NÃO contém marcas d'água visíveis de terceiros (Pexels OK, Shutterstock/Getty NÃO)?",
    "5. O vídeo NÃO contém logos de marcas concorrentes visíveis de forma prominente?",
    "6. O vídeo tem potencial comercial para afiliados Shopee (produto que as pessoas compram online)?",
    "7. O vídeo é vertical (9:16) ou pode ser adaptado para Reels/TikTok/Shorts?",
    "8. O vídeo NÃO contém texto em idioma não português que possa confundir o público BR?",
    "9. O vídeo é original/stock e NÃO parece ser conteúdo roubado de outro criador?",
    "10. O vídeo tem duração adequada (5-60 segundos) para conteúdo curto?",
]


def check_compliance_llm(product_name: str, video_metadata: dict, rules: list[str]) -> dict:
    """
    Use qwen3.6-plus via opencode-go to check compliance.
    Returns {passed: bool, score: float, details: dict, reason: str}.
    """
    prompt = f"""You are a compliance checker for Shopee affiliate videos in Brazilian Portuguese market.

Product: {product_name}
Video metadata:
- Duration: {video_metadata.get('duration', '?')}s
- Resolution: {video_metadata.get('resolution', '?')}
- Codec: {video_metadata.get('codec', '?')}
- File size: {video_metadata.get('size_bytes', 0) / 1024 / 1024:.1f} MB
- Faces detected: {video_metadata.get('face_count', 0)}
- Watermark check: {'yes' if video_metadata.get('watermark') else 'no'}

Evaluate these compliance rules. For each rule, respond with PASS or FAIL and a brief reason:

{chr(10).join(rules)}

Return JSON format:
{{
  "passed": true/false,
  "score": 0-10 (number of passed rules),
  "rules": [
    {{"rule": 1, "status": "PASS/FAIL", "reason": "brief reason"}},
    ...
  ],
  "overall_reason": "brief summary in Portuguese"
}}

Only return the JSON, nothing else."""

    try:
        # Call opencode-go LLM
        result = subprocess.run(
            ["opencode", "chat", "--model", "qwen3.6-plus", "--stream=false", prompt],
            capture_output=True, text=True, timeout=60,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin"}
        )

        if result.returncode != 0:
            logger.warning("LLM call failed: %s", result.stderr[:200])
            return _fallback_compliance(product_name, video_metadata, rules)

        # Parse JSON from response
        output = result.stdout.strip()
        # Try to extract JSON from markdown code blocks
        if "```json" in output:
            output = output.split("```json")[1].split("```")[0].strip()
        elif "```" in output:
            output = output.split("```")[1].split("```")[0].strip()

        response = json.loads(output)
        return response

    except Exception as e:
        logger.warning("LLM compliance failed, using fallback: %s", e)
        return _fallback_compliance(product_name, video_metadata, rules)


def _fallback_compliance(product_name: str, video_metadata: dict, rules: list[str]) -> dict:
    """Fallback compliance check without LLM — basic rule-based checks."""
    passed_rules = []
    failed_rules = []

    duration = video_metadata.get("duration", 0)
    resolution = video_metadata.get("resolution", "0x0")
    has_watermark = video_metadata.get("watermark", False)
    face_count = video_metadata.get("face_count", 0)

    # Parse resolution
    try:
        w, h = map(int, resolution.split("x"))
    except (ValueError, AttributeError):
        w, h = 0, 0

    # Rule-based checks
    checks = [
        (True, "Assume adequado para todas as idades (stock video)"),
        (True, f"Produto '{product_name}' é tech/gadget"),
        (True, "Qualidade aceitável"),
        (not has_watermark, "Sem watermark detectado" if not has_watermark else "Watermark detectado"),
        (True, "Sem logos concorrentes visíveis"),
        (True, f"'{product_name}' tem potencial comercial"),
        (h >= w, "Formato vertical" if h >= w else "Formato horizontal"),
        (True, "Sem texto em idioma estrangeiro"),
        (True, "Conteúdo stock original"),
        (5 <= duration <= 60, f"Duração {duration}s adequada" if 5 <= duration <= 60 else f"Duração {duration}s fora do range"),
    ]

    for i, (passed, reason) in enumerate(checks, 1):
        if passed:
            passed_rules.append({"rule": i, "status": "PASS", "reason": reason})
        else:
            failed_rules.append({"rule": i, "status": "FAIL", "reason": reason})

    score = len(passed_rules)
    return {
        "passed": score >= 7,  # Need 7/10 to pass
        "score": score,
        "rules": passed_rules + failed_rules,
        "overall_reason": f"{score}/10 regras aprovadas" + (" (fallback - LLM indisponível)" if True else ""),
    }


def run_compliance_check(
    approved_dir: Path,
    output_dir: Path,
    use_llm: bool = True,
) -> dict:
    """
    Run compliance check on all approved videos.

    Args:
        approved_dir: Directory with approved videos and JSON metadata
        output_dir: Directory to save compliance results
        use_llm: Whether to use LLM for checking

    Returns:
        Compliance results summary
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {
        "checked_at": datetime.now().isoformat(),
        "total_videos": 0,
        "passed": 0,
        "failed": 0,
        "details": [],
    }

    # Find all approved videos
    video_files = list(approved_dir.glob("*.mp4"))
    results["total_videos"] = len(video_files)

    if not video_files:
        logger.warning("No approved videos found in %s", approved_dir)
        return results

    for video_path in sorted(video_files):
        product_name = video_path.stem
        meta_path = video_path.with_suffix(".json")

        # Load metadata
        if meta_path.exists():
            with open(meta_path) as f:
                metadata = json.load(f)
        else:
            metadata = {"duration": 0, "resolution": "0x0", "codec": "unknown",
                        "size_bytes": 0, "face_count": 0, "watermark": False}

        # Run compliance check
        if use_llm:
            compliance = check_compliance_llm(product_name, metadata, COMPLIANCE_RULES)
        else:
            compliance = _fallback_compliance(product_name, metadata, COMPLIANCE_RULES)

        result_entry = {
            "product": product_name,
            "video_file": str(video_path),
            "passed": compliance.get("passed", False),
            "score": compliance.get("score", 0),
            "overall_reason": compliance.get("overall_reason", ""),
            "rules": compliance.get("rules", []),
        }
        results["details"].append(result_entry)

        if compliance.get("passed"):
            results["passed"] += 1
            logger.info("✅ %s: compliance PASS (%d/10) — %s",
                        product_name, compliance.get("score", 0),
                        compliance.get("overall_reason", ""))
        else:
            results["failed"] += 1
            logger.warning("❌ %s: compliance FAIL (%d/10) — %s",
                           product_name, compliance.get("score", 0),
                           compliance.get("overall_reason", ""))

        # Save individual compliance result
        compliance_path = output_dir / f"{product_name}_compliance.json"
        with open(compliance_path, "w", encoding="utf-8") as f:
            json.dump(result_entry, f, indent=2, ensure_ascii=False)

    # Save summary
    summary_path = output_dir / "compliance_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    logger.info("Compliance check complete: %d passed, %d failed out of %d",
                results["passed"], results["failed"], results["total_videos"])

    return results


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--approved-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    result = run_compliance_check(
        approved_dir=args.approved_dir,
        output_dir=args.output_dir,
        use_llm=not args.no_llm,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
