# Use Python base with tesseract pre-installed, then add AWS Lambda adapter
FROM python:3.11-slim

# Install tesseract and dependencies
RUN apt-get update && \
    apt-get install -y \
    tesseract-ocr \
    poppler-utils \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install AWS Lambda Runtime Interface Client for Python
RUN pip install --no-cache-dir awslambdaric

# Copy requirements and install Python dependencies
WORKDIR /var/task
COPY requirements.txt .
RUN pip install --no-cache-dir Flask==3.0.0 \
    Flask-CORS==4.0.0 \
    "Pillow>=10.2.0" \
    pytesseract==0.3.10 \
    pdf2image==1.16.3 \
    "boto3>=1.34.24" \
    "opencv-python-headless>=4.9.0.80" \
    "numpy>=1.26.3" \
    python-dotenv==1.0.0 \
    apig-wsgi==2.18.0

# Download Indic language data
RUN mkdir -p /usr/share/tesseract-ocr/4.00/tessdata && \
    cd /usr/share/tesseract-ocr/4.00/tessdata && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/san.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/hin.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/tam.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/kan.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/tel.traineddata || true

# Set environment variables
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/4.00/tessdata

# Copy application code
COPY src/ /var/task/src/
COPY templates/ /var/task/templates/

# Create upload directory
RUN mkdir -p /var/task/uploads

# Set the handler
# For Lambda Function URLs, we need to ensure proper invocation
ENTRYPOINT []
CMD [ "python", "-m", "awslambdaric", "src.lambda_handler.handler" ]
