#!/bin/bash

# Create enhanced DynamoDB table for OCR with multi-language support and corrections

AWS_REGION="${AWS_REGION:-us-east-1}"
TABLE_NAME="ocr-results-v2"

echo "=========================================="
echo "Creating DynamoDB Table: $TABLE_NAME"
echo "=========================================="

aws dynamodb create-table \
  --table-name $TABLE_NAME \
  --attribute-definitions \
    AttributeName=file_id,AttributeType=S \
    AttributeName=page#word_index,AttributeType=S \
    AttributeName=language,AttributeType=S \
    AttributeName=confidence,AttributeType=N \
    AttributeName=is_corrected,AttributeType=S \
    AttributeName=corrected_at,AttributeType=S \
    AttributeName=is_low_confidence,AttributeType=S \
    AttributeName=file_page_word,AttributeType=S \
  --key-schema \
    AttributeName=file_id,KeyType=HASH \
    AttributeName=page#word_index,KeyType=RANGE \
  --global-secondary-indexes \
    '[
      {
        "IndexName": "GSI-Language-Confidence",
        "KeySchema": [
          {"AttributeName": "language", "KeyType": "HASH"},
          {"AttributeName": "confidence", "KeyType": "RANGE"}
        ],
        "Projection": {
          "ProjectionType": "ALL"
        }
      },
      {
        "IndexName": "GSI-Corrections",
        "KeySchema": [
          {"AttributeName": "is_corrected", "KeyType": "HASH"},
          {"AttributeName": "corrected_at", "KeyType": "RANGE"}
        ],
        "Projection": {
          "ProjectionType": "ALL"
        }
      },
      {
        "IndexName": "GSI-LowConfidence",
        "KeySchema": [
          {"AttributeName": "is_low_confidence", "KeyType": "HASH"},
          {"AttributeName": "file_page_word", "KeyType": "RANGE"}
        ],
        "Projection": {
          "ProjectionType": "ALL"
        }
      }
    ]' \
  --billing-mode PAY_PER_REQUEST \
  --region $AWS_REGION

if [ $? -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "Table created successfully!"
    echo "=========================================="
    echo "Table Name: $TABLE_NAME"
    echo "Region: $AWS_REGION"
    echo ""
    echo "Waiting for table to become ACTIVE..."
    aws dynamodb wait table-exists --table-name $TABLE_NAME --region $AWS_REGION
    echo "Table is now ACTIVE!"
    echo ""
    echo "Next steps:"
    echo "1. Update DYNAMODB_TABLE in .env or Lambda env vars to: $TABLE_NAME"
    echo "2. Deploy updated code"
else
    echo "Error creating table!"
    exit 1
fi
