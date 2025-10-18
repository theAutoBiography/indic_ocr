import os
from dotenv import load_dotenv

# Load .env file if it exists (local development)
# In production (Lambda), environment variables are set directly
load_dotenv()

class Config:
    # Get project root directory (parent of src/)
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Flask config
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    UPLOAD_FOLDER = os.path.join(PROJECT_ROOT, os.getenv('UPLOAD_FOLDER', 'uploads'))
    MAX_CONTENT_LENGTH = int(os.getenv('MAX_CONTENT_LENGTH', 104857600))  # 100MB default

    # AWS config
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')

    # S3 buckets
    S3_WORD_BUCKET = os.getenv('S3_WORD_BUCKET', 'ocr-word-images')
    S3_CHAR_BUCKET = os.getenv('S3_CHAR_BUCKET', 'ocr-char-images')

    # DynamoDB
    DYNAMODB_TABLE = os.getenv('DYNAMODB_TABLE', 'ocr-results')
    SANDHI_TABLE = os.getenv('SANDHI_TABLE', 'sandhi-corrections')

    # OCR config
    CONFIDENCE_THRESHOLD = 80
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'tiff', 'bmp'}
    TESSERACT_LANG = os.getenv('TESSERACT_LANG', 'san+eng+hin')  # Sanskrit, English, and Hindi

    # Sandhi config
    SANDHI_DATA_PATH = os.path.join(PROJECT_ROOT, 'data', 'sandhikosh_combined.json')
