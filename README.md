# Drishti (दृष्टि)

**Document Vision & Recognition Platform**

A serverless OCR web application for processing images and PDFs with real-time text extraction. Features AWS Lambda deployment, S3 storage for low-confidence word/character images, and DynamoDB metadata storage. Optimized for Sanskrit, English, and Hindi.

## Features

- 📄 **File Upload**: Support for images (PNG, JPG, JPEG, TIFF, BMP) and PDF files up to 100MB
- 🔍 **OCR Processing**: Tesseract OCR with Sanskrit/Hindi/English support
- 📊 **Confidence Scoring**: Track and highlight low-confidence words
- ⚡ **Real-time Streaming**: Page-by-page results via Server-Sent Events (SSE)
- ☁️ **AWS Integration**: S3 storage + DynamoDB + Lambda
- 🎨 **Modern UI**: Responsive design with drag-and-drop upload
- 🚀 **Serverless**: Automated GitHub Actions deployment to AWS Lambda

## Quick Start

### Local Development

1. **Install Tesseract:**
   ```bash
   # macOS
   brew install tesseract tesseract-lang

   # Ubuntu
   sudo apt-get install tesseract-ocr tesseract-ocr-san tesseract-ocr-hin
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your AWS credentials
   ```

4. **Run:**
   ```bash
   python app.py
   ```

5. **Open:** http://localhost:5000

### AWS Lambda Deployment

#### One-Time Setup

1. **Create AWS resources:**
   ```bash
   # ECR repository
   aws ecr create-repository --repository-name drishti-ocr --region us-east-1

   # S3 buckets
   aws s3 mb s3://ocr-word-images
   aws s3 mb s3://ocr-char-images

   # DynamoDB table
   aws dynamodb create-table \
     --table-name ocr-results \
     --attribute-definitions AttributeName=id,AttributeType=S AttributeName=file_id,AttributeType=S \
     --key-schema AttributeName=id,KeyType=HASH \
     --global-secondary-indexes '[{"IndexName":"file_id-index","KeySchema":[{"AttributeName":"file_id","KeyType":"HASH"}],"Projection":{"ProjectionType":"ALL"}}]' \
     --billing-mode PAY_PER_REQUEST
   ```

2. **Create Lambda function** (via AWS Console):
   - Function name: `DrishtiOCR`
   - Package type: Container image
   - Memory: 3008 MB
   - Timeout: 900 seconds
   - Ephemeral storage: 2048 MB
   - Create Function URL with CORS enabled

3. **Set Lambda environment variables:**
   ```
   AWS_REGION=us-east-1
   S3_WORD_BUCKET=ocr-word-images
   S3_CHAR_BUCKET=ocr-char-images
   DYNAMODB_TABLE=ocr-results
   UPLOAD_FOLDER=/tmp/uploads
   TESSERACT_LANG=san+eng+hin
   ```

4. **Configure GitHub secrets:**
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`

#### Deploy

Push to main branch - GitHub Actions handles the rest:
```bash
git push origin main
```

GitHub Actions will:
- Build Docker image
- Push to ECR
- Update Lambda function
- Display Function URL

## Architecture

```
User → Lambda Function URL → Lambda (Container)
                                 ↓
                    ┌────────────┼────────────┐
                    ↓            ↓            ↓
                S3 Buckets   DynamoDB   Tesseract OCR
```

## Configuration

### Environment Variables

- `AWS_REGION`: AWS region (default: us-east-1)
- `S3_WORD_BUCKET`: S3 bucket for word images
- `S3_CHAR_BUCKET`: S3 bucket for character images
- `DYNAMODB_TABLE`: DynamoDB table name
- `TESSERACT_LANG`: OCR languages (default: san+eng+hin)
- `UPLOAD_FOLDER`: Temporary upload directory

### OCR Settings

In `config.py`:
- `CONFIDENCE_THRESHOLD`: 80 (words below this are highlighted)
- `MAX_CONTENT_LENGTH`: 100MB max file size
- `ALLOWED_EXTENSIONS`: Supported file types

## Project Structure

```
.
├── app.py                  # Flask application
├── lambda_handler.py       # Lambda entry point
├── ocr_processor.py        # OCR processing logic
├── aws_service.py          # AWS S3/DynamoDB integration
├── config.py               # Configuration
├── requirements.txt        # Python dependencies
├── Dockerfile              # Container image
├── templates/              # HTML templates
│   └── index.html         # Frontend
├── .github/workflows/      # GitHub Actions
│   └── deploy.yml         # Deployment workflow
└── README.md              # This file
```

## How It Works

1. **Upload**: User uploads image/PDF
2. **Process**: Lambda function processes with Tesseract OCR
3. **Extract**: Text extracted with confidence scores
4. **Store**: Low-confidence word/char images → S3, metadata → DynamoDB
5. **Stream**: Results streamed back in real-time

## Cost Estimate

Monthly costs (1000 documents):
- Lambda: ~$5-10
- S3: ~$1
- DynamoDB: ~$2
- ECR: ~$1

**Total**: ~$10-15/month (Free Tier covers most for first 12 months)

## Troubleshooting

### Character Extraction Errors
Fixed - properly checks for 'char' key in OCR data before processing.

### No Logs Appearing
Only errors are logged. Check CloudWatch Logs for error messages.

### Lambda Timeout
Increase timeout (max 15 min) or optimize document size.

### Out of Memory
Increase Lambda memory (up to 10GB).

## Security

1. Use IAM roles for Lambda execution (recommended)
2. Remove hardcoded credentials from `config.py`
3. Enable S3 bucket encryption
4. Configure Function URL authentication if needed
5. Set up proper CORS policies

## Development

Run locally:
```bash
python app.py
```

Deploy to Lambda:
```bash
git push origin main  # GitHub Actions handles deployment
```

Manual deployment:
```bash
chmod +x deploy-ecr.sh
./deploy-ecr.sh
```

## License

MIT
