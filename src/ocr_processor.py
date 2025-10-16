import pytesseract
from PIL import Image
import cv2
import numpy as np
from pdf2image import convert_from_path
import io
import uuid
import os
from datetime import datetime
from src.config import Config
from src.aws_service import AWSService
from src.script_utils import detect_script
import logging

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)


class OCRProcessor:
    def __init__(self, language=None):
        self.aws_service = AWSService()
        self.confidence_threshold = Config.CONFIDENCE_THRESHOLD
        self.tesseract_lang = language or Config.TESSERACT_LANG

    def process_file(self, file_path, file_id):
        """Process a file (image or PDF) and yield results page by page"""
        file_extension = os.path.splitext(file_path)[1].lower()

        if file_extension == '.pdf':
            yield from self._process_pdf(file_path, file_id)
        else:
            yield from self._process_image(file_path, file_id, page_num=1)

    def _process_pdf(self, pdf_path, file_id):
        """Process PDF page by page"""
        page_num = 0  # Initialize page_num to avoid unbound variable error
        try:
            images = convert_from_path(pdf_path)
            for page_num, image in enumerate(images, start=0):
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

                word_data = {
                    "text": text,
                    "confidence": conf,
                    "bbox": {"x": x, "y": y, "width": w, "height": h},
                    "word_index": word_index  # Add word_index to word_data
                }

                # If confidence is below threshold, store image and prepare for upload
                if conf < self.confidence_threshold:
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

                    # Extract character-level data for low confidence words
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
                    "original_text": text,
                    "confidence": conf,  # Store as number for GSI sorting
                    "language": self.tesseract_lang,
                    "detected_script": detect_script(text),
                    "bbox": word_data["bbox"],
                    "page": page_num,
                    "word_index": word_index,
                    "is_low_confidence": "true" if conf < self.confidence_threshold else "false",
                    "is_corrected": "false",
                    "correction_count": 0,
                    "approved_for_training": False,
                    "correction_verified": False,
                    "created_at": page_data["timestamp"],
                    "updated_at": page_data["timestamp"],
                }

                # Only add corrected_text, corrected_at, corrected_by if they exist
                # (DynamoDB GSI keys cannot be NULL)

                # Add S3 references if word image was stored
                if conf < self.confidence_threshold and "image_filename" in word_data:
                    db_item["word_image_s3_key"] = word_data["image_filename"]

                    # Add character images if available
                    if "characters" in word_data and word_data["characters"]:
                        db_item["char_images_s3_keys"] = [
                            char["image_filename"] for char in word_data["characters"]
                        ]

                # Add composite sort key for GSI-LowConfidence
                db_item["file_page_word"] = f"{file_id}#{page_num:04d}#{word_index:04d}"

                db_items.append(db_item)
                word_index += 1  # Increment word index

            # Wait for all S3 uploads to complete
            for future in word_upload_futures + char_upload_futures:
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"S3 upload error: {e}")

            # Save to DynamoDB
            if db_items:
                self.aws_service.save_to_dynamodb(db_items)

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
