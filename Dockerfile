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

# Create runtime directories
RUN mkdir -p trends raw_videos approved rejected reports config/prompts logs

# Set environment (override with docker run -e)
ENV SHOPEE_APP_ID=""
ENV SHOPEE_APP_SECRET=""

# Default entrypoint
CMD ["python", "main.py"]
