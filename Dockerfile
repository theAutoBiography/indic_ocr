FROM public.ecr.aws/lambda/python:3.11

# Install build dependencies AND runtime libraries
RUN yum update -y && \
    yum install -y \
    autoconf \
    automake \
    libtool \
    pkgconfig \
    libpng-devel \
    libjpeg-devel \
    libtiff-devel \
    zlib-devel \
    libpng \
    libjpeg \
    libtiff \
    zlib \
    libstdc++ \
    libgomp \
    poppler-utils \
    wget \
    gcc \
    gcc-c++ \
    && yum clean all

# Build and install Leptonica (required by Tesseract)
RUN cd /tmp && \
    wget https://github.com/DanBloomberg/leptonica/releases/download/1.84.1/leptonica-1.84.1.tar.gz && \
    tar -xzf leptonica-1.84.1.tar.gz && \
    cd leptonica-1.84.1 && \
    ./configure --prefix=/opt && \
    make -j$(nproc) && \
    make install && \
    cd / && \
    rm -rf /tmp/leptonica-1.84.1*

# Build and install Tesseract
RUN cd /tmp && \
    wget https://github.com/tesseract-ocr/tesseract/archive/refs/tags/5.3.3.tar.gz && \
    tar -xzf 5.3.3.tar.gz && \
    cd tesseract-5.3.3 && \
    ./autogen.sh && \
    PKG_CONFIG_PATH=/opt/lib/pkgconfig ./configure --prefix=/opt LDFLAGS="-L/opt/lib" CFLAGS="-I/opt/include" && \
    make -j$(nproc) && \
    make install && \
    cd / && \
    rm -rf /tmp/tesseract-5.3.3 /tmp/5.3.3.tar.gz

# Add tesseract to PATH and set library paths
ENV PATH="/opt/bin:${PATH}"
ENV LD_LIBRARY_PATH="/opt/lib:${LD_LIBRARY_PATH}"

# Verify tesseract installation and check library dependencies
RUN echo "Checking tesseract binary..." && \
    ldd /opt/bin/tesseract || echo "ldd failed or not available" && \
    /opt/bin/tesseract --version || echo "Tesseract version check failed"

# Download Indic language data
RUN mkdir -p /opt/share/tessdata && \
    cd /opt/share/tessdata && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/san.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/hin.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/tam.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/kan.traineddata || true && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/tel.traineddata || true

# Set Tesseract data path
ENV TESSDATA_PREFIX=/opt/share/tessdata

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
