"""
Export training data from DynamoDB and S3 for ViT training.

This script exports:
1. High-confidence Tesseract predictions (confidence >= 80) as pseudo-labels
2. User-corrected words as ground truth labels
3. Downloads word images from S3
"""

import os
import sys
import json
import boto3
import argparse
from pathlib import Path
from tqdm import tqdm
from collections import defaultdict
import io
from PIL import Image

# Add parent directory to path to import src modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Config


class TrainingDataExporter:
    def __init__(self, output_dir='training_data'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True, parents=True)

        # Initialize AWS clients
        self.dynamodb = boto3.resource(
            'dynamodb',
            region_name=Config.AWS_REGION,
            aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY
        )
        self.s3 = boto3.client(
            's3',
            region_name=Config.AWS_REGION,
            aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY
        )
        self.table = self.dynamodb.Table(Config.DYNAMODB_TABLE)

    def export_data(self,
                   min_confidence=80,
                   languages=None,
                   include_corrected=True,
                   include_high_confidence=True,
                   max_samples_per_script=None):
        """
        Export training data based on criteria.

        Args:
            min_confidence: Minimum confidence for Tesseract predictions (default: 80)
            languages: List of languages to export (e.g., ['san', 'hin']). None = all
            include_corrected: Include user-corrected words (highest quality)
            include_high_confidence: Include high-confidence Tesseract predictions
            max_samples_per_script: Maximum samples per script (for balancing)
        """
        print(f"Exporting training data...")
        print(f"- Min confidence: {min_confidence}")
        print(f"- Include corrected: {include_corrected}")
        print(f"- Include high-confidence: {include_high_confidence}")

        samples = []
        stats = defaultdict(int)

        # Scan DynamoDB table
        print("\nScanning DynamoDB table...")
        scan_kwargs = {}

        while True:
            response = self.table.scan(**scan_kwargs)
            items = response.get('Items', [])

            for item in items:
                # Extract metadata
                confidence = float(item.get('confidence', 0))
                detected_script = item.get('detected_script', 'Unknown')
                language = item.get('language', '')
                is_corrected = item.get('is_corrected') == 'true'

                # Filter by language if specified
                if languages:
                    if not any(lang in language for lang in languages):
                        continue

                # Determine label and whether to include
                label = None
                source = None

                if is_corrected and include_corrected:
                    # User-corrected words (highest priority)
                    label = item.get('corrected_text', '').strip()
                    source = 'corrected'
                    stats[f'{detected_script}_corrected'] += 1
                elif confidence >= min_confidence and include_high_confidence:
                    # High-confidence Tesseract predictions (pseudo-labels)
                    label = item.get('original_text', '').strip()
                    source = 'high_confidence'
                    stats[f'{detected_script}_high_confidence'] += 1

                # Skip if no valid label
                if not label or len(label.strip()) == 0:
                    continue

                # Get S3 image key
                image_key = item.get('word_image_s3_key')
                if not image_key:
                    stats['missing_image'] += 1
                    continue

                samples.append({
                    'image_key': image_key,
                    'label': label,
                    'confidence': confidence,
                    'script': detected_script,
                    'language': language,
                    'source': source,
                    'file_id': item.get('file_id'),
                    'page': item.get('page'),
                    'word_index': item.get('word_index'),
                })

            # Check if more pages to scan
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']

        print(f"\nTotal samples found: {len(samples)}")
        print("\nBreakdown by script and source:")
        for key, count in sorted(stats.items()):
            print(f"  {key}: {count}")

        # Balance samples per script if requested
        if max_samples_per_script:
            samples = self._balance_samples(samples, max_samples_per_script)
            print(f"\nAfter balancing (max {max_samples_per_script} per script): {len(samples)}")

        # Download images and create dataset
        print("\nDownloading images from S3...")
        dataset = self._download_images(samples)

        # Save dataset metadata
        self._save_dataset(dataset)

        return dataset

    def _balance_samples(self, samples, max_per_script):
        """Balance samples per script to avoid class imbalance."""
        script_samples = defaultdict(list)
        for sample in samples:
            script_samples[sample['script']].append(sample)

        balanced = []
        for script, script_samples_list in script_samples.items():
            # Prioritize corrected samples
            corrected = [s for s in script_samples_list if s['source'] == 'corrected']
            high_conf = [s for s in script_samples_list if s['source'] == 'high_confidence']

            # Take up to max_per_script, prioritizing corrections
            balanced.extend(corrected[:max_per_script])
            remaining = max_per_script - len(corrected[:max_per_script])
            if remaining > 0:
                balanced.extend(high_conf[:remaining])

        return balanced

    def _download_images(self, samples):
        """Download images from S3 and save locally."""
        dataset = []

        # Create directories for each script
        script_dirs = {}

        for sample in tqdm(samples, desc="Downloading images"):
            script = sample['script']

            # Create script directory if not exists
            if script not in script_dirs:
                script_dir = self.output_dir / script
                script_dir.mkdir(exist_ok=True)
                script_dirs[script] = script_dir

            # Generate local filename
            filename = f"{sample['file_id']}_{sample['page']}_{sample['word_index']}.png"
            local_path = script_dirs[script] / filename

            # Download from S3
            try:
                response = self.s3.get_object(
                    Bucket=Config.S3_WORD_BUCKET,
                    Key=sample['image_key']
                )

                # Read image data
                img_data = response['Body'].read()

                # Convert to grayscale for OCR (optional but recommended)
                img = Image.open(io.BytesIO(img_data))
                if img.mode != 'L':
                    img = img.convert('L')  # Convert to grayscale

                # Save locally
                img.save(local_path)

                dataset.append({
                    'image_path': str(local_path),
                    'label': sample['label'],
                    'confidence': sample['confidence'],
                    'script': sample['script'],
                    'source': sample['source'],
                })

            except Exception as e:
                print(f"\nError downloading {sample['image_key']}: {e}")
                continue

        return dataset

    def _save_dataset(self, dataset):
        """Save dataset metadata to JSON files."""
        # Split into train/val/test (80/10/10)
        total = len(dataset)
        train_size = int(0.8 * total)
        val_size = int(0.1 * total)

        # Shuffle
        import random
        random.seed(42)
        random.shuffle(dataset)

        train_data = dataset[:train_size]
        val_data = dataset[train_size:train_size + val_size]
        test_data = dataset[train_size + val_size:]

        # Save splits
        splits = {
            'train': train_data,
            'val': val_data,
            'test': test_data
        }

        for split_name, split_data in splits.items():
            output_file = self.output_dir / f'{split_name}.json'
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(split_data, f, ensure_ascii=False, indent=2)
            print(f"\n{split_name.capitalize()} set: {len(split_data)} samples")
            print(f"  Saved to: {output_file}")

        # Save vocabulary (all unique characters across all scripts)
        vocab = self._create_vocabulary(dataset)
        vocab_file = self.output_dir / 'vocabulary.json'
        with open(vocab_file, 'w', encoding='utf-8') as f:
            json.dump(vocab, f, ensure_ascii=False, indent=2)
        print(f"\nVocabulary saved to: {vocab_file}")
        print(f"  Total unique characters: {len(vocab['char_to_idx'])}")

        # Save per-script statistics
        script_stats = defaultdict(lambda: {'count': 0, 'corrected': 0, 'high_confidence': 0})
        for sample in dataset:
            script = sample['script']
            script_stats[script]['count'] += 1
            if sample['source'] == 'corrected':
                script_stats[script]['corrected'] += 1
            else:
                script_stats[script]['high_confidence'] += 1

        stats_file = self.output_dir / 'dataset_stats.json'
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(dict(script_stats), f, ensure_ascii=False, indent=2)
        print(f"\nDataset statistics saved to: {stats_file}")

    def _create_vocabulary(self, dataset):
        """Create character-level vocabulary from all labels."""
        chars = set()
        for sample in dataset:
            chars.update(sample['label'])

        # Sort for consistent ordering
        chars = sorted(list(chars))

        # Add special tokens
        special_tokens = ['<PAD>', '<SOS>', '<EOS>', '<UNK>']
        all_chars = special_tokens + chars

        char_to_idx = {char: idx for idx, char in enumerate(all_chars)}
        idx_to_char = {idx: char for char, idx in char_to_idx.items()}

        return {
            'char_to_idx': char_to_idx,
            'idx_to_char': idx_to_char,
            'vocab_size': len(char_to_idx),
            'special_tokens': special_tokens
        }


def main():
    parser = argparse.ArgumentParser(description='Export training data for ViT OCR model')
    parser.add_argument('--output-dir', default='training_data', help='Output directory')
    parser.add_argument('--min-confidence', type=int, default=80,
                       help='Minimum confidence for high-confidence samples')
    parser.add_argument('--languages', nargs='+',
                       help='Languages to export (e.g., san hin tam)')
    parser.add_argument('--no-corrected', action='store_true',
                       help='Exclude user-corrected samples')
    parser.add_argument('--no-high-confidence', action='store_true',
                       help='Exclude high-confidence Tesseract predictions')
    parser.add_argument('--max-per-script', type=int,
                       help='Maximum samples per script (for balancing)')

    args = parser.parse_args()

    exporter = TrainingDataExporter(output_dir=args.output_dir)

    dataset = exporter.export_data(
        min_confidence=args.min_confidence,
        languages=args.languages,
        include_corrected=not args.no_corrected,
        include_high_confidence=not args.no_high_confidence,
        max_samples_per_script=args.max_per_script
    )

    print(f"\n✅ Export complete! Dataset saved to: {args.output_dir}")
    print(f"Total samples: {len(dataset)}")


if __name__ == '__main__':
    main()
