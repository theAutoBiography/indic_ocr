#!/usr/bin/env python3
"""
Script to add GSI-ImageHash and GSI-FileHash indexes to DynamoDB table
Run this once to update your table schema
"""
import boto3
from src.config import Config

def add_indexes():
    """Add GSI-ImageHash and GSI-FileHash indexes to the DynamoDB table"""
    dynamodb = boto3.client('dynamodb')

    try:
        # Get current table description
        response = dynamodb.describe_table(TableName=Config.DYNAMODB_TABLE)
        table = response['Table']

        # Check if indexes already exist
        existing_indexes = {gsi['IndexName'] for gsi in table.get('GlobalSecondaryIndexes', [])}

        updates = []

        # Check billing mode
        billing_mode = table.get('BillingModeSummary', {}).get('BillingMode', 'PROVISIONED')
        is_on_demand = billing_mode == 'PAY_PER_REQUEST'

        # Add GSI-ImageHash if it doesn't exist
        if 'GSI-ImageHash' not in existing_indexes:
            print("Adding GSI-ImageHash index...")
            index_config = {
                'Create': {
                    'IndexName': 'GSI-ImageHash',
                    'KeySchema': [
                        {'AttributeName': 'image_hash', 'KeyType': 'HASH'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'}
                }
            }
            # Only add provisioned throughput if not on-demand
            if not is_on_demand:
                index_config['Create']['ProvisionedThroughput'] = {
                    'ReadCapacityUnits': 5,
                    'WriteCapacityUnits': 5
                }
            updates.append(index_config)
        else:
            print("GSI-ImageHash already exists")

        # Add GSI-FileHash if it doesn't exist
        if 'GSI-FileHash' not in existing_indexes:
            print("Adding GSI-FileHash index...")
            index_config = {
                'Create': {
                    'IndexName': 'GSI-FileHash',
                    'KeySchema': [
                        {'AttributeName': 'file_hash', 'KeyType': 'HASH'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'}
                }
            }
            # Only add provisioned throughput if not on-demand
            if not is_on_demand:
                index_config['Create']['ProvisionedThroughput'] = {
                    'ReadCapacityUnits': 5,
                    'WriteCapacityUnits': 5
                }
            updates.append(index_config)
        else:
            print("GSI-FileHash already exists")

        if not updates:
            print("All indexes already exist. No updates needed.")
            return

        # Create indexes one at a time (DynamoDB limitation)
        for update in updates:
            index_name = update['Create']['IndexName']
            attribute_name = update['Create']['KeySchema'][0]['AttributeName']

            # Define attribute definition for this index
            attribute_definitions = [
                {'AttributeName': attribute_name, 'AttributeType': 'S'}
            ]

            # Update table with this index
            print(f"\nUpdating table '{Config.DYNAMODB_TABLE}' with {index_name}...")
            dynamodb.update_table(
                TableName=Config.DYNAMODB_TABLE,
                AttributeDefinitions=attribute_definitions,
                GlobalSecondaryIndexUpdates=[update]
            )

            print(f"✓ {index_name} creation initiated!")

            if len(updates) > 1:
                print(f"\nNote: You can only create one index at a time.")
                print(f"After {index_name} becomes ACTIVE, run this script again to create the next index.")
                break

        print("\nNote: Index creation is asynchronous and may take several minutes.")
        print("Check the AWS Console or run 'aws dynamodb describe-table --table-name {}'".format(Config.DYNAMODB_TABLE))
        print("to monitor the index status. Wait until status is 'ACTIVE' before proceeding.")

    except Exception as e:
        print(f"\n✗ Error updating table: {e}")
        print("\nIf you're using local DynamoDB, you may need to recreate the table with the new indexes.")
        return 1

    return 0

if __name__ == '__main__':
    import sys
    sys.exit(add_indexes())
