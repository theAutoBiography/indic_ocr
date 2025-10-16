# Drishti (दृष्टि)

**Multi-Language Document Vision & OCR Platform with Correction Capabilities**

A serverless OCR web application for processing images and PDFs with real-time text extraction, confidence scoring, and user corrections. Features AWS Lambda deployment, S3 storage, DynamoDB with GSIs for efficient querying, and click-to-correct interface for building training datasets.

## ✨ Features

- 📄 **Multi-Format Support**: Images (PNG, JPG, JPEG, TIFF, BMP) and PDF files up to 100MB
- 🌍 **Multi-Language OCR**: Sanskrit, Hindi, Tamil, Kannada, Telugu, English with Tesseract
- 🎯 **Confidence Scoring**: Visual highlighting of low-confidence words
- ✏️ **Click-to-Correct**: Edit OCR results directly in the UI
- 📊 **Training Data Collection**: Approve corrections for model retraining
- 🔍 **Script Detection**: Automatic detection of Devanagari, Tamil, Telugu, etc.
- ⚡ **Real-time Streaming**: Page-by-page results via Server-Sent Events (SSE)
- ☁️ **AWS Integration**: Lambda + S3 + DynamoDB with Global Secondary Indexes
- 🎨 **Modern UI**: Responsive design with drag-and-drop, glassmorphic effects
- 🚀 **Serverless**: Automated GitHub Actions deployment

## 🚀 Quick Start

### Local Development

1. **Install Tesseract:**
   ```bash
   # macOS
   brew install tesseract tesseract-lang

   # Ubuntu
   sudo apt-get install tesseract-ocr tesseract-ocr-san tesseract-ocr-hin tesseract-ocr-tam tesseract-ocr-tel tesseract-ocr-kan
   ```

2. **Set up Python environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your AWS credentials
   ```

4. **Run the app:**
   ```bash
   python run.py
   ```

5. **Open:** http://localhost:5000

### AWS Lambda Deployment

#### One-Time Setup

1. **Create AWS resources:**
   ```bash
   # Run the provided scripts
   cd scripts
   ./create-dynamodb-table.sh
   ./setup-lambda.sh
   ```

   Or manually:
   ```bash
   # ECR repository
   aws ecr create-repository --repository-name drishti-ocr --region us-east-1

   # S3 buckets
   aws s3 mb s3://ocr-word-images
   aws s3 mb s3://ocr-char-images
   ```

2. **Configure GitHub secrets:**
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`

#### Deploy

Push to main branch - GitHub Actions handles the rest:
```bash
git push origin main
```

## 📁 Project Structure

```
.
├── src/                      # Application source code
│   ├── __init__.py          # Package initialization
│   ├── app.py               # Flask application & API endpoints
│   ├── lambda_handler.py    # AWS Lambda entry point
│   ├── ocr_processor.py     # OCR processing with Tesseract
│   ├── aws_service.py       # S3/DynamoDB integration
│   ├── config.py            # Configuration management
│   └── script_utils.py      # Script detection utilities
├── templates/               # HTML templates
│   └── index.html          # Frontend with correction UI
├── scripts/                 # Deployment & setup scripts
│   ├── create-dynamodb-table.sh
│   ├── deploy-ecr.sh
│   └── setup-lambda.sh
├── docs/                    # Documentation
│   ├── DEPLOYMENT.md        # Deployment guide
│   ├── DYNAMODB_DESIGN.md   # Database schema design
│   └── LOCAL_DEV.md         # Local development guide
├── .github/workflows/       # CI/CD
│   └── deploy.yml          # Automated deployment
├── uploads/                 # Temporary file storage
├── static/                  # Static assets
├── run.py                   # Local development entrypoint
├── requirements.txt         # Python dependencies
├── Dockerfile              # Container image definition
├── .env.example            # Environment variables template
└── README.md               # This file
```

## 🏗️ Architecture

```
User → Lambda Function URL → Lambda (Container)
                                 ↓
                    ┌────────────┼────────────┐
                    ↓            ↓            ↓
                S3 Buckets   DynamoDB      Tesseract OCR
                (Images)    (Metadata +     (Multi-language)
                           Corrections)
```

### DynamoDB Schema

**Table: `ocr-results-v2`**
- **Primary Key**: `file_id` (PK) + `page#word_index` (SK)
- **Attributes**: original_text, corrected_text, confidence, language, detected_script, bbox, S3 keys, training flags
- **GSIs**:
  - `GSI-Language-Confidence`: Query by language and confidence
  - `GSI-Corrections`: Find all corrected words
  - `GSI-LowConfidence`: Find words needing review

## 🎯 Key Features

### 1. Multi-Language Support
Select from Sanskrit, Hindi, Tamil, Kannada, Telugu, English, or combinations.

### 2. Click-to-Correct Interface
- Click any low-confidence word (yellow highlighted)
- Modal displays: original text, confidence, language, script, word image
- Edit text and optionally approve for training
- Corrected words turn green with checkmark

### 3. Training Data Collection
- User corrections stored in DynamoDB
- Flag corrections as "approved for training"
- Query corrections by language, confidence, date
- Export training datasets for model improvement

### 4. Script Detection
Automatic detection using Unicode ranges:
- Indic: Devanagari, Tamil, Telugu, Kannada, Malayalam, Bengali, Gujarati, Oriya, Gurmukhi
- Other: Latin, Arabic, Chinese, Japanese, Korean, Thai, Myanmar

## ⚙️ Configuration

### Environment Variables

```bash
AWS_REGION=us-east-1
S3_WORD_BUCKET=ocr-word-images
S3_CHAR_BUCKET=ocr-char-images
DYNAMODB_TABLE=ocr-results-v2
TESSERACT_LANG=san+eng+hin
UPLOAD_FOLDER=./uploads
MAX_CONTENT_LENGTH=104857600
```

### OCR Settings

In `src/config.py`:
- `CONFIDENCE_THRESHOLD`: 80 (words below are highlighted)
- `MAX_CONTENT_LENGTH`: 100MB max file size
- `ALLOWED_EXTENSIONS`: Supported file types

## 📡 API Endpoints

### OCR Processing
- `POST /upload` - Upload file
- `GET /process/<file_id>` - Stream OCR results (SSE)

### Corrections
- `POST /api/correction` - Submit word correction
- `GET /api/corrections` - Get all corrections (filterable)
- `GET /api/word/<file_id>/<page>/<word_index>` - Get word details
- `GET /api/low-confidence-words/<file_id>` - Get words needing review

### Utilities
- `GET /health` - Health check
- `GET /file/<file_id>` - Get uploaded file
- `GET /page/<file_id>/<page_num>` - Get page image

## 💰 Cost Estimate

Monthly costs (1000 documents):
- Lambda: ~$5-10
- S3: ~$1
- DynamoDB: ~$2-5 (with GSIs)
- ECR: ~$1

**Total**: ~$10-20/month (Free Tier covers most for first 12 months)

## 🔧 Development

### Run tests:
```bash
pytest
```

### Manual deployment:
```bash
cd scripts
./deploy-ecr.sh
```

### Create new DynamoDB table:
```bash
cd scripts
./create-dynamodb-table.sh
```

## 🐛 Troubleshooting

### Character Extraction Errors
Fixed - properly checks for 'char' key in OCR data.

### Import Errors
Ensure you're running from project root: `python run.py`

### Lambda Timeout
Increase timeout (max 15 min) or reduce document size.

### DynamoDB Access
Ensure Lambda execution role has DynamoDB permissions.

## 🔒 Security

1. ✅ Use IAM roles for Lambda (not hardcoded credentials)
2. ✅ Enable S3 bucket encryption
3. ✅ Configure Function URL authentication
4. ✅ Set CORS policies
5. ✅ Never commit `.env` file
6. ✅ Review user corrections before using for training

## 📚 Documentation

- [Deployment Guide](docs/DEPLOYMENT.md)
- [DynamoDB Schema Design](docs/DYNAMODB_DESIGN.md)
- [Local Development Guide](docs/LOCAL_DEV.md)

## 🗺️ Roadmap

### Phase 1 (MVP) ✅
- ✅ Multi-language OCR
- ✅ Click-to-correct interface
- ✅ DynamoDB with GSIs
- ✅ Script detection
- ✅ Correction API

### Phase 2 (Planned)
- [ ] Training data export
- [ ] Batch corrections
- [ ] Correction history
- [ ] Analytics dashboard

### Phase 3 (Future)
- [ ] ML-based auto-suggestions
- [ ] Similarity search for corrections
- [ ] Collaborative corrections
- [ ] Custom model training

## 📄 License

MIT

## 🙏 Acknowledgments

- Tesseract OCR for open-source OCR engine
- AWS for serverless infrastructure
- Unicode Consortium for character standards
