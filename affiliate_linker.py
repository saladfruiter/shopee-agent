#!/usr/bin/env python3
"""
affiliate_linker.py — Módulo de links de afiliado Shopee (Etapa 6 do pipeline)

Integração com API shpee para gerar links curtos de afiliado.
Fallback: importação CSV do painel Shopee caso API falhe.
Retry 3x com backoff exponencial + graceful degradation.

Uso:
    python affiliate_linker.py --url "https://shopee.com.br/produto-i.123.456" --product "Headphones" --source "google-trends"
    python affiliate_linker.py --csv painel_shopee_links.csv
    python affiliate_linker.py --trends trends/2026-05-27.json --top 5
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

try:
    from shpee import ShopeeAffiliate
except (ImportError, ModuleNotFoundError):
    # shpee pode falhar se httpx for incompatível (cgi removido no Python 3.13)
    ShopeeAffiliate = None

# ── Config ──────────────────────────────────────────────────────────────

STORAGE_ROOT = os.environ.get(
    "SHOPEE_STORAGE_ROOT",
    "/mnt/user/data/shopee-agent"
)
APPROVED_DIR = Path(STORAGE_ROOT) / "approved"
LINKS_DIR = Path(STORAGE_ROOT) / "links"
CSV_BACKUP_DIR = Path(STORAGE_ROOT) / "csv_backup"

RETRY_MAX_ATTEMPTS = int(os.environ.get("RETRY_MAX_ATTEMPTS", "3"))
RETRY_BASE_DELAY = float(os.environ.get("RETRY_BASE_DELAY", "2"))
RETRY_BACKOFF_MULTIPLIER = float(os.environ.get("RETRY_BACKOFF_MULTIPLIER", "2"))

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("affiliate_linker")


# ── Helpers ─────────────────────────────────────────────────────────────

def ensure_dirs():
    """Cria diretórios necessários se não existirem."""
    for d in [APPROVED_DIR, LINKS_DIR, CSV_BACKUP_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def slugify(text: str) -> str:
    """Converte nome de produto em slug seguro para filename."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text[:80].rstrip("-") or "unknown"


def extract_product_id(url: str) -> str:
    """Extrai ID do produto da URL Shopee.

    Exemplo: https://shopee.com.br/Fone-Bluetooth-i.12345678.987654321
    Retorna: 12345678.987654321 (shop_id.item_id)
    """
    # Padrão Shopee: -i.{shop_id}.{item_id} ou /i.{shop_id}.{item_id}
    match = re.search(r"[-/]i\.(\d+)\.(\d+)", url)
    if match:
        return f"{match.group(1)}.{match.group(2)}"

    # Fallback: tenta extrair qualquer número longo da URL
    parts = urlparse(url)
    path = parts.path
    # Remove prefixos comuns
    path = re.sub(r"/product[-/]", "", path)
    # Tenta encontrar pattern shop_id.item_id
    match = re.search(r"(\d{6,})\.(\d{6,})", path)
    if match:
        return f"{match.group(1)}.{match.group(2)}"

    return None


# ── Retry decorator ────────────────────────────────────────────────────

def retry_with_backoff(func, *args, max_attempts=RETRY_MAX_ATTEMPTS,
                       base_delay=RETRY_BASE_DELAY, multiplier=RETRY_BACKOFF_MULTIPLIER, **kwargs):
    """Executa func com retry exponencial. Retorna (success, result_or_error)."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = func(*args, **kwargs)
            return True, result
        except Exception as e:
            last_error = e
            logger.warning(
                "Tentativa %d/%d falhou: %s",
                attempt, max_attempts, e
            )
            if attempt < max_attempts:
                delay = base_delay * (multiplier ** (attempt - 1))
                logger.info("Aguardando %.1fs antes de retry...", delay)
                time.sleep(delay)

    return False, last_error


# ── API Linker ──────────────────────────────────────────────────────────

class AffiliateLinker:
    """Gera links de afiliado Shopee via API shpee ou CSV fallback."""

    def __init__(self, app_id: str = None, app_secret: str = None):
        self.app_id = app_id or os.environ.get("SHOPEE_APP_ID", "")
        self.app_secret = app_secret or os.environ.get("SHOPEE_APP_SECRET", "")
        self.client = None
        self._init_client()

    def _init_client(self):
        """Inicializa cliente shpee se credenciais disponíveis."""
        if ShopeeAffiliate is None:
            logger.error("Pacote 'shpee' não instalado. pip install shpee")
            return
        if not self.app_id or not self.app_secret:
            logger.warning(
                "Credenciais Shopee ausentes. Defina SHOPEE_APP_ID e SHOPEE_APP_SECRET. "
                "Usando modo CSV fallback."
            )
            return
        try:
            self.client = ShopeeAffiliate(
                app_id=self.app_id,
                app_secret=self.app_secret
            )
            logger.info("Cliente ShopeeAffiliate inicializado com sucesso.")
        except Exception as e:
            logger.error("Falha ao inicializar ShopeeAffiliate: %s", e)

    def generate_link(self, product_url: str, product_name: str,
                      source: str = "unknown") -> dict:
        """Gera link de afiliado para um produto.

        Args:
            product_url: URL completa do produto Shopee
            product_name: Nome do produto (para slug e sub_ids)
            source: Fonte de origem (google-trends, rss, etc.)

        Returns:
            dict com status, affiliate_link, product_id, method, saved_path
        """
        ensure_dirs()
        product_id = extract_product_id(product_url) or slugify(product_name)
        slug = slugify(product_name)
        sub_ids = [slug, source]

        result = {
            "product_name": product_name,
            "product_url": product_url,
            "product_id": product_id,
            "sub_ids": sub_ids,
            "affiliate_link": None,
            "method": None,
            "saved_path": None,
            "error": None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # ── Tentativa 1: API shpee ─────────────────────────────────
        if self.client:
            def _api_call():
                return self.client.shortlink(product_url, sub_ids=sub_ids)

            ok, resp_or_err = retry_with_backoff(_api_call)
            if ok:
                try:
                    data = resp_or_err.json()
                    # O GraphQL retorna { "data": { "generateShortLink": { "shortLink": "..." } } }
                    short_link = (
                        data.get("data", {})
                        .get("generateShortLink", {})
                        .get("shortLink")
                    )
                    if short_link:
                        result["affiliate_link"] = short_link
                        result["method"] = "shpee_api"
                        logger.info(
                            "Link gerado via API: %s -> %s", product_name, short_link
                        )
                    else:
                        result["error"] = f"Resposta API sem shortLink: {data}"
                        logger.warning("Resposta API sem shortLink: %s", data)
                except Exception as e:
                    result["error"] = f"Erro parsing resposta API: {e}"
                    logger.warning("Erro ao parsear resposta API: %s", e)

        # ── Fallback: verificar se já existe link salvo ────────────
        if not result["affiliate_link"]:
            existing_link = self._load_saved_link(product_id)
            if existing_link:
                result["affiliate_link"] = existing_link
                result["method"] = "cached"
                logger.info("Link carregado do cache: %s", product_name)

        # ── Fallback: CSV ──────────────────────────────────────────
        if not result["affiliate_link"]:
            csv_link = self._search_csv(product_url, product_id)
            if csv_link:
                result["affiliate_link"] = csv_link
                result["method"] = "csv_fallback"
                logger.info("Link encontrado via CSV fallback: %s", product_name)

        # ── Salvar se conseguiu link ───────────────────────────────
        if result["affiliate_link"]:
            save_path = self._save_link(result)
            result["saved_path"] = str(save_path)
        else:
            result["error"] = (
                result.get("error") or
                "Falha em todos os métodos (API, cache, CSV). "
                "Verifique credenciais SHOPEE_APP_ID/SECRET ou importe CSV do painel."
            )
            logger.error("Nenhum método conseguiu gerar link para %s: %s", product_name, result["error"])

        return result

    def _save_link(self, result: dict) -> Path:
        """Salva link em approved/product-XXX_link.txt."""
        slug = slugify(result["product_name"])
        filename = f"{slug}_link.txt"

        # Salva em approved/
        approved_path = APPROVED_DIR / filename
        with open(approved_path, "w", encoding="utf-8") as f:
            f.write(result["affiliate_link"])

        # Salva metadata JSON em links/
        meta_path = LINKS_DIR / f"{slug}_meta.json"
        meta = {
            k: v for k, v in result.items()
            if k not in ("saved_path",)
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        logger.info("Link salvo em %s", approved_path)
        return approved_path

    def _load_saved_link(self, product_id: str) -> Optional[str]:
        """Carrega link salvo anteriormente (cache local)."""
        # Busca em links/ por qualquer arquivo que contenha o product_id
        if not LINKS_DIR.exists():
            return None
        for meta_file in LINKS_DIR.glob("*_meta.json"):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("product_id") == product_id and meta.get("affiliate_link"):
                    return meta["affiliate_link"]
            except (json.JSONDecodeError, IOError):
                continue
        return None

    def _search_csv(self, product_url: str, product_id: str) -> Optional[str]:
        """Busca link em arquivos CSV importados do painel Shopee."""
        if not CSV_BACKUP_DIR.exists():
            return None

        for csv_file in CSV_BACKUP_DIR.glob("*.csv"):
            link = self._parse_csv(csv_file, product_url, product_id)
            if link:
                return link
        return None

    def _parse_csv(self, csv_path: Path, product_url: str,
                   product_id: str) -> Optional[str]:
        """Parseia CSV do painel Shopee buscando produto por URL ou ID.

        Formato esperado (adaptável):
        - Colunas comuns: product_url, affiliate_link, product_id, product_name
        - Ou: link_original, link_afiliado
        - Ou colunas posicionais (tenta detectar)
        """
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                # Detecta separador
                sample = f.read(4096)
                f.seek(0)

                delimiter = ","
                if ";" in sample.split("\n")[0]:
                    delimiter = ";"

                reader = csv.DictReader(f, delimiter=delimiter)

                # Normaliza nomes de colunas
                if reader.fieldnames:
                    reader.fieldnames = [
                        name.strip().lower().replace(" ", "_")
                        for name in reader.fieldnames
                    ]

                for row in reader:
                    row_lower = {k: (v or "").strip().lower() for k, v in row.items()}

                    # Busca por URL exata ou parcial
                    for key in ("product_url", "url", "link_original", "url_produto"):
                        if key in row_lower and row_lower[key]:
                            if (product_url.lower() in row_lower[key] or
                                    row_lower[key] in product_url.lower()):
                                return self._extract_link_from_row(row)

                    # Busca por product_id
                    for key in ("product_id", "item_id", "id_produto"):
                        if key in row_lower and row_lower[key]:
                            if str(product_id) in row_lower[key]:
                                return self._extract_link_from_row(row)

        except Exception as e:
            logger.warning("Erro ao parsear CSV %s: %s", csv_path, e)

        return None

    def _extract_link_from_row(self, row: dict) -> Optional[str]:
        """Extrai link de afiliado de uma linha CSV."""
        for key in ("affiliate_link", "link_afiliado", "short_link",
                     "link_afiliado_shopee", "shopee_link"):
            if key in row and row[key] and row[key].strip():
                return row[key].strip()
        return None

    def import_csv(self, csv_path: str) -> dict:
        """Importa CSV do painel Shopee e salva links em approved/.

        Args:
            csv_path: Caminho para arquivo CSV exportado do painel

        Returns:
            dict com stats de importação
        """
        ensure_dirs()
        csv_path = Path(csv_path)
        if not csv_path.exists():
            return {"error": f"Arquivo não encontrado: {csv_path}"}

        # Copia para csv_backup/
        backup_path = CSV_BACKUP_DIR / csv_path.name
        shutil.copy2(csv_path, backup_path)

        stats = {
            "total_rows": 0,
            "links_found": 0,
            "links_saved": 0,
            "errors": [],
            "csv_path": str(backup_path),
        }

        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                sample = f.read(4096)
                f.seek(0)

                delimiter = ","
                if ";" in sample.split("\n")[0]:
                    delimiter = ";"

                reader = csv.DictReader(f, delimiter=delimiter)
                if reader.fieldnames:
                    reader.fieldnames = [
                        name.strip().lower().replace(" ", "_")
                        for name in reader.fieldnames
                    ]

                for row in reader:
                    stats["total_rows"] += 1
                    link = self._extract_link_from_row(row)
                    if link:
                        stats["links_found"] += 1
                        # Tenta extrair nome do produto
                        product_name = "unknown"
                        for key in ("product_name", "nome_produto", "name"):
                            if key in row and row[key]:
                                product_name = row[key].strip()
                                break

                        # Salva link
                        slug = slugify(product_name)
                        filename = f"{slug}_link.txt"
                        approved_path = APPROVED_DIR / filename
                        with open(approved_path, "w", encoding="utf-8") as f:
                            f.write(link)
                        stats["links_saved"] += 1

                        # Salva metadata
                        meta_path = LINKS_DIR / f"{slug}_meta.json"
                        meta = {
                            "product_name": product_name,
                            "affiliate_link": link,
                            "method": "csv_import",
                            "source_csv": str(backup_path),
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                        }
                        with open(meta_path, "w", encoding="utf-8") as f:
                            json.dump(meta, f, indent=2, ensure_ascii=False)

        except Exception as e:
            stats["errors"].append(str(e))
            logger.error("Erro ao importar CSV: %s", e)

        logger.info(
            "CSV importado: %d linhas, %d links encontrados, %d salvos",
            stats["total_rows"], stats["links_found"], stats["links_saved"]
        )
        return stats


# ── Process trends JSON ────────────────────────────────────────────────

def process_trends(trends_path: str, top: int = 5, app_id: str = None,
                   app_secret: str = None) -> list:
    """Processa produtos do arquivo de tendências e gera links.

    Args:
        trends_path: Caminho para JSON de tendências (ex: trends/2026-05-27.json)
        top: Número de produtos top para processar
        app_id: Shopee App ID (override env)
        app_secret: Shopee App Secret (override env)

    Returns:
        Lista de resultados por produto
    """
    linker = AffiliateLinker(app_id=app_id, app_secret=app_secret)
    results = []

    trends_path = Path(trends_path)
    if not trends_path.exists():
        logger.error("Arquivo de tendências não encontrado: %s", trends_path)
        return results

    with open(trends_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    products = data.get("ranked_products", [])[:top]

    if not products:
        logger.warning("Nenhum produto encontrado em %s", trends_path)
        return results

    # Nota: O trends_analyzer gera produtos genéricos (nomes de keywords),
    # não URLs Shopee reais. Este módulo precisa de URLs Shopee válidas.
    # Aqui geramos um aviso e tentamos buscar URLs se possível.
    for product in products:
        product_name = product.get("name", "unknown")
        score = product.get("score", 0)

        # Sem URL real, não é possível gerar link de afiliado
        # Em produção, a busca de vídeos (Etapa 2) encontraria URLs reais
        logger.warning(
            "Produto '%s' (score=%.2f) sem URL Shopee. "
            "Links de afiliado requerem URLs reais de produtos Shopee.",
            product_name, score
        )

        results.append({
            "product_name": product_name,
            "score": score,
            "affiliate_link": None,
            "error": "URL Shopee não disponível nos dados de tendência",
            "method": None,
        })

    return results


# ── CLI ────────────────────────────────────────────────────────────────

def main():
    """CLI para gerar links de afiliado."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Gerar links de afiliado Shopee (Etapa 6 do pipeline)"
    )
    parser.add_argument(
        "--url", type=str,
        help="URL do produto Shopee"
    )
    parser.add_argument(
        "--product", type=str, default="produto",
        help="Nome do produto"
    )
    parser.add_argument(
        "--source", type=str, default="manual",
        help="Fonte de origem (google-trends, rss, etc.)"
    )
    parser.add_argument(
        "--csv", type=str,
        help="Importar CSV do painel Shopee"
    )
    parser.add_argument(
        "--trends", type=str,
        help="Processar produtos do arquivo de tendências JSON"
    )
    parser.add_argument(
        "--top", type=int, default=5,
        help="Número de produtos top do trends (padrão: 5)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Modo dry-run: simula sem chamar API"
    )

    args = parser.parse_args()

    if not any([args.url, args.csv, args.trends]):
        parser.print_help()
        sys.exit(1)

    # Dry-run mode
    if args.dry_run:
        logger.info("=== MODO DRY-RUN ===")
        if args.url:
            logger.info("URL: %s", args.url)
            logger.info("Produto: %s", args.product)
            logger.info("Fonte: %s", args.source)
            product_id = extract_product_id(args.url)
            logger.info("Product ID extraído: %s", product_id or "(não identificado)")
            slug = slugify(args.product)
            logger.info("Slug: %s", slug)
            expected_path = APPROVED_DIR / f"{slug}_link.txt"
            logger.info("Path esperado: %s", expected_path)
            print(json.dumps({
                "dry_run": True,
                "product_name": args.product,
                "product_url": args.url,
                "product_id": product_id,
                "slug": slug,
                "expected_output": str(expected_path),
            }, indent=2))
        elif args.csv:
            logger.info("CSV para importar: %s", args.csv)
            csv_path = Path(args.csv)
            logger.info("Existe: %s", csv_path.exists())
            print(json.dumps({
                "dry_run": True,
                "csv_path": args.csv,
                "exists": csv_path.exists(),
            }, indent=2))
        elif args.trends:
            logger.info("Trends para processar: %s", args.trends)
            trends_path = Path(args.trends)
            logger.info("Existe: %s", trends_path.exists())
            print(json.dumps({
                "dry_run": True,
                "trends_path": args.trends,
                "exists": trends_path.exists(),
                "top": args.top,
            }, indent=2))
        return

    # Import CSV
    if args.csv:
        linker = AffiliateLinker()
        stats = linker.import_csv(args.csv)
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return

    # Process trends
    if args.trends:
        results = process_trends(args.trends, top=args.top)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return

    # Generate single link
    linker = AffiliateLinker()
    result = linker.generate_link(args.url, args.product, args.source)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # Exit code: 0 = sucesso, 1 = falha
    if result.get("affiliate_link"):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
