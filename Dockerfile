FROM public.ecr.aws/lambda/python:3.10

# Install system dependencies for Tesseract and OpenCV
# Enable EPEL repo for tesseract on Amazon Linux 2
RUN yum update -y && \
    yum install -y \
    amazon-linux-extras \
    && amazon-linux-extras install epel -y && \
    yum install -y \
    tesseract \
    poppler-utils \
    wget \
    gcc \
    gcc-c++ \
    && yum clean all

# Verify tesseract installation
RUN which tesseract && tesseract --version

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
