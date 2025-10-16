#!/bin/bash

# Configuration
AWS_REGION="${AWS_REGION:-us-east-1}"
ECR_REPO_NAME="${ECR_REPO_NAME:-drishti-ocr}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

echo "=========================================="
echo "Deploying Drishti OCR to AWS ECR"
echo "=========================================="
echo "Region: $AWS_REGION"
echo "Repository: $ECR_REPO_NAME"
echo "Tag: $IMAGE_TAG"
echo "=========================================="

# Get AWS Account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo "Error: Unable to get AWS Account ID. Make sure AWS CLI is configured."
    exit 1
fi
echo "AWS Account ID: $AWS_ACCOUNT_ID"

# ECR Repository URI
ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"

# Create ECR repository if it doesn't exist
echo ""
echo "Creating ECR repository (if it doesn't exist)..."
aws ecr describe-repositories --repository-names $ECR_REPO_NAME --region $AWS_REGION > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "Repository doesn't exist. Creating..."
    aws ecr create-repository \
        --repository-name $ECR_REPO_NAME \
        --region $AWS_REGION \
        --image-scanning-configuration scanOnPush=true
    echo "Repository created successfully!"
else
    echo "Repository already exists."
fi

# Authenticate Docker to ECR
echo ""
echo "Authenticating Docker to ECR..."
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_URI
if [ $? -ne 0 ]; then
    echo "Error: Failed to authenticate to ECR"
    exit 1
fi
echo "Authentication successful!"

# Build Docker image
echo ""
echo "Building Docker image..."
docker build -t $ECR_REPO_NAME:$IMAGE_TAG .
if [ $? -ne 0 ]; then
    echo "Error: Docker build failed"
    exit 1
fi
echo "Docker image built successfully!"

# Tag image for ECR
echo ""
echo "Tagging image for ECR..."
docker tag $ECR_REPO_NAME:$IMAGE_TAG $ECR_URI:$IMAGE_TAG
echo "Image tagged as: $ECR_URI:$IMAGE_TAG"

# Push to ECR
echo ""
echo "Pushing image to ECR..."
docker push $ECR_URI:$IMAGE_TAG
if [ $? -ne 0 ]; then
    echo "Error: Failed to push image to ECR"
    exit 1
fi
echo "Image pushed successfully!"

# Output the image URI
echo ""
echo "=========================================="
echo "Deployment completed successfully!"
echo "=========================================="
echo "Image URI: $ECR_URI:$IMAGE_TAG"
echo ""
echo "Use this URI when creating your Lambda function."
echo "=========================================="
