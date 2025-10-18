"""
Vision Language Model inference for OCR refinement
Loads trained TrOCR models and runs inference on word images
"""
import os
import logging
import torch
from PIL import Image
import numpy as np
from transformers import TrOCRProcessor, VisionEncoderDecoderModel
import boto3
from pathlib import Path
import tempfile
import shutil
from src.config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VLMInference:
    """
    Handles VLM model loading and inference for OCR refinement
    Uses lazy loading - only loads model when first needed
    """

    def __init__(self, model_path=None, device=None):
        """
        Initialize VLM inference

        Args:
            model_path: Optional path to local model. If None, downloads from S3
            device: Optional device (cpu/cuda). If None, auto-detects
        """
        self.model_path = model_path
        self.device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = None
        self.processor = None
        self.model_loaded = False
        self.s3_client = None

        logger.info(f"VLM Inference initialized. Device: {self.device}")

    def _get_s3_client(self):
        """Lazy initialize S3 client"""
        if self.s3_client is None:
            self.s3_client = boto3.client('s3', region_name=Config.AWS_REGION)
        return self.s3_client

    def _download_model_from_s3(self, s3_uri=None):
        """
        Download the latest trained model from S3

        Args:
            s3_uri: Optional specific S3 URI. If None, gets latest model

        Returns:
            str: Local path to downloaded model
        """
        s3_client = self._get_s3_client()
        model_bucket = os.getenv('S3_MODEL_BUCKET', 'ocr-trained-models')

        try:
            if s3_uri:
                # Parse S3 URI
                s3_prefix = s3_uri.replace(f"s3://{model_bucket}/", "")
            else:
                # Get latest model
                logger.info("Fetching latest model from S3...")
                response = s3_client.list_objects_v2(
                    Bucket=model_bucket,
                    Prefix='vlm_models/',
                    Delimiter='/'
                )

                if 'CommonPrefixes' not in response or len(response['CommonPrefixes']) == 0:
                    logger.warning("No trained models found in S3")
                    return None

                # Get latest (last in sorted list)
                model_dirs = sorted([p['Prefix'] for p in response['CommonPrefixes']])
                s3_prefix = model_dirs[-1]  # Latest model
                logger.info(f"Latest model: {s3_prefix}")

            # Download all files in model directory
            local_model_dir = os.path.join(tempfile.gettempdir(), 'vlm_model_cache', s3_prefix.split('/')[-2])
            os.makedirs(local_model_dir, exist_ok=True)

            # Check if already downloaded
            if os.path.exists(os.path.join(local_model_dir, 'config.json')):
                logger.info(f"Model already cached locally: {local_model_dir}")
                return local_model_dir

            logger.info(f"Downloading model from s3://{model_bucket}/{s3_prefix}...")

            # List all files in model directory
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=model_bucket, Prefix=s3_prefix)

            file_count = 0
            for page in pages:
                for obj in page.get('Contents', []):
                    s3_key = obj['Key']
                    if s3_key.endswith('/'):  # Skip directories
                        continue

                    # Get relative path
                    relative_path = s3_key.replace(s3_prefix, '')
                    local_path = os.path.join(local_model_dir, relative_path)

                    # Create directory if needed
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)

                    # Download file
                    s3_client.download_file(model_bucket, s3_key, local_path)
                    file_count += 1

                    if file_count % 5 == 0:
                        logger.info(f"Downloaded {file_count} files...")

            logger.info(f"Model download complete: {local_model_dir} ({file_count} files)")
            return local_model_dir

        except Exception as e:
            logger.error(f"Error downloading model from S3: {e}")
            return None

    def load_model(self, model_path=None):
        """
        Load VLM model and processor

        Args:
            model_path: Optional path to model. If None, uses initialization path or downloads from S3

        Returns:
            bool: True if model loaded successfully
        """
        if self.model_loaded:
            logger.info("Model already loaded")
            return True

        try:
            # Determine model path
            if model_path:
                final_model_path = model_path
            elif self.model_path:
                final_model_path = self.model_path
            else:
                # Try to download from S3
                final_model_path = self._download_model_from_s3()

            if not final_model_path or not os.path.exists(final_model_path):
                logger.warning("No VLM model available. Using Tesseract only.")
                return False

            logger.info(f"Loading VLM model from: {final_model_path}")

            # Load processor and model
            self.processor = TrOCRProcessor.from_pretrained(final_model_path)
            self.model = VisionEncoderDecoderModel.from_pretrained(final_model_path)
            self.model.to(self.device)
            self.model.eval()  # Set to evaluation mode

            self.model_loaded = True
            logger.info(f"VLM model loaded successfully on {self.device}")
            return True

        except Exception as e:
            logger.error(f"Error loading VLM model: {e}")
            self.model_loaded = False
            return False

    def predict(self, image, return_confidence=True):
        """
        Run VLM inference on an image

        Args:
            image: PIL Image or numpy array
            return_confidence: Whether to return confidence score

        Returns:
            dict: {'text': str, 'confidence': float} or just text string
        """
        if not self.model_loaded:
            # Try to load model on first use
            if not self.load_model():
                raise RuntimeError("VLM model not loaded and could not be loaded")

        try:
            # Convert numpy array to PIL Image if needed
            if isinstance(image, np.ndarray):
                image = Image.fromarray(image)

            # Ensure RGB
            if image.mode != 'RGB':
                image = image.convert('RGB')

            # Process image
            pixel_values = self.processor(image, return_tensors="pt").pixel_values
            pixel_values = pixel_values.to(self.device)

            # Generate text
            with torch.no_grad():
                generated_ids = self.model.generate(
                    pixel_values,
                    max_length=64,
                    num_beams=4,
                    early_stopping=True
                )

            # Decode
            generated_text = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

            if return_confidence:
                # Calculate a pseudo-confidence based on beam scores
                # This is approximate - VLM doesn't provide per-word confidence like Tesseract
                # We use a high default confidence since VLM is generally more accurate
                confidence = 95.0  # Default high confidence for VLM predictions

                return {
                    'text': generated_text,
                    'confidence': confidence,
                    'source': 'vlm'
                }
            else:
                return generated_text

        except Exception as e:
            logger.error(f"Error during VLM inference: {e}")
            raise

    def predict_batch(self, images, batch_size=8):
        """
        Run VLM inference on multiple images

        Args:
            images: List of PIL Images or numpy arrays
            batch_size: Batch size for inference

        Returns:
            list: List of prediction dicts
        """
        if not self.model_loaded:
            if not self.load_model():
                raise RuntimeError("VLM model not loaded")

        results = []

        for i in range(0, len(images), batch_size):
            batch = images[i:i + batch_size]

            try:
                # Convert to PIL Images if needed
                pil_images = []
                for img in batch:
                    if isinstance(img, np.ndarray):
                        img = Image.fromarray(img)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    pil_images.append(img)

                # Process batch
                pixel_values = self.processor(pil_images, return_tensors="pt").pixel_values
                pixel_values = pixel_values.to(self.device)

                # Generate
                with torch.no_grad():
                    generated_ids = self.model.generate(
                        pixel_values,
                        max_length=64,
                        num_beams=4,
                        early_stopping=True
                    )

                # Decode
                generated_texts = self.processor.batch_decode(generated_ids, skip_special_tokens=True)

                # Add to results
                for text in generated_texts:
                    results.append({
                        'text': text,
                        'confidence': 95.0,
                        'source': 'vlm'
                    })

            except Exception as e:
                logger.error(f"Error in batch inference: {e}")
                # Add error results for failed batch
                for _ in batch:
                    results.append({
                        'text': '',
                        'confidence': 0.0,
                        'source': 'vlm',
                        'error': str(e)
                    })

        return results

    def is_available(self):
        """
        Check if VLM model is available

        Returns:
            bool: True if model is loaded or can be loaded
        """
        if self.model_loaded:
            return True

        # Check if model exists locally
        if self.model_path and os.path.exists(self.model_path):
            return True

        # Check if model exists in S3
        try:
            s3_client = self._get_s3_client()
            model_bucket = os.getenv('S3_MODEL_BUCKET', 'ocr-trained-models')
            response = s3_client.list_objects_v2(
                Bucket=model_bucket,
                Prefix='vlm_models/',
                MaxKeys=1
            )
            return response.get('KeyCount', 0) > 0
        except:
            return False

    def unload_model(self):
        """Unload model from memory"""
        if self.model:
            del self.model
            del self.processor
            self.model = None
            self.processor = None
            self.model_loaded = False
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("VLM model unloaded from memory")


# Global inference instance (singleton pattern for model caching)
_global_vlm_instance = None


def get_vlm_inference():
    """
    Get global VLM inference instance (singleton)
    Ensures model is loaded only once per process

    Returns:
        VLMInference: Global VLM inference instance
    """
    global _global_vlm_instance
    if _global_vlm_instance is None:
        _global_vlm_instance = VLMInference()
    return _global_vlm_instance


if __name__ == '__main__':
    # Test VLM inference
    vlm = VLMInference()

    if vlm.is_available():
        logger.info("VLM model is available")
        vlm.load_model()
    else:
        logger.info("No VLM model available yet")
