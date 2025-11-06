"""
Evaluation metrics for OCR: CER, WER, and accuracy.
"""

import torch
import numpy as np
from tqdm import tqdm
import Levenshtein


def calculate_cer(predicted, target):
    """
    Calculate Character Error Rate.

    CER = (S + D + I) / N
    where S = substitutions, D = deletions, I = insertions, N = total characters
    """
    if len(target) == 0:
        return 0.0 if len(predicted) == 0 else 1.0

    distance = Levenshtein.distance(predicted, target)
    cer = distance / len(target)
    return cer


def calculate_wer(predicted, target):
    """
    Calculate Word Error Rate.

    WER = (S + D + I) / N
    where S = substitutions, D = deletions, I = insertions, N = total words
    """
    pred_words = predicted.split()
    target_words = target.split()

    if len(target_words) == 0:
        return 0.0 if len(pred_words) == 0 else 1.0

    distance = Levenshtein.distance(' '.join(pred_words), ' '.join(target_words))
    wer = distance / len(target_words)
    return wer


def calculate_exact_match_accuracy(predicted, target):
    """
    Calculate exact match accuracy (1 if exact match, 0 otherwise).
    """
    return 1.0 if predicted == target else 0.0


def calculate_metrics(predictions, targets, dataset):
    """
    Calculate CER, WER, and accuracy for a batch of predictions.

    Args:
        predictions: List or array of predicted token indices [batch_size, seq_len]
        targets: List or array of target token indices [batch_size, seq_len]
        dataset: Dataset object with decode_text method

    Returns:
        dict: {'cer': float, 'wer': float, 'accuracy': float}
    """
    total_cer = 0.0
    total_wer = 0.0
    total_accuracy = 0.0
    num_samples = len(predictions)

    for pred, tgt in zip(predictions, targets):
        # Decode to text
        pred_text = dataset.decode_text(pred)
        tgt_text = dataset.decode_text(tgt)

        # Calculate metrics
        total_cer += calculate_cer(pred_text, tgt_text)
        total_wer += calculate_wer(pred_text, tgt_text)
        total_accuracy += calculate_exact_match_accuracy(pred_text, tgt_text)

    # Average metrics
    avg_cer = (total_cer / num_samples) * 100  # Convert to percentage
    avg_wer = (total_wer / num_samples) * 100
    avg_accuracy = (total_accuracy / num_samples) * 100

    return {
        'cer': avg_cer,
        'wer': avg_wer,
        'accuracy': avg_accuracy,
    }


def evaluate_model(model, dataloader, device, dataset):
    """
    Evaluate model on a dataset.

    Args:
        model: ViTOCR model
        dataloader: DataLoader for evaluation
        device: Device to use
        dataset: Dataset object with decode_text method

    Returns:
        dict: Evaluation metrics
    """
    model.eval()

    all_predictions = []
    all_targets = []
    all_pred_texts = []
    all_target_texts = []

    # Get special token indices
    sos_idx = dataset.char_to_idx['<SOS>']
    eos_idx = dataset.char_to_idx['<EOS>']

    with torch.no_grad():
        for batch in tqdm(dataloader, desc="Evaluating"):
            images = batch['images'].to(device)
            labels = batch['labels']

            # Generate predictions
            predictions = model.generate(images, sos_idx, eos_idx)

            all_predictions.extend(predictions.cpu().numpy())
            all_targets.extend(labels.numpy())

            # Decode for detailed analysis
            for pred, tgt in zip(predictions.cpu().numpy(), labels.numpy()):
                pred_text = dataset.decode_text(pred)
                tgt_text = dataset.decode_text(tgt)
                all_pred_texts.append(pred_text)
                all_target_texts.append(tgt_text)

    # Calculate overall metrics
    metrics = calculate_metrics(all_predictions, all_targets, dataset)

    # Add sample predictions for inspection
    metrics['samples'] = []
    for i in range(min(10, len(all_pred_texts))):
        metrics['samples'].append({
            'target': all_target_texts[i],
            'predicted': all_pred_texts[i],
            'match': all_target_texts[i] == all_pred_texts[i]
        })

    return metrics


if __name__ == '__main__':
    import argparse
    import json
    from pathlib import Path

    from model import create_model
    from dataset import create_dataloaders

    parser = argparse.ArgumentParser(description='Evaluate ViT-OCR model')
    parser.add_argument('--checkpoint', required=True, help='Path to model checkpoint')
    parser.add_argument('--data-dir', required=True, help='Path to data directory')
    parser.add_argument('--split', default='test', choices=['train', 'val', 'test'],
                       help='Dataset split to evaluate')
    parser.add_argument('--batch-size', type=int, default=32, help='Batch size')
    parser.add_argument('--device', default='cuda' if torch.cuda.is_available() else 'cpu',
                       help='Device to use')
    parser.add_argument('--output', help='Output file for results (JSON)')

    args = parser.parse_args()

    print("Loading data...")
    dataloaders = create_dataloaders(
        data_dir=args.data_dir,
        batch_size=args.batch_size,
        num_workers=0,  # Single-threaded for evaluation
    )

    print("Loading model...")
    # Create model (architecture should match checkpoint)
    model = create_model(
        vocab_size=dataloaders['vocab_size'],
        model_size='base',  # Adjust if needed
    )

    # Load checkpoint
    checkpoint = torch.load(args.checkpoint, map_location=args.device)
    model.load_state_dict(checkpoint['model_state_dict'])
    model = model.to(args.device)

    print(f"Loaded checkpoint from epoch {checkpoint['epoch']}")

    # Evaluate
    print(f"\nEvaluating on {args.split} set...")
    dataloader = dataloaders[args.split]
    dataset = dataloader.dataset

    metrics = evaluate_model(model, dataloader, args.device, dataset)

    # Print results
    print("\n" + "=" * 50)
    print("Evaluation Results")
    print("=" * 50)
    print(f"CER: {metrics['cer']:.2f}%")
    print(f"WER: {metrics['wer']:.2f}%")
    print(f"Accuracy: {metrics['accuracy']:.2f}%")
    print("=" * 50)

    print("\nSample predictions:")
    for i, sample in enumerate(metrics['samples'], 1):
        print(f"\n{i}. Target:    '{sample['target']}'")
        print(f"   Predicted: '{sample['predicted']}'")
        print(f"   Match: {'✅' if sample['match'] else '❌'}")

    # Save results if output file specified
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(exist_ok=True, parents=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)

        print(f"\n✅ Results saved to: {output_path}")
