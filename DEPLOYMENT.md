# Drishti OCR - AWS Lambda Deployment Guide

This guide will help you deploy the Drishti OCR application to AWS Lambda using ECR (Elastic Container Registry) and API Gateway.

## Prerequisites

1. **AWS CLI** installed and configured
   ```bash
   aws configure
   ```

2. **Docker** installed and running

3. **AWS SAM CLI** installed (for SAM deployment)
   ```bash
   pip install aws-sam-cli
   ```

4. **Required AWS Permissions**:
   - ECR: CreateRepository, PutImage, GetAuthorizationToken
   - Lambda: CreateFunction, UpdateFunctionCode, InvokeFunction
   - IAM: CreateRole, AttachRolePolicy
   - S3: CreateBucket, PutObject, GetObject
   - DynamoDB: CreateTable, PutItem, Query
   - API Gateway: CreateApi, CreateRoute

## Deployment Steps

### Step 1: Configure Environment Variables

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your AWS credentials (optional, if not using AWS CLI credentials):
   ```bash
   AWS_REGION=us-east-1
   S3_WORD_BUCKET=ocr-word-images
   S3_CHAR_BUCKET=ocr-char-images
   DYNAMODB_TABLE=ocr-results
   ```

### Step 2: Build and Push Docker Image to ECR

1. Make the deployment script executable:
   ```bash
   chmod +x deploy-ecr.sh
   ```

2. Run the ECR deployment script:
   ```bash
   ./deploy-ecr.sh
   ```

   Or with custom parameters:
   ```bash
   AWS_REGION=us-east-1 ECR_REPO_NAME=drishti-ocr IMAGE_TAG=v1.0 ./deploy-ecr.sh
   ```

3. Note the **Image URI** from the output - you'll need this for the next step.

### Step 3: Deploy Lambda Function and Infrastructure

#### Option A: Using AWS SAM (Recommended)

1. Build the SAM application:
   ```bash
   sam build
   ```

2. Deploy with guided prompts:
   ```bash
   sam deploy --guided
   ```

   You'll be asked to provide:
   - Stack Name: `drishti-ocr-stack`
   - AWS Region: `us-east-1`
   - ECRImageUri: *[paste the URI from Step 2]*
   - S3WordBucket: `ocr-word-images` (or custom name)
   - S3CharBucket: `ocr-char-images` (or custom name)
   - DynamoDBTable: `ocr-results` (or custom name)

3. Save your configuration when prompted.

4. After deployment, note the outputs:
   - **ApiUrl**: Your API Gateway endpoint
   - **FunctionUrl**: Your Lambda Function URL
   - Bucket names and DynamoDB table name

#### Option B: Manual Lambda Creation via AWS Console

1. Go to **AWS Lambda Console**
2. Click **Create function**
3. Choose **Container image**
4. Enter function name: `DrishtiOCR`
5. Paste the **Image URI** from Step 2
6. Under **Advanced settings**:
   - Memory: 3008 MB
   - Timeout: 15 minutes (900 seconds)
   - Ephemeral storage: 2048 MB

7. Create execution role with permissions:
   - S3 (PutObject, GetObject on your buckets)
   - DynamoDB (PutItem, Query, Scan)
   - CloudWatch Logs (CreateLogGroup, CreateLogStream, PutLogEvents)

8. Add environment variables:
   ```
   AWS_REGION=us-east-1
   S3_WORD_BUCKET=ocr-word-images
   S3_CHAR_BUCKET=ocr-char-images
   DYNAMODB_TABLE=ocr-results
   UPLOAD_FOLDER=/tmp/uploads
   TESSERACT_LANG=san+eng+hin
   ```

9. Create **Function URL** with:
   - Auth type: NONE
   - CORS enabled

### Step 4: Create AWS Resources (if not using SAM)

If you deployed manually, create the following resources:

1. **S3 Buckets**:
   ```bash
   aws s3 mb s3://ocr-word-images --region us-east-1
   aws s3 mb s3://ocr-char-images --region us-east-1
   ```

2. **DynamoDB Table**:
   ```bash
   aws dynamodb create-table \
     --table-name ocr-results \
     --attribute-definitions \
       AttributeName=id,AttributeType=S \
       AttributeName=file_id,AttributeType=S \
     --key-schema \
       AttributeName=id,KeyType=HASH \
     --global-secondary-indexes \
       "[{\"IndexName\":\"file_id-index\",\"KeySchema\":[{\"AttributeName\":\"file_id\",\"KeyType\":\"HASH\"}],\"Projection\":{\"ProjectionType\":\"ALL\"}}]" \
     --billing-mode PAY_PER_REQUEST \
     --region us-east-1
   ```

### Step 5: Test the Deployment

1. Get your function URL from the Lambda console or SAM output

2. Test the health endpoint:
   ```bash
   curl https://your-function-url.lambda-url.us-east-1.on.aws/health
   ```

3. Open the URL in your browser to access the web interface

4. Upload a test document and verify processing

## Architecture

```
User → API Gateway/Lambda URL → Lambda Function → {
  - Tesseract OCR Processing
  - S3 (Word & Character Images)
  - DynamoDB (OCR Results)
}
```

## Lambda Configuration

- **Runtime**: Container (Python 3.11 base)
- **Memory**: 3008 MB (recommended for image processing)
- **Timeout**: 900 seconds (15 minutes max)
- **Ephemeral Storage**: 2048 MB (for temporary file storage)

## Cost Considerations

1. **Lambda**:
   - Free tier: 1M requests/month, 400,000 GB-seconds
   - After: $0.20 per 1M requests + compute time

2. **S3**:
   - Storage: $0.023 per GB/month
   - Requests: Minimal cost

3. **DynamoDB**:
   - On-demand pricing: $1.25 per million writes, $0.25 per million reads

4. **ECR**:
   - Storage: $0.10 per GB/month

## Updating the Application

To update your Lambda function after making changes:

1. Rebuild and push the Docker image:
   ```bash
   ./deploy-ecr.sh
   ```

2. Update Lambda function:
   ```bash
   sam deploy
   ```

   Or manually update the function in the AWS Console to use the new image.

## Monitoring

1. **CloudWatch Logs**: Check Lambda execution logs
   ```bash
   aws logs tail /aws/lambda/DrishtiOCR --follow
   ```

2. **CloudWatch Metrics**: Monitor invocations, duration, errors

3. **X-Ray**: Enable for distributed tracing (optional)

## Troubleshooting

### Issue: Lambda timeout
- **Solution**: Increase timeout to 900s or optimize OCR processing

### Issue: Out of memory
- **Solution**: Increase Lambda memory (up to 10,240 MB)

### Issue: Storage space error
- **Solution**: Increase ephemeral storage (up to 10,240 MB)

### Issue: Image too large
- **Solution**: Optimize Docker image, remove unnecessary dependencies

### Issue: Tesseract not found
- **Solution**: Verify Tesseract installation in Dockerfile

## Security Considerations

1. **Remove hardcoded credentials** from `config.py`:
   - Use environment variables
   - Use IAM roles for Lambda execution

2. **Enable authentication** on Lambda Function URL if needed

3. **Set up S3 bucket policies** to restrict access

4. **Enable encryption** for S3 buckets and DynamoDB

## Clean Up

To remove all resources:

```bash
sam delete --stack-name drishti-ocr-stack
```

Or manually delete:
- Lambda function
- ECR repository
- S3 buckets
- DynamoDB table
- CloudWatch log groups
- IAM roles

## Support

For issues or questions, refer to:
- AWS Lambda Documentation
- AWS SAM Documentation
- Tesseract OCR Documentation
