#!/bin/bash

# Configuration
AWS_REGION="us-east-1"
FUNCTION_NAME="DrishtiOCR"
ROLE_NAME="DrishtiOCRLambdaRole"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/drishti-ocr:latest"

echo "=========================================="
echo "Setting up Lambda Function"
echo "=========================================="
echo "Account ID: $AWS_ACCOUNT_ID"
echo "Function: $FUNCTION_NAME"
echo "Image URI: $ECR_IMAGE_URI"
echo "=========================================="

# Create IAM role for Lambda
echo ""
echo "Creating IAM role..."

# Check if role exists
aws iam get-role --role-name $ROLE_NAME 2>/dev/null
if [ $? -ne 0 ]; then
    # Create trust policy
    cat > /tmp/trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

    aws iam create-role \
        --role-name $ROLE_NAME \
        --assume-role-policy-document file:///tmp/trust-policy.json

    # Attach basic execution policy
    aws iam attach-role-policy \
        --role-name $ROLE_NAME \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

    # Create and attach custom policy for S3 and DynamoDB
    cat > /tmp/lambda-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::ocr-word-images/*",
        "arn:aws:s3:::ocr-char-images/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:BatchWriteItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:${AWS_REGION}:${AWS_ACCOUNT_ID}:table/ocr-results",
        "arn:aws:dynamodb:${AWS_REGION}:${AWS_ACCOUNT_ID}:table/ocr-results/index/*"
      ]
    }
  ]
}
EOF

    aws iam put-role-policy \
        --role-name $ROLE_NAME \
        --policy-name DrishtiOCRPolicy \
        --policy-document file:///tmp/lambda-policy.json

    echo "Waiting 10 seconds for IAM role to propagate..."
    sleep 10
else
    echo "Role already exists."
fi

ROLE_ARN=$(aws iam get-role --role-name $ROLE_NAME --query 'Role.Arn' --output text)

# Create Lambda function
echo ""
echo "Creating Lambda function..."

aws lambda create-function \
    --function-name $FUNCTION_NAME \
    --package-type Image \
    --code ImageUri=$ECR_IMAGE_URI \
    --role $ROLE_ARN \
    --timeout 900 \
    --memory-size 3008 \
    --ephemeral-storage Size=2048 \
    --environment "Variables={S3_WORD_BUCKET=ocr-word-images,S3_CHAR_BUCKET=ocr-char-images,DYNAMODB_TABLE=ocr-results,UPLOAD_FOLDER=/tmp/uploads,TESSERACT_LANG=san+eng+hin}" \
    --region $AWS_REGION

if [ $? -eq 0 ]; then
    echo "Lambda function created successfully!"

    # Create Function URL
    echo ""
    echo "Creating Function URL..."
    aws lambda create-function-url-config \
        --function-name $FUNCTION_NAME \
        --auth-type NONE \
        --cors "AllowOrigins=*,AllowMethods=*,AllowHeaders=*" \
        --region $AWS_REGION

    # Add permission for Function URL
    aws lambda add-permission \
        --function-name $FUNCTION_NAME \
        --statement-id FunctionURLAllowPublicAccess \
        --action lambda:InvokeFunctionUrl \
        --principal "*" \
        --function-url-auth-type NONE \
        --region $AWS_REGION

    # Get Function URL
    FUNCTION_URL=$(aws lambda get-function-url-config \
        --function-name $FUNCTION_NAME \
        --region $AWS_REGION \
        --query 'FunctionUrl' \
        --output text)

    echo ""
    echo "=========================================="
    echo "Setup Complete!"
    echo "=========================================="
    echo "Function URL: $FUNCTION_URL"
    echo "=========================================="
else
    echo "Failed to create Lambda function. The image might not exist in ECR yet."
    echo "Wait for GitHub Actions to build and push the image, then run this script again."
fi

# Cleanup temp files
rm -f /tmp/trust-policy.json /tmp/lambda-policy.json
