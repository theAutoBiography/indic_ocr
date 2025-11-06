# Vision Transformer OCR Training Pipeline

Complete training pipeline for Vision Transformer-based OCR on Indic languages.

## Overview

This pipeline trains a ViT encoder + Transformer decoder model for OCR, using:
- **High-confidence Tesseract predictions** (confidence ≥ 80) as pseudo-labels
- **User-corrected text** as ground truth labels (highest quality)

## Architecture

```
Image (224×224×1) → ViT Encoder → Transformer Decoder → Text Sequence
                    (visual features)  (autoregressive)
```

### Model Sizes

| Model | Encoder Params | Decoder Params | Total Params | Training Time* |
|-------|---------------|----------------|--------------|----------------|
| Tiny  | ~5M           | ~2M            | ~7M          | 2-4 hours      |
| Small | ~22M          | ~5M            | ~27M         | 6-12 hours     |
| Base  | ~86M          | ~15M           | ~101M        | 1-2 days       |
| Large | ~307M         | ~40M           | ~347M        | 3-5 days       |

*Approximate time for 50k samples, 100 epochs on single A100 GPU

## Setup

### 1. Install Dependencies

```bash
cd training
pip install -r requirements.txt
```

### 2. Export Training Data

Export word images and labels from DynamoDB/S3:

```bash
python export_training_data.py \
  --output-dir training_data \
  --min-confidence 80 \
  --languages san hin \
  --max-per-script 10000
```

**Arguments:**
- `--output-dir`: Output directory for dataset
- `--min-confidence`: Minimum confidence for Tesseract predictions (default: 80)
- `--languages`: Languages to export (e.g., `san hin tam`), or omit for all
- `--no-corrected`: Exclude user-corrected samples
- `--no-high-confidence`: Exclude high-confidence Tesseract predictions
- `--max-per-script`: Maximum samples per script (for balancing)

**Output structure:**
```
training_data/
├── Devanagari/         # Images organized by script
│   ├── file1_page1_word0.png
│   ├── file1_page1_word1.png
│   └── ...
├── Tamil/
├── train.json          # Training split (80%)
├── val.json            # Validation split (10%)
├── test.json           # Test split (10%)
├── vocabulary.json     # Character vocabulary
└── dataset_stats.json  # Dataset statistics
```

### 3. Verify Dataset

```bash
python dataset.py --data-dir training_data
```

This will test data loading and show sample batches.

## Training

### Quick Start (Tiny Model)

For quick experimentation:

```bash
python train.py \
  --data-dir training_data \
  --model-size tiny \
  --batch-size 64 \
  --epochs 50 \
  --output-dir checkpoints_tiny
```

### Production Training (Base Model)

For best results:

```bash
python train.py \
  --data-dir training_data \
  --model-size base \
  --batch-size 32 \
  --epochs 100 \
  --lr 1e-4 \
  --weight-decay 0.01 \
  --warmup-epochs 5 \
  --label-smoothing 0.1 \
  --output-dir checkpoints_base \
  --save-every 5 \
  --validate-every 1
```

### Training Arguments

**Data:**
- `--data-dir`: Path to training data directory (required)
- `--batch-size`: Batch size (default: 32)
- `--num-workers`: Number of data loading workers (default: 4)

**Model:**
- `--model-size`: Model size: `tiny`, `small`, `base`, `large` (default: `base`)
- `--img-size`: Input image size (default: 224)
- `--max-seq-len`: Maximum sequence length (default: 50)

**Training:**
- `--epochs`: Number of epochs (default: 100)
- `--lr`: Learning rate (default: 1e-4)
- `--weight-decay`: Weight decay for AdamW (default: 0.01)
- `--warmup-epochs`: Linear warmup epochs (default: 5)
- `--label-smoothing`: Label smoothing factor (default: 0.1)

**Checkpoints:**
- `--output-dir`: Output directory for checkpoints (default: `checkpoints`)
- `--resume`: Resume training from checkpoint
- `--save-every`: Save checkpoint every N epochs (default: 5)
- `--validate-every`: Validate every N epochs (default: 1)

**Device:**
- `--device`: Device to use: `cuda` or `cpu` (default: auto-detect)

### Resume Training

```bash
python train.py \
  --data-dir training_data \
  --model-size base \
  --resume checkpoints_base/checkpoint_epoch_50.pth \
  --epochs 100
```

### Monitor Training

Use TensorBoard to monitor training:

```bash
tensorboard --logdir checkpoints_base/logs
```

Open http://localhost:6006 to view:
- Training/validation loss
- CER, WER, accuracy metrics
- Learning rate schedule

## Evaluation

### Evaluate on Test Set

```bash
python evaluate.py \
  --checkpoint checkpoints_base/best_model.pth \
  --data-dir training_data \
  --split test \
  --output results.json
```

**Output:**
```
==================================================
Evaluation Results
==================================================
CER: 5.23%
WER: 12.45%
Accuracy: 78.92%
==================================================

Sample predictions:
1. Target:    'संस्कृत'
   Predicted: 'संस्कृत'
   Match: ✅

2. Target:    'धर्म'
   Predicted: 'धर्म'
   Match: ✅
...
```

### Evaluate Per-Script

To evaluate performance on specific scripts, filter the test set:

```python
# Custom evaluation script
import json

# Load test data
with open('training_data/test.json') as f:
    test_data = json.load(f)

# Filter by script
devanagari_samples = [s for s in test_data if s['script'] == 'Devanagari']
print(f"Devanagari samples: {len(devanagari_samples)}")
```

## Inference

### Single Image

```bash
python inference.py \
  --checkpoint checkpoints_base/best_model.pth \
  --vocab training_data/vocabulary.json \
  --image path/to/word_image.png
```

**Output:**
```
Loading model...
✅ Model loaded from checkpoints_base/best_model.pth
   Epoch: 95
   CER: 5.23

Processing: path/to/word_image.png
Predicted text: संस्कृत
```

### Batch Inference

```bash
python inference.py \
  --checkpoint checkpoints_base/best_model.pth \
  --vocab training_data/vocabulary.json \
  --image-dir path/to/images/ \
  --output predictions.json
```

### Python API

```python
from inference import OCRInference

# Load model
ocr = OCRInference(
    checkpoint_path='checkpoints_base/best_model.pth',
    vocab_file='training_data/vocabulary.json',
    device='cuda'
)

# Predict single image
text = ocr.predict('word_image.png')
print(f"Predicted: {text}")

# Predict batch
texts = ocr.predict_batch(['img1.png', 'img2.png', 'img3.png'])
```

## Data Requirements

### Minimum Viable

For initial experiments:
- **5,000-10,000** samples per script
- Mix of high-confidence Tesseract + user corrections
- Expected CER: 15-25%

### Good Performance

For production-quality models:
- **50,000-100,000** samples per script
- At least 10% user-corrected samples
- Expected CER: 5-10%

### Excellent Performance

For state-of-the-art results:
- **500,000+** samples per script
- 20%+ user-corrected samples
- Diverse fonts, sizes, quality levels
- Expected CER: 2-5%

## Best Practices

### 1. Data Quality

**Prioritize user corrections:**
```bash
# Export with high priority on corrections
python export_training_data.py \
  --output-dir training_data \
  --min-confidence 90 \
  --max-per-script 50000
```

**Balance datasets:**
- Use `--max-per-script` to prevent script imbalance
- Ensure validation set is representative

### 2. Start Small

**Rapid iteration:**
1. Start with `tiny` model on 5k samples
2. Verify training pipeline works
3. Scale to `base` model with full dataset

### 3. Hyperparameter Tuning

**Learning rate:**
- Start: 1e-4 (default)
- If loss plateaus: reduce to 5e-5
- If loss diverges: reduce to 5e-5

**Batch size:**
- Larger is better (up to memory limits)
- Tiny: 64-128
- Base: 32-64
- Large: 16-32

**Epochs:**
- Monitor validation CER
- Stop if no improvement for 10-20 epochs
- Typical: 50-150 epochs

### 4. Data Augmentation

The dataset automatically applies:
- Random rotation (±3°)
- Random translation (±5%)
- Brightness/contrast jittering

To disable (not recommended):
```python
# In dataset.py
train_dataset = OCRDataset(..., augment=False)
```

### 5. Multi-GPU Training

For faster training with multiple GPUs:

```bash
# Coming soon: Distributed training support
```

## Integration with Your OCR Pipeline

### Hybrid Approach (Recommended)

Use ViT for low-confidence Tesseract predictions:

```python
from inference import OCRInference
import pytesseract

# Load ViT model
vit_ocr = OCRInference('checkpoints/best_model.pth', 'training_data/vocabulary.json')

def hybrid_ocr(image):
    # Use Tesseract first
    tesseract_result = pytesseract.image_to_data(image, output_type=Output.DICT)

    for i, word in enumerate(tesseract_result['text']):
        confidence = tesseract_result['conf'][i]

        # Use ViT for low-confidence words
        if confidence < 60:
            word_image = extract_word_image(image, tesseract_result, i)
            vit_prediction = vit_ocr.predict(word_image)
            tesseract_result['text'][i] = vit_prediction

    return tesseract_result
```

### Replace Tesseract

For full ViT-based OCR, modify `src/ocr_processor.py`:

```python
from training.inference import OCRInference

class OCRProcessor:
    def __init__(self):
        self.vit_ocr = OCRInference(
            'training/checkpoints/best_model.pth',
            'training/training_data/vocabulary.json'
        )

    def process_word(self, word_image):
        return self.vit_ocr.predict(word_image)
```

## Troubleshooting

### Out of Memory

**Reduce batch size:**
```bash
python train.py --batch-size 16  # Instead of 32
```

**Use smaller model:**
```bash
python train.py --model-size small  # Instead of base
```

**Reduce image size:**
```bash
python train.py --img-size 128  # Instead of 224
```

### Low Accuracy

**Check data quality:**
```bash
# Inspect samples
python dataset.py --data-dir training_data
```

**Increase training data:**
```bash
# Export more samples
python export_training_data.py --max-per-script 100000
```

**Train longer:**
```bash
python train.py --epochs 200  # Instead of 100
```

**Adjust learning rate:**
```bash
python train.py --lr 5e-5  # Lower learning rate
```

### Training Diverges

**Reduce learning rate:**
```bash
python train.py --lr 5e-5
```

**Increase warmup:**
```bash
python train.py --warmup-epochs 10
```

**Check data:**
- Ensure vocabulary is correct
- Verify labels are properly encoded
- Check for corrupted images

## Performance Benchmarks

Expected performance on 50k Devanagari samples (Base model, 100 epochs):

| Metric | Value |
|--------|-------|
| CER | 5-8% |
| WER | 12-18% |
| Exact Match | 75-85% |
| Training Time | ~24 hours (A100) |
| Inference Speed | ~50 images/sec (A100) |

## Next Steps

1. **Collect more data**: Use your correction UI to gather 50k+ samples
2. **Train per-script models**: Separate models for Devanagari, Tamil, etc.
3. **Fine-tune on specific domains**: Ancient texts, handwritten, etc.
4. **Experiment with architectures**: Try TrOCR, LayoutLM, etc.

## Resources

- [Vision Transformer Paper](https://arxiv.org/abs/2010.11929)
- [TrOCR Paper](https://arxiv.org/abs/2109.10282)
- [Attention Is All You Need](https://arxiv.org/abs/1706.03762)

## Support

For questions or issues, please open an issue in the main repository.
