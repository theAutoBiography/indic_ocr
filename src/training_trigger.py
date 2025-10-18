"""
Service to trigger VLM training jobs on ECS Fargate
"""
import boto3
import logging
from datetime import datetime
import os
from src.config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TrainingJobTrigger:
    """Handles triggering of ECS training tasks"""

    def __init__(self):
        self.ecs_client = boto3.client('ecs', region_name=Config.AWS_REGION)
        self.cluster_name = os.getenv('ECS_TRAINING_CLUSTER', 'drishti-ocr-training-cluster')
        self.task_definition = os.getenv('ECS_TRAINING_TASK_DEF', 'drishti-ocr-training-task')
        self.subnet_ids = os.getenv('ECS_SUBNET_IDS', '').split(',')
        self.security_group_ids = os.getenv('ECS_SECURITY_GROUP_IDS', '').split(',')

    def trigger_training_task(self):
        """
        Trigger a new ECS Fargate training task

        Returns:
            dict: Contains job_id (task ARN) and status
        """
        job_id = f"training_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        logger.info(f"Triggering training task: {job_id}")

        try:
            # Run ECS task
            response = self.ecs_client.run_task(
                cluster=self.cluster_name,
                taskDefinition=self.task_definition,
                launchType='FARGATE',
                networkConfiguration={
                    'awsvpcConfiguration': {
                        'subnets': [s.strip() for s in self.subnet_ids if s.strip()],
                        'securityGroups': [sg.strip() for sg in self.security_group_ids if sg.strip()],
                        'assignPublicIp': 'ENABLED'
                    }
                },
                overrides={
                    'containerOverrides': [
                        {
                            'name': 'training-container',
                            'environment': [
                                {
                                    'name': 'TRAINING_JOB_ID',
                                    'value': job_id
                                },
                                {
                                    'name': 'AWS_REGION',
                                    'value': Config.AWS_REGION
                                }
                            ]
                        }
                    ]
                },
                tags=[
                    {
                        'key': 'JobType',
                        'value': 'TesseractTraining'
                    },
                    {
                        'key': 'JobId',
                        'value': job_id
                    },
                    {
                        'key': 'Timestamp',
                        'value': datetime.utcnow().isoformat()
                    }
                ]
            )

            # Extract task ARN from response
            if response.get('tasks') and len(response['tasks']) > 0:
                task_arn = response['tasks'][0]['taskArn']
                logger.info(f"Training task started: {task_arn}")

                return {
                    'success': True,
                    'job_id': job_id,
                    'task_arn': task_arn,
                    'cluster': self.cluster_name,
                    'status': 'RUNNING'
                }
            else:
                # Task failed to start
                failures = response.get('failures', [])
                error_msg = f"Failed to start training task: {failures}"
                logger.error(error_msg)

                return {
                    'success': False,
                    'job_id': job_id,
                    'error': error_msg,
                    'failures': failures
                }

        except Exception as e:
            logger.error(f"Error triggering training task: {e}")
            return {
                'success': False,
                'job_id': job_id,
                'error': str(e)
            }

    def get_task_status(self, task_arn):
        """
        Get status of a running training task

        Args:
            task_arn: ARN of the ECS task

        Returns:
            dict: Task status information
        """
        try:
            response = self.ecs_client.describe_tasks(
                cluster=self.cluster_name,
                tasks=[task_arn]
            )

            if response.get('tasks') and len(response['tasks']) > 0:
                task = response['tasks'][0]

                return {
                    'task_arn': task_arn,
                    'status': task.get('lastStatus'),
                    'desired_status': task.get('desiredStatus'),
                    'started_at': task.get('startedAt'),
                    'stopped_at': task.get('stoppedAt'),
                    'stop_code': task.get('stopCode'),
                    'stopped_reason': task.get('stoppedReason'),
                    'containers': [
                        {
                            'name': c.get('name'),
                            'status': c.get('lastStatus'),
                            'exit_code': c.get('exitCode')
                        }
                        for c in task.get('containers', [])
                    ]
                }
            else:
                return {
                    'task_arn': task_arn,
                    'status': 'NOT_FOUND',
                    'error': 'Task not found'
                }

        except Exception as e:
            logger.error(f"Error getting task status: {e}")
            return {
                'task_arn': task_arn,
                'status': 'ERROR',
                'error': str(e)
            }


def trigger_training_job():
    """
    Convenience function to trigger a training job

    Returns:
        dict: Training job result
    """
    trigger = TrainingJobTrigger()
    return trigger.trigger_training_task()


def get_training_job_status(task_arn):
    """
    Convenience function to get training job status

    Args:
        task_arn: ARN of the training task

    Returns:
        dict: Task status
    """
    trigger = TrainingJobTrigger()
    return trigger.get_task_status(task_arn)


if __name__ == '__main__':
    # Test trigger
    result = trigger_training_job()
    logger.info(f"Trigger result: {result}")
