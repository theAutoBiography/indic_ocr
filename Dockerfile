FROM public.ecr.aws/lambda/python:3.11

# Install system dependencies for Tesseract and OpenCV
RUN yum update -y && \
    yum install -y \
    tesseract \
    tesseract-langpack-eng \
    poppler-utils \
    wget \
    && yum clean all

# Install additional Tesseract language data for Sanskrit and Hindi
RUN cd /usr/share/tesseract/tessdata && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/san.traineddata && \
    wget -q https://github.com/tesseract-ocr/tessdata/raw/main/hin.traineddata

# Set Tesseract data path
ENV TESSDATA_PREFIX=/usr/share/tesseract/tessdata

# Copy requirements file
COPY requirements.txt ${LAMBDA_TASK_ROOT}/

# Install Python dependencies
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy application code
COPY app.py ${LAMBDA_TASK_ROOT}/
COPY lambda_handler.py ${LAMBDA_TASK_ROOT}/
COPY config.py ${LAMBDA_TASK_ROOT}/
COPY ocr_processor.py ${LAMBDA_TASK_ROOT}/
COPY aws_service.py ${LAMBDA_TASK_ROOT}/
COPY templates/ ${LAMBDA_TASK_ROOT}/templates/

# Create upload directory
RUN mkdir -p ${LAMBDA_TASK_ROOT}/uploads

# Set the Lambda handler
CMD [ "lambda_handler.handler" ]
