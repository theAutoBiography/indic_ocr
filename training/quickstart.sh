#!/bin/bash

# QuickStart script for ViT-OCR training pipeline

set -e  # Exit on error

echo "=========================================="
echo "ViT-OCR Training Pipeline - QuickStart"
echo "=========================================="

# Step 1: Install dependencies
echo ""
echo "Step 1: Installing dependencies..."
pip install -r requirements.txt

# Step 2: Export training data
echo ""
echo "Step 2: Exporting training data..."
echo "This will download images from S3 and create train/val/test splits."
echo ""
read -p "Output directory [default: training_data]: " OUTPUT_DIR
OUTPUT_DIR=${OUTPUT_DIR:-training_data}

read -p "Minimum confidence [default: 80]: " MIN_CONF
MIN_CONF=${MIN_CONF:-80}

read -p "Languages (space-separated, e.g., 'san hin tam') [default: all]: " LANGUAGES

read -p "Max samples per script [default: no limit]: " MAX_PER_SCRIPT

# Build export command
EXPORT_CMD="python export_training_data.py --output-dir $OUTPUT_DIR --min-confidence $MIN_CONF"

if [ ! -z "$LANGUAGES" ]; then
    EXPORT_CMD="$EXPORT_CMD --languages $LANGUAGES"
fi

if [ ! -z "$MAX_PER_SCRIPT" ]; then
    EXPORT_CMD="$EXPORT_CMD --max-per-script $MAX_PER_SCRIPT"
fi

echo "Running: $EXPORT_CMD"
eval $EXPORT_CMD

# Check if export was successful
if [ ! -f "$OUTPUT_DIR/train.json" ]; then
    echo "Error: Data export failed. Please check your AWS credentials and try again."
    exit 1
fi

echo ""
echo "✅ Data export complete!"

# Step 3: Verify dataset
echo ""
echo "Step 3: Verifying dataset..."
python dataset.py --data-dir $OUTPUT_DIR

# Step 4: Choose model size
echo ""
echo "Step 4: Choose model size for training"
echo "  tiny  - Fast training, good for experiments (7M params)"
echo "  small - Balanced (27M params)"
echo "  base  - Best quality (101M params)"
echo "  large - Maximum quality, slow training (347M params)"
echo ""
read -p "Model size [default: tiny]: " MODEL_SIZE
MODEL_SIZE=${MODEL_SIZE:-tiny}

read -p "Batch size [default: 32]: " BATCH_SIZE
BATCH_SIZE=${BATCH_SIZE:-32}

read -p "Number of epochs [default: 50]: " EPOCHS
EPOCHS=${EPOCHS:-50}

read -p "Output directory for checkpoints [default: checkpoints_${MODEL_SIZE}]: " CHECKPOINT_DIR
CHECKPOINT_DIR=${CHECKPOINT_DIR:-checkpoints_${MODEL_SIZE}}

# Step 5: Start training
echo ""
echo "=========================================="
echo "Starting training with:"
echo "  Model: $MODEL_SIZE"
echo "  Batch size: $BATCH_SIZE"
echo "  Epochs: $EPOCHS"
echo "  Output: $CHECKPOINT_DIR"
echo "=========================================="
echo ""
read -p "Press Enter to start training, or Ctrl+C to cancel..."

python train.py \
    --data-dir $OUTPUT_DIR \
    --model-size $MODEL_SIZE \
    --batch-size $BATCH_SIZE \
    --epochs $EPOCHS \
    --output-dir $CHECKPOINT_DIR \
    --save-every 5 \
    --validate-every 1

echo ""
echo "=========================================="
echo "✅ Training complete!"
echo "=========================================="
echo ""
echo "Best model saved to: $CHECKPOINT_DIR/best_model.pth"
echo ""
echo "To monitor training, run:"
echo "  tensorboard --logdir $CHECKPOINT_DIR/logs"
echo ""
echo "To evaluate on test set, run:"
echo "  python evaluate.py --checkpoint $CHECKPOINT_DIR/best_model.pth --data-dir $OUTPUT_DIR --split test"
echo ""
echo "To run inference on an image, run:"
echo "  python inference.py --checkpoint $CHECKPOINT_DIR/best_model.pth --vocab $OUTPUT_DIR/vocabulary.json --image path/to/image.png"
echo ""
