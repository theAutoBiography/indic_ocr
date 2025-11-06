"""
Inference script for trained ViT-OCR model.
"""

import torch
from PIL import Image
import torchvision.transforms as transforms
import json
import argparse
from pathlib import Path
import sys

from model import create_model


class OCRInference:
    """Inference wrapper for ViT-OCR model."""

    def __init__(self, checkpoint_path, vocab_file, device='cuda', model_size='base'):
        self.device = device

        # Load vocabulary
        with open(vocab_file, 'r', encoding='utf-8') as f:
            vocab_data = json.load(f)
            self.char_to_idx = vocab_data['char_to_idx']
            self.idx_to_char = {int(k): v for k, v in vocab_data['idx_to_char'].items()}
            self.vocab_size = vocab_data['vocab_size']

        # Special tokens
        self.pad_idx = self.char_to_idx['<PAD>']
        self.sos_idx = self.char_to_idx['<SOS>']
        self.eos_idx = self.char_to_idx['<EOS>']
        self.unk_idx = self.char_to_idx['<UNK>']

        # Create model
        self.model = create_model(
            vocab_size=self.vocab_size,
            model_size=model_size
        )

        # Load checkpoint
        checkpoint = torch.load(checkpoint_path, map_location=device)
        self.model.load_state_dict(checkpoint['model_state_dict'])
        self.model = self.model.to(device)
        self.model.eval()

        print(f"✅ Model loaded from {checkpoint_path}")
        print(f"   Epoch: {checkpoint['epoch']}")
        if 'metrics' in checkpoint:
            print(f"   CER: {checkpoint['metrics'].get('cer', 'N/A')}")

        # Image preprocessing
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.5], std=[0.5])
        ])

    def preprocess_image(self, image_path):
        """
        Load and preprocess image.

        Args:
            image_path: Path to image file

        Returns:
            torch.Tensor: Preprocessed image [1, 1, 224, 224]
        """
        # Load image
        image = Image.open(image_path).convert('L')  # Convert to grayscale

        # Apply transforms
        image = self.transform(image)

        # Add batch dimension
        image = image.unsqueeze(0)

        return image

    def decode_text(self, indices):
        """
        Decode token indices to text.

        Args:
            indices: Tensor or list of token indices

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
                continue  # Skip special tokens
            chars.append(self.idx_to_char.get(int(idx), '<UNK>'))

        return ''.join(chars)

    @torch.no_grad()
    def predict(self, image_path, return_confidence=False):
        """
        Predict text from image.

        Args:
            image_path: Path to image file
            return_confidence: If True, return confidence scores

        Returns:
            str: Predicted text
            or tuple: (text, confidence) if return_confidence=True
        """
        # Preprocess image
        image = self.preprocess_image(image_path).to(self.device)

        # Generate prediction
        predictions = self.model.generate(
            image,
            sos_idx=self.sos_idx,
            eos_idx=self.eos_idx
        )

        # Decode to text
        text = self.decode_text(predictions[0])

        if return_confidence:
            # Calculate average confidence (simplified)
            # In production, you'd want to use the actual logits
            confidence = 0.95  # Placeholder
            return text, confidence

        return text

    @torch.no_grad()
    def predict_batch(self, image_paths):
        """
        Predict text from multiple images.

        Args:
            image_paths: List of image file paths

        Returns:
            list: List of predicted texts
        """
        predictions = []

        for image_path in image_paths:
            text = self.predict(image_path)
            predictions.append(text)

        return predictions


def main():
    parser = argparse.ArgumentParser(description='Run inference with trained ViT-OCR model')
    parser.add_argument('--checkpoint', required=True, help='Path to model checkpoint')
    parser.add_argument('--vocab', required=True, help='Path to vocabulary.json')
    parser.add_argument('--image', help='Path to single image')
    parser.add_argument('--image-dir', help='Path to directory of images')
    parser.add_argument('--model-size', default='base',
                       choices=['tiny', 'small', 'base', 'large'],
                       help='Model size (must match checkpoint)')
    parser.add_argument('--device', default='cuda' if torch.cuda.is_available() else 'cpu',
                       help='Device to use')
    parser.add_argument('--output', help='Output file for results (JSON)')

    args = parser.parse_args()

    # Validate inputs
    if not args.image and not args.image_dir:
        print("Error: Must provide either --image or --image-dir")
        sys.exit(1)

    # Create inference object
    print("Loading model...")
    ocr = OCRInference(
        checkpoint_path=args.checkpoint,
        vocab_file=args.vocab,
        device=args.device,
        model_size=args.model_size
    )

    # Run inference
    results = []

    if args.image:
        # Single image
        print(f"\nProcessing: {args.image}")
        text = ocr.predict(args.image)
        print(f"Predicted text: {text}")

        results.append({
            'image': str(args.image),
            'text': text
        })

    elif args.image_dir:
        # Directory of images
        image_dir = Path(args.image_dir)
        image_files = []

        # Find all image files
        for ext in ['*.png', '*.jpg', '*.jpeg', '*.bmp', '*.tiff']:
            image_files.extend(image_dir.glob(ext))

        print(f"\nFound {len(image_files)} images in {image_dir}")

        # Process each image
        for image_path in image_files:
            print(f"Processing: {image_path.name}")
            text = ocr.predict(image_path)
            print(f"  Predicted: {text}")

            results.append({
                'image': str(image_path),
                'text': text
            })

    # Save results if output file specified
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(exist_ok=True, parents=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print(f"\n✅ Results saved to: {output_path}")

    print("\n✅ Inference complete!")


if __name__ == '__main__':
    main()
