"""
PyTorch Dataset and DataLoader for ViT OCR training.
"""

import json
import torch
from torch.utils.data import Dataset, DataLoader
from PIL import Image
import torchvision.transforms as transforms
from pathlib import Path
import numpy as np


class OCRDataset(Dataset):
    """Dataset for OCR word images with text labels."""

    def __init__(self,
                 json_file,
                 vocab_file,
                 image_size=(224, 224),
                 max_label_length=50,
                 augment=False):
        """
        Args:
            json_file: Path to JSON file (train.json, val.json, test.json)
            vocab_file: Path to vocabulary JSON file
            image_size: Target image size (height, width)
            max_label_length: Maximum length of text labels (for padding)
            augment: Whether to apply data augmentation
        """
        with open(json_file, 'r', encoding='utf-8') as f:
            self.samples = json.load(f)

        with open(vocab_file, 'r', encoding='utf-8') as f:
            vocab_data = json.load(f)
            self.char_to_idx = vocab_data['char_to_idx']
            self.idx_to_char = {int(k): v for k, v in vocab_data['idx_to_char'].items()}
            self.vocab_size = vocab_data['vocab_size']

        self.image_size = image_size
        self.max_label_length = max_label_length
        self.augment = augment

        # Special token indices
        self.pad_idx = self.char_to_idx['<PAD>']
        self.sos_idx = self.char_to_idx['<SOS>']
        self.eos_idx = self.char_to_idx['<EOS>']
        self.unk_idx = self.char_to_idx['<UNK>']

        # Image transforms
        self.base_transform = transforms.Compose([
            transforms.Resize(image_size),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.5], std=[0.5])  # Normalize grayscale to [-1, 1]
        ])

        # Augmentation transforms (only for training)
        self.augment_transform = transforms.Compose([
            transforms.Resize(image_size),
            transforms.RandomRotation(degrees=3),  # Slight rotation
            transforms.RandomAffine(degrees=0, translate=(0.05, 0.05)),  # Slight shift
            transforms.ColorJitter(brightness=0.2, contrast=0.2),  # Brightness/contrast
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.5], std=[0.5])
        ])

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        sample = self.samples[idx]

        # Load image
        img_path = sample['image_path']
        image = Image.open(img_path).convert('L')  # Convert to grayscale

        # Apply transforms
        if self.augment:
            image = self.augment_transform(image)
        else:
            image = self.base_transform(image)

        # Encode label
        label = sample['label']
        encoded_label = self.encode_text(label)

        return {
            'image': image,
            'label': encoded_label,
            'label_length': len(label),
            'label_text': label,
            'script': sample['script'],
            'confidence': sample['confidence'],
        }

    def encode_text(self, text):
        """
        Encode text to indices with padding.

        Returns:
            torch.Tensor of shape [max_label_length] with character indices
        """
        # Convert characters to indices
        indices = [self.sos_idx]  # Start token
        for char in text:
            indices.append(self.char_to_idx.get(char, self.unk_idx))
        indices.append(self.eos_idx)  # End token

        # Pad to max length
        if len(indices) < self.max_label_length:
            indices += [self.pad_idx] * (self.max_label_length - len(indices))
        else:
            indices = indices[:self.max_label_length]  # Truncate if too long

        return torch.tensor(indices, dtype=torch.long)

    def decode_text(self, indices):
        """
        Decode indices back to text.

        Args:
            indices: List or tensor of character indices

        Returns:
            str: Decoded text
        """
        if isinstance(indices, torch.Tensor):
            indices = indices.cpu().numpy()

        chars = []
        for idx in indices:
            if idx == self.eos_idx:
                break  # Stop at end token
            if idx in [self.pad_idx, self.sos_idx]:
                continue  # Skip padding and start tokens
            chars.append(self.idx_to_char.get(int(idx), '<UNK>'))

        return ''.join(chars)


def collate_fn(batch):
    """
    Custom collate function for DataLoader.
    """
    images = torch.stack([item['image'] for item in batch])
    labels = torch.stack([item['label'] for item in batch])
    label_lengths = torch.tensor([item['label_length'] for item in batch])
    label_texts = [item['label_text'] for item in batch]
    scripts = [item['script'] for item in batch]
    confidences = torch.tensor([item['confidence'] for item in batch])

    return {
        'images': images,
        'labels': labels,
        'label_lengths': label_lengths,
        'label_texts': label_texts,
        'scripts': scripts,
        'confidences': confidences,
    }


def create_dataloaders(data_dir,
                      batch_size=32,
                      num_workers=4,
                      image_size=(224, 224),
                      max_label_length=50):
    """
    Create train, validation, and test dataloaders.

    Args:
        data_dir: Directory containing train.json, val.json, test.json, vocabulary.json
        batch_size: Batch size for training
        num_workers: Number of workers for data loading
        image_size: Target image size (height, width)
        max_label_length: Maximum label length

    Returns:
        dict: {'train': DataLoader, 'val': DataLoader, 'test': DataLoader, 'vocab_size': int}
    """
    data_dir = Path(data_dir)

    # Check if files exist
    required_files = ['train.json', 'val.json', 'test.json', 'vocabulary.json']
    for file in required_files:
        if not (data_dir / file).exists():
            raise FileNotFoundError(f"Missing required file: {data_dir / file}")

    vocab_file = data_dir / 'vocabulary.json'

    # Create datasets
    train_dataset = OCRDataset(
        json_file=data_dir / 'train.json',
        vocab_file=vocab_file,
        image_size=image_size,
        max_label_length=max_label_length,
        augment=True  # Enable augmentation for training
    )

    val_dataset = OCRDataset(
        json_file=data_dir / 'val.json',
        vocab_file=vocab_file,
        image_size=image_size,
        max_label_length=max_label_length,
        augment=False
    )

    test_dataset = OCRDataset(
        json_file=data_dir / 'test.json',
        vocab_file=vocab_file,
        image_size=image_size,
        max_label_length=max_label_length,
        augment=False
    )

    # Create dataloaders
    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        collate_fn=collate_fn,
        pin_memory=True
    )

    val_loader = DataLoader(
        val_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        collate_fn=collate_fn,
        pin_memory=True
    )

    test_loader = DataLoader(
        test_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        collate_fn=collate_fn,
        pin_memory=True
    )

    return {
        'train': train_loader,
        'val': val_loader,
        'test': test_loader,
        'vocab_size': train_dataset.vocab_size,
        'char_to_idx': train_dataset.char_to_idx,
        'idx_to_char': train_dataset.idx_to_char,
    }


# Test code
if __name__ == '__main__':
    # Test dataset loading
    import sys
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', default='training_data', help='Data directory')
    args = parser.parse_args()

    print("Testing dataset loading...")

    try:
        dataloaders = create_dataloaders(
            data_dir=args.data_dir,
            batch_size=4,
            num_workers=0
        )

        print(f"✅ Dataloaders created successfully!")
        print(f"Vocabulary size: {dataloaders['vocab_size']}")
        print(f"Train batches: {len(dataloaders['train'])}")
        print(f"Val batches: {len(dataloaders['val'])}")
        print(f"Test batches: {len(dataloaders['test'])}")

        # Test one batch
        batch = next(iter(dataloaders['train']))
        print(f"\nSample batch:")
        print(f"  Images shape: {batch['images'].shape}")
        print(f"  Labels shape: {batch['labels'].shape}")
        print(f"  Label texts: {batch['label_texts'][:3]}")
        print(f"  Scripts: {batch['scripts'][:3]}")

        # Test decoding
        dataset = dataloaders['train'].dataset
        decoded = dataset.decode_text(batch['labels'][0])
        print(f"\nDecoded first label: '{decoded}'")
        print(f"Original text: '{batch['label_texts'][0]}'")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
