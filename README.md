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
docker build -t shopee-pipeline .

# 4. Executar (dry-run primeiro)
docker run --rm -v $(pwd)/data:/app/data \
  --env-file .env \
  shopee-pipeline python main.py --dry-run

# 5. Executar producao
docker run --rm -v $(pwd)/data:/app/data \
  --env-file .env \
  shopee-pipeline python main.py
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
├── trends/              # Dados de tendencias (JSON)
├── raw_videos/          # Videos baixados (brutos)
├── approved/            # Videos aprovados + metadata
├── rejected/            # Videos rejeitados + motivo (auto-delete 7 dias)
├── reports/             # Relatorios de execucao
├── logs/                # Logs do pipeline
├── scripts/             # Scripts auxiliares
├── main.py              # Entry point
├── requirements.txt     # Dependencias Python
├── Dockerfile           # Imagem Docker
├── .env.example         # Template de variaveis de ambiente
└── .gitignore
```

## Configuracao

Edite `config.yaml` para ajustar:
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
