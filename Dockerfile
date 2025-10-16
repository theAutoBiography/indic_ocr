FROM public.ecr.aws/lambda/python:3.11

# Install basic dependencies
RUN yum update -y && \
    yum install -y \
    poppler-utils \
    wget \
    gcc \
    gcc-c++ \
    tar \
    xz \
    unzip \
    && yum clean all

# Install Tesseract from pre-built binary
# Using amazonlinux-tesseract layer approach - install directly in the image
RUN cd /tmp && \
    wget https://github.com/bweigel/aws-lambda-tesseract-layer/releases/download/v5.3.3/tesseract-v5.3.3-layer.zip && \
    unzip tesseract-v5.3.3-layer.zip -d /opt && \
    rm tesseract-v5.3.3-layer.zip && \
    chmod +x /opt/bin/tesseract

# Add tesseract to PATH
ENV PATH="/opt/bin:${PATH}"
ENV LD_LIBRARY_PATH="/opt/lib:${LD_LIBRARY_PATH}"

# Create tessdata directory if it doesn't exist and install Indic language data
RUN mkdir -p /opt/tessdata && \
    cd /opt/tessdata && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/san.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/hin.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/tam.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/kan.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/tel.traineddata || true

# Set Tesseract data path
ENV TESSDATA_PREFIX=/opt/tessdata

# Copy requirements file
COPY requirements.txt ${LAMBDA_TASK_ROOT}/

# Upgrade pip first
RUN pip install --upgrade pip

# Install Python dependencies one by one to identify failures
RUN pip install --no-cache-dir Flask==3.0.0
RUN pip install --no-cache-dir Flask-CORS==4.0.0
RUN pip install --no-cache-dir "Pillow>=10.2.0"
RUN pip install --no-cache-dir pytesseract==0.3.10
RUN pip install --no-cache-dir pdf2image==1.16.3
RUN pip install --no-cache-dir "boto3>=1.34.24"
RUN pip install --no-cache-dir "opencv-python-headless>=4.9.0.80"
RUN pip install --no-cache-dir "numpy>=1.26.3"
RUN pip install --no-cache-dir python-dotenv==1.0.0

# Copy application code
COPY src/ ${LAMBDA_TASK_ROOT}/src/
COPY templates/ ${LAMBDA_TASK_ROOT}/templates/

# Create upload directory
RUN mkdir -p ${LAMBDA_TASK_ROOT}/uploads

# Set the Lambda handler
CMD [ "src.lambda_handler.handler" ]
