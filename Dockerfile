FROM public.ecr.aws/lambda/python:3.11

# Install system dependencies for Tesseract and OpenCV
RUN yum update -y && \
    yum install -y \
    tesseract \
    tesseract-langpack-eng \
    poppler-utils \
    wget \
    gcc \
    gcc-c++ \
    cmake \
    libffi-devel \
    openssl-devel \
    && yum clean all

# Create tessdata directory if it doesn't exist and install Indic language data
RUN mkdir -p /usr/share/tesseract/tessdata && \
    cd /usr/share/tesseract/tessdata && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/san.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/hin.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/tam.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/kan.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/tel.traineddata || true

# Set Tesseract data path
ENV TESSDATA_PREFIX=/usr/share/tesseract/tessdata

# Copy requirements file
COPY requirements.txt ${LAMBDA_TASK_ROOT}/

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy application code
COPY src/ ${LAMBDA_TASK_ROOT}/src/
COPY templates/ ${LAMBDA_TASK_ROOT}/templates/

# Create upload directory
RUN mkdir -p ${LAMBDA_TASK_ROOT}/uploads

# Set the Lambda handler
CMD [ "src.lambda_handler.handler" ]
