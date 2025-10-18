"""
Training counter management for tracking corrections and triggering model retraining
"""
import boto3
from decimal import Decimal
from datetime import datetime
import logging
from src.config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TrainingCounter:
    """Manages the training counter in DynamoDB"""

    # DynamoDB table for tracking training metadata
    TRAINING_TABLE = 'ocr-training-metadata'
    COUNTER_KEY = 'correction_counter'
    TRAINING_THRESHOLD = 50

    def __init__(self, aws_service=None):
        """
        Initialize training counter

        Args:
            aws_service: Optional AWSService instance. If None, creates new one.
        """
        if aws_service:
            self.dynamodb = aws_service.dynamodb
        else:
            from src.aws_service import AWSService
            aws = AWSService()
            self.dynamodb = aws.dynamodb

        self.table = self.dynamodb.Table(self.TRAINING_TABLE)

    def increment_counter(self):
        """
        Increment the correction counter by 1

        Returns:
            dict: Contains new_count and should_trigger_training boolean
        """
        try:
            response = self.table.update_item(
                Key={'counter_id': self.COUNTER_KEY},
                UpdateExpression='ADD correction_count :inc SET last_updated = :timestamp',
                ExpressionAttributeValues={
                    ':inc': 1,
                    ':timestamp': datetime.utcnow().isoformat()
                },
                ReturnValues='ALL_NEW'
            )

            new_count = int(response['Attributes']['correction_count'])
            should_trigger = new_count >= self.TRAINING_THRESHOLD

            logger.info(f"Training counter incremented to {new_count}")

            return {
                'new_count': new_count,
                'should_trigger_training': should_trigger,
                'threshold': self.TRAINING_THRESHOLD
            }

        except Exception as e:
            logger.error(f"Error incrementing training counter: {e}")
            # Initialize counter if it doesn't exist
            try:
                self.table.put_item(
                    Item={
                        'counter_id': self.COUNTER_KEY,
                        'correction_count': 1,
                        'last_updated': datetime.utcnow().isoformat(),
                        'created_at': datetime.utcnow().isoformat()
                    }
                )
                logger.info("Training counter initialized to 1")
                return {
                    'new_count': 1,
                    'should_trigger_training': False,
                    'threshold': self.TRAINING_THRESHOLD
                }
            except Exception as init_error:
                logger.error(f"Error initializing training counter: {init_error}")
                raise

    def reset_counter(self, training_job_id):
        """
        Reset counter after training job is triggered

        Args:
            training_job_id: ID of the training job that was started
        """
        try:
            self.table.update_item(
                Key={'counter_id': self.COUNTER_KEY},
                UpdateExpression='''
                    SET correction_count = :zero,
                        last_training_triggered = :timestamp,
                        last_training_job_id = :job_id
                ''',
                ExpressionAttributeValues={
                    ':zero': 0,
                    ':timestamp': datetime.utcnow().isoformat(),
                    ':job_id': training_job_id
                }
            )
            logger.info(f"Training counter reset after triggering job {training_job_id}")
        except Exception as e:
            logger.error(f"Error resetting training counter: {e}")
            raise

    def get_counter_status(self):
        """
        Get current counter status

        Returns:
            dict: Counter status including count and last training info
        """
        try:
            response = self.table.get_item(
                Key={'counter_id': self.COUNTER_KEY}
            )

            if 'Item' not in response:
                return {
                    'correction_count': 0,
                    'last_updated': None,
                    'last_training_triggered': None,
                    'threshold': self.TRAINING_THRESHOLD,
                    'progress_percent': 0
                }

            item = response['Item']
            count = int(item.get('correction_count', 0))

            return {
                'correction_count': count,
                'last_updated': item.get('last_updated'),
                'last_training_triggered': item.get('last_training_triggered'),
                'last_training_job_id': item.get('last_training_job_id'),
                'threshold': self.TRAINING_THRESHOLD,
                'progress_percent': min(100, (count / self.TRAINING_THRESHOLD) * 100)
            }

        except Exception as e:
            logger.error(f"Error getting counter status: {e}")
            raise

    def record_training_completion(self, training_job_id, status, model_s3_path=None, error=None):
        """
        Record training job completion status

        Args:
            training_job_id: ID of the completed training job
            status: 'success' or 'failed'
            model_s3_path: S3 path to trained model (if successful)
            error: Error message (if failed)
        """
        try:
            # Create or update training history record
            history_item = {
                'training_job_id': training_job_id,
                'status': status,
                'completed_at': datetime.utcnow().isoformat(),
            }

            if model_s3_path:
                history_item['model_s3_path'] = model_s3_path
            if error:
                history_item['error'] = error

            self.table.put_item(Item=history_item)

            # Update counter metadata with last completion
            self.table.update_item(
                Key={'counter_id': self.COUNTER_KEY},
                UpdateExpression='''
                    SET last_training_completed = :timestamp,
                        last_training_status = :status
                ''',
                ExpressionAttributeValues={
                    ':timestamp': datetime.utcnow().isoformat(),
                    ':status': status
                }
            )

            logger.info(f"Training job {training_job_id} marked as {status}")

        except Exception as e:
            logger.error(f"Error recording training completion: {e}")
            raise


def initialize_training_table():
    """
    Initialize the training metadata table in DynamoDB.
    Run this once during setup.
    """
    import boto3
    from botocore.exceptions import ClientError

    dynamodb = boto3.client('dynamodb', region_name=Config.AWS_REGION)

    try:
        dynamodb.create_table(
            TableName=TrainingCounter.TRAINING_TABLE,
            KeySchema=[
                {'AttributeName': 'counter_id', 'KeyType': 'HASH'},  # Partition key
            ],
            AttributeDefinitions=[
                {'AttributeName': 'counter_id', 'AttributeType': 'S'},
                {'AttributeName': 'training_job_id', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'GSI-TrainingHistory',
                    'KeySchema': [
                        {'AttributeName': 'training_job_id', 'KeyType': 'HASH'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )

        # Wait for table to be created
        dynamodb.get_waiter('table_exists').wait(
            TableName=TrainingCounter.TRAINING_TABLE
        )

        logger.info(f"Created table {TrainingCounter.TRAINING_TABLE}")
        return True

    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceInUseException':
            logger.info(f"Table {TrainingCounter.TRAINING_TABLE} already exists")
            return True
        else:
            logger.error(f"Error creating training table: {e}")
            raise


if __name__ == '__main__':
    # Initialize table when run directly
    initialize_training_table()
