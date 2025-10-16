FROM public.ecr.aws/lambda/python:3.11

# Install basic dependencies first
RUN yum install -y \
    wget \
    tar \
    gzip \
    gcc \
    gcc-c++ \
    make \
    && yum clean all

# Try to install development libraries if available (optional for some packages)
RUN yum install -y libffi-devel || echo "libffi-devel not available" && \
    yum install -y openssl-devel || echo "openssl-devel not available" && \
    yum clean all

# Install poppler-utils for PDF support
RUN yum install -y poppler-utils || yum install -y poppler && yum clean all

# Install Tesseract from EPEL (Amazon Linux 2)
RUN amazon-linux-extras install epel -y && \
    yum install -y tesseract && \
    yum clean all

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
