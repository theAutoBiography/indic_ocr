import boto3
import io
import os
from src.config import Config
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import logging

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)


class AWSService:
    def __init__(self):
        # Check if running in Lambda (AWS_EXECUTION_ENV is set in Lambda)
        # or if credentials are explicitly provided (local development)
        is_lambda = 'AWS_EXECUTION_ENV' in os.environ or 'AWS_LAMBDA_FUNCTION_NAME' in os.environ

        if is_lambda or not Config.AWS_ACCESS_KEY_ID:
            # Use Lambda execution role or default credentials chain
            self.s3_client = boto3.client('s3', region_name=Config.AWS_REGION)
            self.dynamodb = boto3.resource('dynamodb', region_name=Config.AWS_REGION)
        else:
            # Use explicit credentials for local development
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
                region_name=Config.AWS_REGION
            )

            self.dynamodb = boto3.resource(
                'dynamodb',
                aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
                region_name=Config.AWS_REGION
            )

        self.table = self.dynamodb.Table(Config.DYNAMODB_TABLE)
        self.executor = ThreadPoolExecutor(max_workers=10)

    def upload_to_s3_async(self, image_bytes, filename, bucket_name):
        """Upload image to S3 asynchronously"""
        future = self.executor.submit(self._upload_to_s3, image_bytes, filename, bucket_name)
        return future

    def _upload_to_s3(self, image_bytes, filename, bucket_name):
        """Internal method to upload to S3"""
        try:
            self.s3_client.put_object(
                Bucket=bucket_name,
                Key=filename,
                Body=image_bytes,
                ContentType='image/png'
            )
            return f"s3://{bucket_name}/{filename}"
        except Exception as e:
            logger.error(f"Error uploading to S3: {e}")
            raise

    def save_to_dynamodb(self, items):
        """Save OCR results to DynamoDB"""
        try:
            with self.table.batch_writer() as batch:
                for item in items:
                    # Convert floats to Decimal for DynamoDB
                    converted_item = self._convert_floats_to_decimal(item)
                    batch.put_item(Item=converted_item)
        except Exception as e:
            logger.error(f"Error saving to DynamoDB: {e}")
            raise

    def _convert_floats_to_decimal(self, obj):
        """Recursively convert float values to Decimal for DynamoDB compatibility"""
        if isinstance(obj, float):
            return Decimal(str(obj))
        elif isinstance(obj, dict):
            return {k: self._convert_floats_to_decimal(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_floats_to_decimal(item) for item in obj]
        return obj

    def shutdown(self):
        """Shutdown executor"""
        self.executor.shutdown(wait=True)
