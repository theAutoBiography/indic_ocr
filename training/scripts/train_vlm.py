#!/usr/bin/env python3
"""
Vision Language Model training script for OCR
Uses TrOCR (or similar) fine-tuned on correction data
"""
import os
import sys
import logging
from datetime import datetime
import tempfile
import shutil
from pathlib import Path
import json

import torch
from torch.utils.data import Dataset, DataLoader
from transformers import (
    TrOCRProcessor,
    VisionEncoderDecoderModel,
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
    default_data_collator
)
from PIL import Image
import evaluate

# Add src to path to import shared modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.config import Config
from src.aws_service import AWSService

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class OCRDataset(Dataset):
    """Dataset for OCR training with word images and ground truth text"""

    def __init__(self, image_paths, texts, processor):
        """
        Args:
            image_paths: List of paths to word images
            texts: List of ground truth texts
            processor: TrOCRProcessor instance
        """
        self.image_paths = image_paths
        self.texts = texts
        self.processor = processor

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        # Load image
        image = Image.open(self.image_paths[idx]).convert("RGB")

        # Process image
        pixel_values = self.processor(image, return_tensors="pt").pixel_values

        # Process text (labels)
        labels = self.processor.tokenizer(
            self.texts[idx],
            padding="max_length",
            max_length=64,
            truncation=True,
            return_tensors="pt"
        ).input_ids

        # Remove batch dimension
        pixel_values = pixel_values.squeeze()
        labels = labels.squeeze()

        return {
            "pixel_values": pixel_values,
            "labels": labels
        }


class VLMTrainer:
    """Handles VLM training from correction data"""

    def __init__(self, base_model="microsoft/trocr-small-printed"):
        """
        Args:
            base_model: Hugging Face model ID to fine-tune from
        """
        self.aws_service = AWSService()
        self.dynamodb_table = self.aws_service.dynamodb.Table(Config.DYNAMODB_TABLE)
        self.work_dir = tempfile.mkdtemp(prefix='vlm_training_')
        self.training_job_id = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        self.base_model = base_model
        self.model_bucket = os.getenv('S3_MODEL_BUCKET', 'ocr-trained-models')

        logger.info(f"Training job ID: {self.training_job_id}")
        logger.info(f"Base model: {self.base_model}")
        logger.info(f"Working directory: {self.work_dir}")

        # Initialize processor and model
        self.processor = TrOCRProcessor.from_pretrained(base_model)
        self.model = VisionEncoderDecoderModel.from_pretrained(base_model)

        # Set decoder to start with BOS token
        self.model.config.decoder_start_token_id = self.processor.tokenizer.cls_token_id
        self.model.config.pad_token_id = self.processor.tokenizer.pad_token_id
        self.model.config.vocab_size = self.model.config.decoder.vocab_size

        # Use GPU if available
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"Using device: {self.device}")

    def fetch_approved_corrections(self):
        """
        Fetch all corrections approved for training from DynamoDB

        Returns:
            list: List of correction items with word images and corrected text
        """
        logger.info("Fetching approved corrections from DynamoDB...")

        try:
            response = self.dynamodb_table.query(
                IndexName='GSI-Corrections',
                KeyConditionExpression='is_corrected = :is_corrected',
                FilterExpression='approved_for_training = :approved',
                ExpressionAttributeValues={
                    ':is_corrected': 'true',
                    ':approved': True
                }
            )

            corrections = response.get('Items', [])

            # Handle pagination
            while 'LastEvaluatedKey' in response:
                response = self.dynamodb_table.query(
                    IndexName='GSI-Corrections',
                    KeyConditionExpression='is_corrected = :is_corrected',
                    FilterExpression='approved_for_training = :approved',
                    ExpressionAttributeValues={
                        ':is_corrected': 'true',
                        ':approved': True
                    },
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
                corrections.extend(response.get('Items', []))

            logger.info(f"Found {len(corrections)} approved corrections")

            # Filter to only include items with word images
            corrections_with_images = [
                c for c in corrections
                if 'word_image_s3_key' in c and 'corrected_text' in c
            ]

            logger.info(f"Found {len(corrections_with_images)} corrections with images")
            return corrections_with_images

        except Exception as e:
            logger.error(f"Error fetching corrections: {e}")
            raise

    def download_training_data(self, corrections):
        """
        Download word images from S3 and prepare training data

        Args:
            corrections: List of correction items

        Returns:
            tuple: (image_paths, texts) for training
        """
        logger.info("Downloading training images from S3...")

        image_dir = os.path.join(self.work_dir, 'images')
        os.makedirs(image_dir, exist_ok=True)

        image_paths = []
        texts = []

        for idx, correction in enumerate(corrections):
            try:
                s3_key = correction['word_image_s3_key']
                ground_truth = correction['corrected_text']

                # Download image from S3
                local_filename = f"word_{idx:06d}.png"
                local_path = os.path.join(image_dir, local_filename)

                self.aws_service.s3_client.download_file(
                    Config.S3_WORD_BUCKET,
                    s3_key,
                    local_path
                )

                image_paths.append(local_path)
                texts.append(ground_truth)

                if (idx + 1) % 100 == 0:
                    logger.info(f"Downloaded {idx + 1}/{len(corrections)} images")

            except Exception as e:
                logger.warning(f"Failed to download {s3_key}: {e}")
                continue

        logger.info(f"Successfully downloaded {len(image_paths)} training images")
        return image_paths, texts

    def train_model(self, train_dataset, eval_dataset=None):
        """
        Train the VLM model

        Args:
            train_dataset: Training dataset
            eval_dataset: Optional evaluation dataset

        Returns:
            dict: Training results
        """
        logger.info("Starting model training...")

        output_dir = os.path.join(self.work_dir, 'model_output')

        # Training arguments
        training_args = Seq2SeqTrainingArguments(
            output_dir=output_dir,
            num_train_epochs=10,
            per_device_train_batch_size=8,
            per_device_eval_batch_size=8,
            learning_rate=5e-5,
            weight_decay=0.01,
            logging_steps=50,
            save_steps=500,
            eval_steps=500 if eval_dataset else None,
            evaluation_strategy="steps" if eval_dataset else "no",
            save_total_limit=2,
            predict_with_generate=True,
            fp16=torch.cuda.is_available(),  # Use mixed precision if GPU available
            dataloader_num_workers=2,
            logging_dir=os.path.join(output_dir, 'logs'),
            report_to=["tensorboard"],
        )

        # Metrics
        cer_metric = evaluate.load("cer")

        def compute_metrics(pred):
            labels_ids = pred.label_ids
            pred_ids = pred.predictions

            # Decode predictions and labels
            pred_str = self.processor.batch_decode(pred_ids, skip_special_tokens=True)
            labels_ids[labels_ids == -100] = self.processor.tokenizer.pad_token_id
            label_str = self.processor.batch_decode(labels_ids, skip_special_tokens=True)

            # Compute CER
            cer = cer_metric.compute(predictions=pred_str, references=label_str)

            return {"cer": cer}

        # Initialize trainer
        trainer = Seq2SeqTrainer(
            model=self.model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=eval_dataset,
            data_collator=default_data_collator,
            compute_metrics=compute_metrics if eval_dataset else None,
        )

        # Train
        logger.info("Training started...")
        train_result = trainer.train()

        # Save model
        trainer.save_model(output_dir)
        self.processor.save_pretrained(output_dir)

        logger.info("Training completed!")
        logger.info(f"Training metrics: {train_result.metrics}")

        return {
            'output_dir': output_dir,
            'metrics': train_result.metrics
        }

    def upload_trained_model(self, model_dir):
        """
        Upload trained model to S3

        Args:
            model_dir: Local directory containing trained model

        Returns:
            str: S3 URI of uploaded model
        """
        logger.info("Uploading trained model to S3...")

        s3_prefix = f"vlm_models/{self.training_job_id}/"

        try:
            # Upload all model files
            for root, dirs, files in os.walk(model_dir):
                for file in files:
                    local_path = os.path.join(root, file)
                    relative_path = os.path.relpath(local_path, model_dir)
                    s3_key = f"{s3_prefix}{relative_path}"

                    self.aws_service.s3_client.upload_file(
                        local_path,
                        self.model_bucket,
                        s3_key
                    )
                    logger.info(f"Uploaded {s3_key}")

            s3_uri = f"s3://{self.model_bucket}/{s3_prefix}"
            logger.info(f"Model uploaded successfully: {s3_uri}")

            # Save metadata
            metadata = {
                'training_job_id': self.training_job_id,
                'base_model': self.base_model,
                's3_uri': s3_uri,
                'timestamp': datetime.utcnow().isoformat()
            }

            metadata_key = f"{s3_prefix}metadata.json"
            self.aws_service.s3_client.put_object(
                Bucket=self.model_bucket,
                Key=metadata_key,
                Body=json.dumps(metadata, indent=2),
                ContentType='application/json'
            )

            return s3_uri

        except Exception as e:
            logger.error(f"Error uploading model: {e}")
            raise

    def run_training_pipeline(self):
        """
        Run complete VLM training pipeline

        Returns:
            dict: Training results
        """
        try:
            # Fetch corrections
            corrections = self.fetch_approved_corrections()

            if len(corrections) < 50:
                logger.warning(f"Only {len(corrections)} corrections available. Minimum 50 recommended.")
                return {
                    'status': 'skipped',
                    'reason': 'insufficient_data',
                    'correction_count': len(corrections),
                    'minimum_required': 50
                }

            # Download training data
            image_paths, texts = self.download_training_data(corrections)

            # Split into train/eval (90/10)
            split_idx = int(len(image_paths) * 0.9)
            train_images = image_paths[:split_idx]
            train_texts = texts[:split_idx]
            eval_images = image_paths[split_idx:]
            eval_texts = texts[split_idx:]

            logger.info(f"Training samples: {len(train_images)}")
            logger.info(f"Evaluation samples: {len(eval_images)}")

            # Create datasets
            train_dataset = OCRDataset(train_images, train_texts, self.processor)
            eval_dataset = OCRDataset(eval_images, eval_texts, self.processor) if eval_images else None

            # Train model
            train_result = self.train_model(train_dataset, eval_dataset)

            # Upload trained model
            s3_uri = self.upload_trained_model(train_result['output_dir'])

            return {
                'status': 'success',
                'training_job_id': self.training_job_id,
                'total_corrections': len(corrections),
                'train_samples': len(train_images),
                'eval_samples': len(eval_images),
                'model_s3_uri': s3_uri,
                'metrics': train_result['metrics']
            }

        except Exception as e:
            logger.error(f"Training pipeline failed: {e}", exc_info=True)
            return {
                'status': 'failed',
                'error': str(e),
                'training_job_id': self.training_job_id
            }

    def cleanup(self):
        """Clean up temporary working directory"""
        try:
            if os.path.exists(self.work_dir):
                shutil.rmtree(self.work_dir)
                logger.info(f"Cleaned up working directory: {self.work_dir}")
        except Exception as e:
            logger.warning(f"Error cleaning up: {e}")


def main():
    """Main entry point for VLM training script"""
    logger.info("Starting VLM training pipeline...")

    # Get base model from environment or use default
    base_model = os.getenv('VLM_BASE_MODEL', 'microsoft/trocr-small-printed')

    trainer = VLMTrainer(base_model=base_model)

    try:
        results = trainer.run_training_pipeline()

        logger.info("Training pipeline completed")
        logger.info(f"Results: {json.dumps(results, indent=2, default=str)}")

        # Record completion in DynamoDB
        if results['status'] == 'success':
            from src.training_counter import TrainingCounter
            counter = TrainingCounter()
            counter.record_training_completion(
                training_job_id=results['training_job_id'],
                status='success',
                model_s3_path=results.get('model_s3_uri')
            )

        return 0 if results['status'] == 'success' else 1

    except Exception as e:
        logger.error(f"Training failed with exception: {e}", exc_info=True)
        return 1

    finally:
        # Keep work_dir for debugging in dev, clean up in production
        if os.getenv('CLEANUP_AFTER_TRAINING', 'false').lower() == 'true':
            trainer.cleanup()


if __name__ == '__main__':
    sys.exit(main())
