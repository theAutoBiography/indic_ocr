#!/usr/bin/env python3
"""
Create DynamoDB table for Sandhi corrections
"""

import boto3
from botocore.exceptions import ClientError
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Config

def create_sandhi_table():
    """Create the sandhi-corrections DynamoDB table"""

    dynamodb = boto3.resource(
        'dynamodb',
        region_name=Config.AWS_REGION,
        aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY
    )

    table_name = Config.SANDHI_TABLE

    try:
        # Check if table already exists
        existing_table = dynamodb.Table(table_name)
        existing_table.load()
        print(f"✓ Table '{table_name}' already exists")
        return existing_table
    except ClientError as e:
        if e.response['Error']['Code'] != 'ResourceNotFoundException':
            raise

    print(f"Creating table '{table_name}'...")

    table = dynamodb.create_table(
        TableName=table_name,
        KeySchema=[
            {
                'AttributeName': 'correction_id',
                'KeyType': 'HASH'  # Partition key
            },
            {
                'AttributeName': 'timestamp',
                'KeyType': 'RANGE'  # Sort key
            }
        ],
        AttributeDefinitions=[
            {
                'AttributeName': 'correction_id',
                'AttributeType': 'S'
            },
            {
                'AttributeName': 'timestamp',
                'AttributeType': 'N'
            },
            {
                'AttributeName': 'corpus_entry_id',
                'AttributeType': 'S'
            }
        ],
        GlobalSecondaryIndexes=[
            {
                'IndexName': 'corpus-entry-index',
                'KeySchema': [
                    {
                        'AttributeName': 'corpus_entry_id',
                        'KeyType': 'HASH'
                    },
                    {
                        'AttributeName': 'timestamp',
                        'KeyType': 'RANGE'
                    }
                ],
                'Projection': {
                    'ProjectionType': 'ALL'
                },
                'ProvisionedThroughput': {
                    'ReadCapacityUnits': 5,
                    'WriteCapacityUnits': 5
                }
            }
        ],
        BillingMode='PROVISIONED',
        ProvisionedThroughput={
            'ReadCapacityUnits': 5,
            'WriteCapacityUnits': 5
        }
    )

    # Wait for the table to be created
    print("Waiting for table to be created...")
    table.wait_until_exists()

    print(f"✓ Table '{table_name}' created successfully!")
    print(f"\nTable details:")
    print(f"  - Table name: {table.table_name}")
    print(f"  - Table ARN: {table.table_arn}")
    print(f"  - Item count: {table.item_count}")
    print(f"  - Status: {table.table_status}")

    return table


if __name__ == '__main__':
    try:
        create_sandhi_table()
    except Exception as e:
        print(f"\n✗ Error: {str(e)}", file=sys.stderr)
        sys.exit(1)
