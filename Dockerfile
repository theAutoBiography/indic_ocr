# Stage 1: Get Tesseract from Ubuntu
FROM ubuntu:20.04 AS tesseract-build
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
    tesseract-ocr \
    libtesseract-dev && \
    rm -rf /var/lib/apt/lists/*

# Stage 2: Lambda runtime with Tesseract
FROM public.ecr.aws/lambda/python:3.11

# Install basic dependencies
RUN yum update -y && \
    yum install -y \
    poppler-utils \
    wget \
    gcc \
    gcc-c++ \
    && yum clean all

# Copy tesseract binaries and libraries from Ubuntu build
COPY --from=tesseract-build /usr/bin/tesseract /opt/bin/tesseract
COPY --from=tesseract-build /usr/lib/x86_64-linux-gnu/libtesseract.so* /opt/lib/
COPY --from=tesseract-build /usr/lib/x86_64-linux-gnu/liblept.so* /opt/lib/
COPY --from=tesseract-build /usr/lib/x86_64-linux-gnu/libgomp.so* /opt/lib/
COPY --from=tesseract-build /usr/share/tesseract-ocr /opt/share/tesseract-ocr

# Add tesseract to PATH and set library path
ENV PATH="/opt/bin:${PATH}"
ENV LD_LIBRARY_PATH="/opt/lib:${LD_LIBRARY_PATH}"

# Download Indic language data
RUN mkdir -p /opt/share/tesseract-ocr/4.00/tessdata && \
    cd /opt/share/tesseract-ocr/4.00/tessdata && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/san.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/hin.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/tam.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/kan.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/tel.traineddata || true

# Set Tesseract data path
ENV TESSDATA_PREFIX=/opt/share/tesseract-ocr/4.00/tessdata

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
