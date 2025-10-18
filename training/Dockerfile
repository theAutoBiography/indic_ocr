# Training Dockerfile for Vision Language Model (VLM)
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y \
    wget \
    git \
    build-essential \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install app requirements first (for better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy and install training requirements
COPY training/requirements.txt ./training/
RUN pip install --no-cache-dir -r training/requirements.txt

# Copy shared source code (for AWS service, config, etc.)
COPY src/ /app/src/

# Copy training scripts
COPY training/scripts/ /app/training/scripts/

# Set working directory
WORKDIR /app/training/scripts

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CLEANUP_AFTER_TRAINING=true
ENV TRANSFORMERS_CACHE=/tmp/transformers_cache
ENV HF_HOME=/tmp/huggingface

# Default command runs the VLM training script
CMD ["python3", "train_vlm.py"]
