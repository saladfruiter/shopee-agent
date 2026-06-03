FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files + unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies (runtime only)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-por \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Runtime directories are created by main.py under /mnt/user/data/shopee_execute/YYYY-MM-DD/
# Only create app-local dirs for code/config
RUN mkdir -p config/prompts

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Set environment (override with docker run -e or .env)
ENV SHOPEE_APP_ID=""
ENV SHOPEE_APP_SECRET=""
ENV TZ=America/Sao_Paulo

# Entrypoint: keeps container alive for manual execution
ENTRYPOINT ["/app/entrypoint.sh"]
