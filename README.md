# Shopee Videos Pipeline — Agente de Curadoria para Afiliados

Pipeline automatizado de 7 etapas para curadoria de videos de produtos Shopee (nicho tech + gadgets adjacentes), otimizado para afiliados brasileiros.

## Pipeline de 7 Etapas

| Etapa | Descricao | Ferramenta |
|---|---|---|
| 1. Analise de tendencias | Detecta produtos em alta (EUA -> BR) | pytrends, API |
| 2. Busca de videos | Encontra videos com licencia comercial | Pexels, Pixabay, Coverr, Mixkit |
| 3. Filtro visual | Rejeita videos com rosto, watermark, baixa resolucao | OpenCV, YOLOv8-face, Tesseract OCR |
| 4. Download | Baixa em MP4, maxima resolucao | yt-dlp, FFmpeg |
| 5. Conformidade | Verifica 10 regras de conteudo proibido | qwen3.6-plus + regras locais |
| 6. Link afiliado | Gera link via API oficial | shpee |
| 7. Legenda | Copy em PT-BR otimizada para conversao | qwen3.6-plus |

## Estrutura de Output

Os arquivos são organizados por data em `/mnt/user/data/shopee_execute/`:

```
/mnt/user/data/shopee_execute/
├── data.db                          # DB de engagement (persiste entre runs)
├── logs/
│   └── pipeline.log
├── 2026-06-02/                      # Pasta do dia
│   ├── pipeline_meta.json           # Metadata da execução
│   ├── trends/
│   │   └── 2026-06-02.json          # Produtos ranqueados
│   ├── raw_videos/                  # Videos baixados
│   ├── approved/                    # Videos aprovados + links
│   │   └── produto_link.txt
│   ├── links/
│   │   └── produto_meta.json
│   ├── rejected/                    # Videos rejeitados
│   └── reports/                     # Relatorios
```

## Requisitos

- Python 3.11+
- FFmpeg
- Tesseract OCR
- Docker (opcional)

## Setup Rapido

### Com Docker

```bash
# 1. Clonar repositorio
git clone <repo-url>
cd shopee-videos-pipeline

# 2. Configurar credenciais
cp .env.example .env
# Edite .env com suas credenciais da Shopee Affiliate API

# 3. Build da imagem
docker compose build

# 4. Subir container (manual, sem cron)
docker compose up -d

# 5. Executar pipeline manualmente
docker exec shopee-pipeline python main.py

# 6. Dry-run primeiro
docker exec shopee-pipeline python main.py --dry-run

# 7. Executar etapa específica
docker exec shopee-pipeline python main.py --step 1

# 8. Override de data
docker exec shopee-pipeline python main.py --date 2026-06-01
```

### Local (sem Docker)

```bash
# 1. Instalar dependencias do sistema
# Ubuntu/Debian:
sudo apt install ffmpeg tesseract-ocr tesseract-ocr-por

# macOS:
brew install ffmpeg tesseract

# 2. Criar ambiente virtual
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Instalar dependencias Python
pip install -r requirements.txt

# 4. Configurar credenciais
cp .env.example .env
# Edite .env com SHOPEE_APP_ID e SHOPEE_APP_SECRET

# 5. Executar
python main.py --dry-run   # validacao sem downloads
python main.py             # producao
python main.py --step 1    # apenas trends
python main.py --date 2026-06-01  # pasta especifica
```

## Credenciais

Obtenha suas credenciais no [Shopee Affiliate Program](https://affiliate.shopee.com.br/):

| Variavel | Descricao |
|---|---|
| SHOPEE_APP_ID | ID do aplicativo na API de afiliados |
| SHOPEE_APP_SECRET | Chave secreta do aplicativo |

Nunca compartilhe ou commite essas credenciais.

## Estrutura do Projeto

```
shopee-videos-pipeline/
├── config.yaml          # Configuração central
├── config/prompts/      # Templates de prompts para IA
├── main.py              # Entry point
├── trends_analyzer.py   # Etapa 1: tendencias
├── affiliate_linker.py  # Etapa 6: links de afiliado
├── requirements.txt     # Dependencias Python
├── Dockerfile           # Imagem Docker
├── docker-compose.yml   # Compose para deploy
├── entrypoint.sh        # Container entry (manual mode)
├── .env.example         # Template de variaveis de ambiente
└── .gitignore
```

## Configuracao

Edite `config.yaml` para ajustar:
- `storage_root`: diretorio base (padrao: `/mnt/user/data/shopee_execute`)
- Pesos de analise de tendencias
- Fontes de video (Tier 1)
- Regras de conformidade
- Thresholds de qualidade
- Configuracoes de legenda (emojis, hashtags, CTA)
- Nicho e keywords

## Regras de Conformidade (10 itens)

1. Sem conteudo adulto
2. Sem violencia ou gore
3. Sem discurso de odio
4. Sem alegacoes medicas
5. Sem marcas falsificadas
6. Sem substancias ilegais
7. Sem jogos de azar
8. Sem golpes financeiros
9. Sem antes/depois enganoso
10. Sem links externos nas legendas

## Licenca

Uso interno para afiliados Shopee. Videos devem ter licencia comercial verificada.
