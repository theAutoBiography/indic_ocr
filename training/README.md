# VLM Training Pipeline for OCR

Automated pipeline for training Vision Language Models on manual corrections, triggering retraining after every 50 approved corrections.

## Architecture

```
User Correction → DynamoDB → Counter Increment → Threshold (50) → ECS Task → Train VLM → S3 Model
                                                                              ↓
                                                                    Update Training Metadata
```

## Components

### 1. **Training Counter** (`src/training_counter.py`)
- Tracks approved corrections in DynamoDB (`ocr-training-metadata` table)
- Increments on each `approve_for_training=true` correction
- Triggers training when count reaches 50
- Resets after training job starts

### 2. **VLM Training Script** (`training/scripts/train_vlm.py`)
- Fetches approved corrections from DynamoDB
- Downloads word images from S3
- Fine-tunes TrOCR model (microsoft/trocr-small-printed)
- Single multilingual model for all Indian languages
- Uploads trained model to S3

### 3. **Training Trigger** (`src/training_trigger.py`)
- Launches ECS Fargate task for training
- Passes environment variables and job metadata
- Tracks task status

### 4. **Training Infrastructure**
- **ECS Cluster**: `drishti-ocr-training-cluster`
- **Task Definition**: `drishti-ocr-training-task`
- **Resources**: 2 vCPU, 4GB RAM (configurable)
- **S3 Bucket**: `ocr-trained-models` for model storage

## Model Details

### Base Model: TrOCR-small
- **Architecture**: ViT encoder + RoBERTa decoder
- **Size**: ~200MB
- **Training**: Fine-tuned on correction data
- **Multilingual**: Single model for all languages
  - Scripts: Devanagari, Tamil, Telugu, Kannada, Malayalam, Bengali, etc.
  - Transfer learning across similar scripts
  - Natural script distinction through training

### Training Configuration
- **Epochs**: 10
- **Batch Size**: 8
- **Learning Rate**: 5e-5
- **Train/Eval Split**: 90/10
- **Metric**: Character Error Rate (CER)
- **Mixed Precision**: FP16 (if GPU available)

## Setup Instructions

### 1. Initialize Training Infrastructure

```bash
cd training/scripts
chmod +x setup_training_infrastructure.sh
./setup_training_infrastructure.sh
```

This creates:
- ECR repository for training images
- DynamoDB table for training metadata
- S3 bucket for trained models
- ECS cluster and task definition
- IAM roles for training tasks

### 2. Update Environment Variables

Add to your main app's `.env` or ECS environment:

```bash
# Training Configuration
ECS_TRAINING_CLUSTER=drishti-ocr-training-cluster
ECS_TRAINING_TASK_DEF=drishti-ocr-training-task
ECS_SUBNET_IDS=subnet-xxx,subnet-yyy
ECS_SECURITY_GROUP_IDS=sg-xxx
S3_MODEL_BUCKET=ocr-trained-models

# VLM Configuration
VLM_BASE_MODEL=microsoft/trocr-small-printed  # Optional, defaults to this
```

### 3. Build and Push Training Image

```bash
# Build training Docker image
docker build -f training/Dockerfile -t drishti-ocr-training:latest .

# Tag and push to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com

docker tag drishti-ocr-training:latest ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/drishti-ocr-training:latest
docker push ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/drishti-ocr-training:latest
```

## Usage

### Automatic Triggering

Training automatically triggers when 50 corrections are approved:

1. User corrects a word via `/api/correction` endpoint
2. Sets `approve_for_training: true` in request body
3. Counter increments in DynamoDB
4. At 50th correction, ECS training task launches
5. Counter resets to 0
6. Training runs in background (10-30 minutes depending on data size)
7. Trained model saved to S3

### Manual Triggering

```python
from src.training_trigger import trigger_training_job

result = trigger_training_job()
print(result)  # {'job_id': 'training_20251017_143022', 'task_arn': '...', 'status': 'RUNNING'}
```

### Check Counter Status

```python
from src.training_counter import TrainingCounter

counter = TrainingCounter()
status = counter.get_counter_status()
print(status)
# {
#   'correction_count': 37,
#   'threshold': 50,
#   'progress_percent': 74.0,
#   'last_training_triggered': '2025-10-17T14:30:22'
# }
```

### Monitor Training Job

```bash
# View ECS task logs
aws logs tail /ecs/drishti-ocr-training --follow --region us-east-1

# Check task status
aws ecs describe-tasks \
  --cluster drishti-ocr-training-cluster \
  --tasks TASK_ARN \
  --region us-east-1
```

## API Integration

### Submit Correction with Training Approval

```bash
curl -X POST https://drishtiocr.in/api/correction \
  -H "Content-Type: application/json" \
  -d '{
    "file_id": "abc-123",
    "page": 1,
    "word_index": 5,
    "corrected_text": "देवनागरी",
    "approve_for_training": true
  }'
```

Response includes training status:
```json
{
  "success": true,
  "message": "Correction submitted successfully",
  "training_status": {
    "count": 37,
    "threshold": 50,
    "progress_percent": 74.0
  }
}
```

When threshold is reached:
```json
{
  "success": true,
  "message": "Correction submitted successfully",
  "training_status": {
    "count": 50,
    "threshold": 50,
    "progress_percent": 100.0,
    "training_triggered": true,
    "job_id": "training_20251017_143022"
  }
}
```

## Training Outputs

### S3 Structure

```
s3://ocr-trained-models/
  vlm_models/
    20251017_143022/
      config.json
      pytorch_model.bin
      preprocessor_config.json
      tokenizer.json
      tokenizer_config.json
      special_tokens_map.json
      vocab.txt
      metadata.json
```

### Metadata Format

```json
{
  "training_job_id": "20251017_143022",
  "base_model": "microsoft/trocr-small-printed",
  "s3_uri": "s3://ocr-trained-models/vlm_models/20251017_143022/",
  "timestamp": "2025-10-17T14:30:22.123456",
  "train_samples": 450,
  "eval_samples": 50,
  "metrics": {
    "train_loss": 0.234,
    "eval_cer": 0.023
  }
}
```

## Cost Optimization

### Estimated Costs (per training run)
- **ECS Fargate**: 2 vCPU, 4GB RAM for ~20 mins = $0.15
- **S3 Storage**: ~200MB model = $0.005/month
- **Data Transfer**: Minimal (within same region)
- **DynamoDB**: On-demand pricing, negligible
- **Total per run**: ~$0.15

### Cost Savings
- Use Fargate Spot for 70% discount (add in task definition)
- Clean up old models after validation
- Use lifecycle policies on S3 bucket

## Monitoring

### CloudWatch Metrics
- Training task duration
- Training success/failure rate
- Model upload size
- Counter status

### Alarms (Recommended)
1. Training failure rate > 10%
2. Training duration > 60 minutes
3. Counter stuck (no increment in 7 days)

## Troubleshooting

### Training fails with OOM
- Reduce batch size in `train_vlm.py` (line 168)
- Increase ECS task memory to 8GB

### Not enough training data
- Lower threshold to 30 corrections (in `training_counter.py` line 21)
- Or accumulate more corrections before enabling training

### Model not improving
- Check data quality (view corrections in DynamoDB)
- Increase training epochs
- Try different base model (e.g., `microsoft/trocr-base-printed`)

### S3 upload fails
- Check IAM permissions for training task role
- Verify S3 bucket exists and is accessible

## Future Enhancements

1. **A/B Testing**: Deploy new model to subset of traffic
2. **Model Versioning**: Track model performance over time
3. **Active Learning**: Prioritize low-confidence words for correction
4. **Distributed Training**: Multi-GPU for faster training
5. **Continuous Training**: Daily scheduled training instead of threshold-based

## References

- [TrOCR Paper](https://arxiv.org/abs/2109.10282)
- [Hugging Face TrOCR](https://huggingface.co/docs/transformers/model_doc/trocr)
- [AWS ECS Fargate](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html)
