# Local Development Setup

## Prerequisites

1. **Python 3.8+**
2. **Tesseract OCR**
   ```bash
   # macOS
   brew install tesseract tesseract-lang

   # Ubuntu
   sudo apt-get install tesseract-ocr tesseract-ocr-san tesseract-ocr-hin tesseract-ocr-tam tesseract-ocr-kan tesseract-ocr-tel
   ```

3. **Poppler** (for PDF processing)
   ```bash
   # macOS
   brew install poppler

   # Ubuntu
   sudo apt-get install poppler-utils
   ```

## Setup

1. **Create virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables:**
   ```bash
   cp .env.example .env
   ```

   Edit `.env` and add your AWS credentials:
   ```
   AWS_ACCESS_KEY_ID=your-access-key
   AWS_SECRET_ACCESS_KEY=your-secret-key
   AWS_REGION=us-east-1
   S3_WORD_BUCKET=ocr-word-images
   S3_CHAR_BUCKET=ocr-char-images
   DYNAMODB_TABLE=ocr-results
   TESSERACT_LANG=san+eng+hin
   ```

## Run Locally

```bash
python app.py
```

The app will be available at: **http://localhost:5000**

## Testing Frontend Changes

1. Make changes to `templates/index.html`
2. Refresh your browser (hard refresh with Cmd+Shift+R or Ctrl+Shift+R)
3. No need to restart the Flask server for template changes!

## Testing Backend Changes

1. Make changes to `app.py`, `ocr_processor.py`, etc.
2. Restart the Flask server (Ctrl+C, then `python app.py` again)

## Clear Terms & Conditions Modal

If you accepted the terms and want to see the modal again:
1. Open browser console (F12 or Cmd+Option+I)
2. Run: `localStorage.clear()`
3. Refresh the page

## Debugging

### Check Tesseract Installation
```bash
tesseract --version
tesseract --list-langs  # Should show: san, hin, tam, kan, tel, eng
```

### Test OCR Locally
```bash
tesseract test_image.png output -l san+eng+hin
```

### Check AWS Credentials
```bash
aws s3 ls  # Should list your buckets
aws dynamodb list-tables  # Should show ocr-results
```

## Common Issues

### Tesseract not found
- Make sure Tesseract is in your PATH
- On macOS: `export PATH="/usr/local/bin:$PATH"`

### Language data not found
- Install language packs: `brew install tesseract-lang`
- Check tessdata location: `tesseract --list-langs`

### AWS connection errors
- Verify credentials in `.env`
- Check IAM permissions for S3 and DynamoDB
- Ensure buckets and table exist

## Deploy to Lambda

Once you've tested locally and everything works:

```bash
git add .
git commit -m "Your changes"
git push origin main
```

GitHub Actions will automatically deploy to Lambda!

## Project Structure

```
.
├── app.py                  # Flask application & routes
├── lambda_handler.py       # Lambda Function URL handler
├── ocr_processor.py        # OCR processing logic
├── aws_service.py          # AWS S3/DynamoDB integration
├── config.py               # Configuration
├── requirements.txt        # Python dependencies
├── templates/
│   └── index.html         # Frontend (HTML/CSS/JS)
├── uploads/               # Temporary uploads (local only)
└── .env                   # Environment variables (gitignored)
```

## Tips

- Use **Flask debug mode** for auto-reload: Set `debug=True` in `app.py`
- **Don't commit** your `.env` file with real credentials
- Test with **small images** first before large PDFs
- Check **browser console** (F12) for JavaScript errors
- Check **terminal** for Python errors
