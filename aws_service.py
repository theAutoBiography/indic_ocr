import boto3
import io
from config import Config
from concurrent.futures import ThreadPoolExecutor
import logging

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)


class AWSService:
    def __init__(self):
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
                    batch.put_item(Item=item)
        except Exception as e:
            logger.error(f"Error saving to DynamoDB: {e}")
            raise

    def shutdown(self):
        """Shutdown executor"""
        self.executor.shutdown(wait=True)
