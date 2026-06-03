#!/usr/bin/env python3
"""
Caption Generator — Etapa 7 do Pipeline Shopee Videos

Gera legendas em PT-BR para vídeos aprovados usando qwen3.6-plus via opencode-go.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("caption_generator")


def generate_caption_llm(product_name: str, video_metadata: dict, affiliate_link: str) -> dict:
    """
    Use qwen3.6-plus to generate a PT-BR caption.
    Returns {caption: str, hashtags: list, title: str}.
    """
    prompt = f"""Você é um especialista em marketing digital para Shopee Brasil.
Crie uma legenda atrativa em PT-BR para um vídeo de produto.

Produto: {product_name}
Duração do vídeo: {video_metadata.get('duration', '?')} segundos
Resolução: {video_metadata.get('resolution', '?')}
Link de afiliado: {affiliate_link or '(link pendente)'}

Crie:
1. Um título chamativo (máx 50 caracteres)
2. Uma legenda envolvente (2-3 frases, com emoji, CTA para comprar)
3. Hashtags relevantes (5-8 hashtags)

IMPORTANTE:
- Use linguagem natural de redes sociais brasileiras
- Inclua CTA claro ("Clique no link", "Compre agora", etc.)
- Seja autêntico, não robótico
- Use emojis relevantes mas não exagere

Retorne APENAS JSON:
{{
  "title": "título chamativo",
  "caption": "legenda completa com CTA e emojis",
  "hashtags": ["#hashtag1", "#hashtag2", ...],
  "full_post": "título\\n\\nlegenda\\n\\nhashtags\\n\\nlink"
}}"""

    try:
        result = subprocess.run(
            ["opencode", "chat", "--model", "qwen3.6-plus", "--stream=false", prompt],
            capture_output=True, text=True, timeout=60,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin"}
        )

        if result.returncode != 0:
            logger.warning("LLM caption failed: %s", result.stderr[:200])
            return _fallback_caption(product_name, affiliate_link)

        output = result.stdout.strip()
        if "```json" in output:
            output = output.split("```json")[1].split("```")[0].strip()
        elif "```" in output:
            output = output.split("```")[1].split("```")[0].strip()

        return json.loads(output)

    except Exception as e:
        logger.warning("LLM caption failed, using fallback: %s", e)
        return _fallback_caption(product_name, affiliate_link)


def _fallback_caption(product_name: str, affiliate_link: str) -> dict:
    """Fallback caption without LLM."""
    link_text = f"\n🔗 {affiliate_link}" if affiliate_link else "\n🔗 Link nos comentários"

    title = f"🔥 {product_name.title()} que você precisa!"
    caption = (
        f"Olha esse {product_name} incrível! 😍\n"
        f"Perfeito pro seu dia a dia. Qualidade top e preço acessível! 💯\n"
        f"Corre que o estoque é limitado! 🏃‍♂️💨\n"
        f"{link_text}"
    )
    hashtags = [
        f"#{product_name.replace(' ', '')}",
        "#ShopeeBrasil",
        "#AchadinhosShopee",
        "#TechGadgets",
        "#ComprasOnline",
        "#Ofertas",
    ]
    full_post = f"{title}\n\n{caption}\n\n{' '.join(hashtags)}"

    return {
        "title": title,
        "caption": caption,
        "hashtags": hashtags,
        "full_post": full_post,
    }


def generate_captions(
    videos: list[dict],
    affiliate_links: list[dict],
    output_dir: Path,
    config: dict = None,
    use_llm: bool = True,
) -> dict:
    """
    Generate PT-BR captions for compliant videos.

    Args:
        videos: List of compliant video entries
        affiliate_links: List of affiliate link entries
        output_dir: Directory to save captions
        config: Pipeline config
        use_llm: Whether to use LLM for caption generation

    Returns:
        Caption generation results
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if not videos:
        logger.warning("No compliant videos to generate captions for")
        return {"captions_generated": 0, "captions": []}

    # Build affiliate link lookup
    link_lookup = {}
    for link in (affiliate_links or []):
        product_name = link.get("product_name", "")
        link_url = link.get("affiliate_link", "")
        if product_name:
            link_lookup[product_name] = link_url

    captions = []
    for video in videos:
        product_name = video.get("product", "unknown")
        video_file = video.get("video_file", "")

        # Load video metadata
        meta_path = Path(video_file).with_suffix(".json")
        if meta_path.exists():
            with open(meta_path) as f:
                metadata = json.load(f)
        else:
            metadata = {"duration": 0, "resolution": "0x0"}

        # Get affiliate link
        affiliate_link = link_lookup.get(product_name, "")

        # Generate caption
        if use_llm:
            caption = generate_caption_llm(product_name, metadata, affiliate_link)
        else:
            caption = _fallback_caption(product_name, affiliate_link)

        caption_entry = {
            "product": product_name,
            "video_file": video_file,
            "title": caption.get("title", ""),
            "caption": caption.get("caption", ""),
            "hashtags": caption.get("hashtags", []),
            "full_post": caption.get("full_post", ""),
            "affiliate_link": affiliate_link,
            "generated_at": datetime.now().isoformat(),
        }
        captions.append(caption_entry)

        # Save individual caption
        from affiliate_linker import slugify
        slug = slugify(product_name)
        caption_path = output_dir / f"{slug}_caption.json"
        with open(caption_path, "w", encoding="utf-8") as f:
            json.dump(caption_entry, f, indent=2, ensure_ascii=False)

        logger.info("✅ Caption generated for %s", product_name)

    # Save summary
    summary = {
        "generated_at": datetime.now().isoformat(),
        "captions_generated": len(captions),
        "captions": captions,
    }
    summary_path = output_dir / "captions_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info("Generated %d captions", len(captions))
    return summary


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--videos", type=str, required=True, help="JSON with video list")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    with open(args.videos) as f:
        videos = json.load(f)

    result = generate_captions(
        videos=videos.get("details", videos) if isinstance(videos, dict) else videos,
        affiliate_links=[],
        output_dir=args.output_dir,
        use_llm=not args.no_llm,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
