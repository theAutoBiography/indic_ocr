import pytesseract
from PIL import Image
import cv2
import numpy as np
from pdf2image import convert_from_path
import io
import uuid
import os
import hashlib
from datetime import datetime
from src.config import Config
from src.aws_service import AWSService
from src.script_utils import detect_script
import logging

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# Set Tesseract path - check common locations
# Lambda containers may not have AWS_LAMBDA_FUNCTION_NAME set reliably
tesseract_paths = ['/usr/bin/tesseract', '/usr/local/bin/tesseract']
for path in tesseract_paths:
    if os.path.exists(path):
        pytesseract.pytesseract.tesseract_cmd = path
        logger.error(f"Tesseract found at: {path}")
        break
else:
    # If not found, still set to standard location and let pytesseract handle the error
    if os.environ.get('LAMBDA_TASK_ROOT') or os.environ.get('AWS_EXECUTION_ENV'):
        pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
        logger.error("Tesseract binary not found, setting to /usr/bin/tesseract")


class OCRProcessor:
    def __init__(self, language=None):
        self.aws_service = AWSService()
        self.confidence_threshold = Config.CONFIDENCE_THRESHOLD
        self.tesseract_lang = language or Config.TESSERACT_LANG

    def _calculate_image_hash(self, image_array):
        """Calculate SHA256 hash of an image array"""
        # Convert to bytes and hash
        image_bytes = image_array.tobytes()
        return hashlib.sha256(image_bytes).hexdigest()

    def _check_word_cache(self, image_hash):
        """Check if a word with this image hash has been processed before"""
        try:
            table = self.aws_service.dynamodb.Table(Config.DYNAMODB_TABLE)

            # Query using GSI-ImageHash to find existing word by image hash
            response = table.query(
                IndexName='GSI-ImageHash',
                KeyConditionExpression='image_hash = :hash',
                ExpressionAttributeValues={
                    ':hash': image_hash
                },
                Limit=1
            )

            if response.get('Items'):
                item = response['Items'][0]
                # Return cached data with preference for corrected text
                return {
                    'text': item.get('corrected_text', item.get('original_text')),
                    'original_text': item.get('original_text'),
                    'confidence': item.get('confidence'),
                    'is_corrected': item.get('is_corrected') == 'true',
                    'cached': True,
                    'source_file_id': item.get('file_id'),
                    'source_page': item.get('page'),
                    'source_word_index': item.get('word_index')
                }

            return None
        except Exception as e:
            logger.error(f"Error checking word cache: {e}")
            return None

    def process_file(self, file_path, file_id):
        """Process a file (image or PDF) and yield results page by page"""
        file_extension = os.path.splitext(file_path)[1].lower()

        # First, send total page count for progress tracking
        if file_extension == '.pdf':
            try:
                from pdf2image import pdfinfo_from_path
                info = pdfinfo_from_path(file_path)
                total_pages = info.get('Pages', 1)
            except Exception as e:
                # Fallback: convert to count pages
                logger.error(f"Error getting PDF info: {e}")
                try:
                    images = convert_from_path(file_path)
                    total_pages = len(images)
                except Exception as e2:
                    logger.error(f"Error converting PDF: {e2}")
                    total_pages = 1

            yield {"total_pages": total_pages, "type": "metadata"}
            yield from self._process_pdf(file_path, file_id)
        else:
            yield {"total_pages": 1, "type": "metadata"}
            yield from self._process_image(file_path, file_id, page_num=1)

    def _process_pdf(self, pdf_path, file_id):
        """Process PDF page by page"""
        page_num = 1  # Initialize page_num to avoid unbound variable error
        try:
            images = convert_from_path(pdf_path)
            for page_num, image in enumerate(images, start=1):
                yield from self._process_image_object(image, file_id, page_num)
        except Exception as e:
            logger.error(f"Error processing PDF: {e}")
            yield {"error": str(e), "page": page_num}

    def _process_image(self, image_path, file_id, page_num=1):
        """Process a single image file"""
        try:
            image = Image.open(image_path)
            yield from self._process_image_object(image, file_id, page_num)
        except Exception as e:
            logger.error(f"Error processing image: {e}")
            yield {"error": str(e), "page": page_num}

    def _process_image_object(self, image, file_id, page_num):
        """Process PIL Image object and extract text with confidence scores"""
        try:
            # Convert to OpenCV format
            image_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

            # Get detailed OCR data with configured language (default: Sanskrit)
            ocr_data = pytesseract.image_to_data(image, lang=self.tesseract_lang, output_type=pytesseract.Output.DICT)

            page_data = {
                "file_id": file_id,
                "page": page_num,
                "words": [],
                "full_text": "",
                "timestamp": datetime.utcnow().isoformat()
            }

            db_items = []
            word_upload_futures = []
            char_upload_futures = []

            # First pass: check if page is blank by counting meaningful text
            meaningful_chars = 0
            for i in range(len(ocr_data['text'])):
                text = ocr_data['text'][i].strip()
                conf = float(ocr_data['conf'][i])
                # Only count characters with reasonable confidence
                if text and conf > 30:
                    meaningful_chars += len(text)

            # If page has less than 5 meaningful characters, consider it blank
            if meaningful_chars < 5:
                page_data["is_blank"] = True
                page_data["full_text"] = ""
                yield page_data
                return

            # Process word by word
            word_index = 0  # Track actual word index (excluding empty strings)
            for i in range(len(ocr_data['text'])):
                text = ocr_data['text'][i].strip()
                if not text:
                    continue

                conf = float(ocr_data['conf'][i])
                x, y, w, h = ocr_data['left'][i], ocr_data['top'][i], ocr_data['width'][i], ocr_data['height'][i]

                # Extract word image
                word_image = image_cv[y:y+h, x:x+w]

                # Calculate image hash for caching
                image_hash = self._calculate_image_hash(word_image)

                # Check cache first
                cached_result = self._check_word_cache(image_hash)

                if cached_result:
                    # Use cached result
                    word_data = {
                        "text": cached_result['text'],
                        "confidence": cached_result['confidence'],
                        "bbox": {"x": x, "y": y, "width": w, "height": h},
                        "word_index": word_index,
                        "cached": True,
                        "is_corrected": cached_result['is_corrected']
                    }
                else:
                    # No cache hit, use Tesseract result
                    word_data = {
                        "text": text,
                        "confidence": conf,
                        "bbox": {"x": x, "y": y, "width": w, "height": h},
                        "word_index": word_index,
                        "cached": False
                    }

                # Always store word images for UI display and VLM training
                # Images are always uploaded (even for cached results) so users can view them when correcting
                word_filename = f"{file_id}/page_{page_num}/word_{uuid.uuid4().hex}.png"

                # Convert word image to bytes
                _, word_buffer = cv2.imencode('.png', word_image)
                word_bytes = word_buffer.tobytes()

                # Upload to S3 asynchronously
                future = self.aws_service.upload_to_s3_async(
                    word_bytes,
                    word_filename,
                    Config.S3_WORD_BUCKET
                )
                word_upload_futures.append(future)

                word_data["image_url"] = f"s3://{Config.S3_WORD_BUCKET}/{word_filename}"
                word_data["image_filename"] = word_filename

                # Extract character-level data for low confidence words only (skip if cached)
                if not cached_result and conf < self.confidence_threshold:
                    char_data = self._extract_characters(word_image, text, file_id, page_num, word_index)
                    word_data["characters"] = char_data["characters"]

                    # Add character upload futures
                    char_upload_futures.extend(char_data.get("upload_futures", []))

                page_data["words"].append(word_data)
                page_data["full_text"] += text + " "

                # Prepare DynamoDB item with new schema
                db_item = {
                    "file_id": file_id,
                    "page#word_index": f"{page_num:04d}#{word_index:04d}",
                    "word_id": str(uuid.uuid4()),
                    "original_text": text if not cached_result else cached_result['original_text'],
                    "confidence": conf if not cached_result else cached_result['confidence'],  # Store as number for GSI sorting
                    "language": self.tesseract_lang,
                    "detected_script": detect_script(text),
                    "bbox": word_data["bbox"],
                    "page": page_num,
                    "word_index": word_index,
                    "is_low_confidence": "true" if conf < self.confidence_threshold else "false",
                    "is_corrected": "true" if cached_result and cached_result['is_corrected'] else "false",
                    "correction_count": 0,
                    "approved_for_training": False,
                    "correction_verified": False,
                    "created_at": page_data["timestamp"],
                    "updated_at": page_data["timestamp"],
                    "image_hash": image_hash,  # Store image hash for caching
                }

                # If cached result has corrected text, add it
                if cached_result and cached_result['is_corrected']:
                    db_item["corrected_text"] = cached_result['text']

                # Add S3 references if word image was stored
                if "image_filename" in word_data:
                    db_item["word_image_s3_key"] = word_data["image_filename"]
                    db_item["word_image_s3_uri"] = f"s3://{Config.S3_WORD_BUCKET}/{word_data['image_filename']}"

                    # Add character images if available
                    if "characters" in word_data and word_data["characters"]:
                        db_item["char_images_s3_keys"] = [
                            char["image_filename"] for char in word_data["characters"]
                        ]
                        db_item["char_images_s3_uris"] = [
                            f"s3://{Config.S3_CHAR_BUCKET}/{char['image_filename']}"
                            for char in word_data["characters"]
                        ]

                # Add composite sort key for GSI-LowConfidence
                db_item["file_page_word"] = f"{file_id}#{page_num:04d}#{word_index:04d}"

                db_items.append(db_item)
                word_index += 1  # Increment word index

            # Notify user that S3 upload is starting
            total_uploads = len(word_upload_futures) + len(char_upload_futures)
            yield {
                "type": "upload_progress",
                "page": page_num,
                "total_uploads": total_uploads,
                "status": "uploading"
            }

            # Wait for S3 uploads to complete before saving to DynamoDB and yielding
            # This ensures images are available when user clicks to correct
            failed_uploads = []
            completed_uploads = 0
            for i, future in enumerate(word_upload_futures + char_upload_futures):
                try:
                    future.result()
                    completed_uploads += 1
                    # Send progress updates every 10% or for small batches
                    if total_uploads <= 10 or completed_uploads % max(1, total_uploads // 10) == 0:
                        yield {
                            "type": "upload_progress",
                            "page": page_num,
                            "completed": completed_uploads,
                            "total": total_uploads,
                            "status": "uploading"
                        }
                except Exception as e:
                    logger.error(f"S3 upload error: {e}")
                    failed_uploads.append(i)

            # Remove S3 references for failed uploads
            if failed_uploads:
                logger.warning(f"{len(failed_uploads)} S3 uploads failed, cleaning up references")
                # Note: This is a best-effort cleanup, consider implementing retry logic

            # Notify upload complete
            yield {
                "type": "upload_progress",
                "page": page_num,
                "completed": completed_uploads,
                "total": total_uploads,
                "status": "complete"
            }

            # Save to DynamoDB after S3 uploads complete
            if db_items:
                self.aws_service.save_to_dynamodb(db_items)

            # Yield page data to user after S3 uploads and DB save
            page_data["full_text"] = page_data["full_text"].strip()
            yield page_data

        except Exception as e:
            logger.error(f"Error in _process_image_object: {e}")
            yield {"error": str(e), "page": page_num}

    def _extract_characters(self, word_image, text, file_id, page_num, word_index):
        """Extract individual characters from a word image"""
        char_data = {"characters": [], "upload_futures": []}

        try:
            # Get character-level OCR data with configured language (default: Sanskrit)
            char_ocr_data = pytesseract.image_to_boxes(
                word_image,
                lang=self.tesseract_lang,
                output_type=pytesseract.Output.DICT
            )

            h, w = word_image.shape[:2]

            # Check if 'char' key exists and has data
            if 'char' not in char_ocr_data or not char_ocr_data['char']:
                return char_data

            for j in range(len(char_ocr_data['char'])):
                char = char_ocr_data['char'][j]
                x1 = char_ocr_data['left'][j]
                y1 = h - char_ocr_data['top'][j]
                x2 = char_ocr_data['right'][j]
                y2 = h - char_ocr_data['bottom'][j]

                # Extract character image
                char_image = word_image[y2:y1, x1:x2]

                if char_image.size == 0:
                    continue

                char_filename = f"{file_id}/page_{page_num}/word_{word_index}_char_{j}_{uuid.uuid4().hex}.png"

                # Convert character image to bytes
                _, char_buffer = cv2.imencode('.png', char_image)
                char_bytes = char_buffer.tobytes()

                # Upload to S3 asynchronously
                future = self.aws_service.upload_to_s3_async(
                    char_bytes,
                    char_filename,
                    Config.S3_CHAR_BUCKET
                )
                char_data["upload_futures"].append(future)

                char_data["characters"].append({
                    "char": char,
                    "image_filename": char_filename,
                    "image_url": f"s3://{Config.S3_CHAR_BUCKET}/{char_filename}"
                })

        except Exception as e:
            logger.error(f"Error extracting characters: {e}")

        return char_data

    def cleanup(self):
        """Cleanup resources"""
        self.aws_service.shutdown()
