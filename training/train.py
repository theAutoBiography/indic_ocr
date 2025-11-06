"""
Training script for ViT-OCR model.
"""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.tensorboard import SummaryWriter
import argparse
import json
from pathlib import Path
from tqdm import tqdm
import os

from model import create_model
from dataset import create_dataloaders
from evaluate import calculate_metrics


class LabelSmoothingCrossEntropy(nn.Module):
    """
    Cross entropy loss with label smoothing.
    Helps prevent overconfidence in predictions.
    """

    def __init__(self, smoothing=0.1, ignore_index=-100):
        super().__init__()
        self.smoothing = smoothing
        self.ignore_index = ignore_index

    def forward(self, pred, target):
        """
        Args:
            pred: [batch_size, seq_len, vocab_size] - logits
            target: [batch_size, seq_len] - target indices
        """
        pred = pred.reshape(-1, pred.size(-1))  # [B * seq_len, vocab_size]
        target = target.reshape(-1)  # [B * seq_len]

        # Mask padding tokens
        mask = target != self.ignore_index
        pred = pred[mask]
        target = target[mask]

        n_classes = pred.size(-1)
        log_probs = nn.functional.log_softmax(pred, dim=-1)

        # One-hot encode targets with smoothing
        with torch.no_grad():
            true_dist = torch.zeros_like(log_probs)
            true_dist.fill_(self.smoothing / (n_classes - 1))
            true_dist.scatter_(1, target.unsqueeze(1), 1.0 - self.smoothing)

        return torch.mean(torch.sum(-true_dist * log_probs, dim=-1))


class Trainer:
    """Trainer for ViT-OCR model."""

    def __init__(self,
                 model,
                 dataloaders,
                 device,
                 learning_rate=1e-4,
                 weight_decay=0.01,
                 warmup_epochs=5,
                 label_smoothing=0.1,
                 output_dir='checkpoints',
                 pad_idx=0):
        self.model = model.to(device)
        self.dataloaders = dataloaders
        self.device = device
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True, parents=True)
        self.pad_idx = pad_idx

        # Loss function
        self.criterion = LabelSmoothingCrossEntropy(
            smoothing=label_smoothing,
            ignore_index=pad_idx
        )

        # Optimizer (AdamW with weight decay)
        self.optimizer = optim.AdamW(
            model.parameters(),
            lr=learning_rate,
            weight_decay=weight_decay,
            betas=(0.9, 0.999)
        )

        # Learning rate scheduler (cosine with warmup)
        self.warmup_epochs = warmup_epochs
        self.scheduler = optim.lr_scheduler.CosineAnnealingLR(
            self.optimizer,
            T_max=100,  # Will be updated based on total epochs
            eta_min=1e-6
        )

        # TensorBoard
        self.writer = SummaryWriter(log_dir=self.output_dir / 'logs')

        # Tracking
        self.epoch = 0
        self.best_val_loss = float('inf')
        self.best_cer = float('inf')

    def train_epoch(self):
        """Train for one epoch."""
        self.model.train()
        total_loss = 0
        num_batches = 0

        pbar = tqdm(self.dataloaders['train'], desc=f"Epoch {self.epoch}")

        for batch in pbar:
            images = batch['images'].to(self.device)
            labels = batch['labels'].to(self.device)

            # Forward pass
            logits = self.model(images, labels)

            # Calculate loss
            # Target is shifted by 1 (predict next token)
            target = labels[:, 1:]  # Remove SOS token
            loss = self.criterion(logits, target)

            # Backward pass
            self.optimizer.zero_grad()
            loss.backward()

            # Gradient clipping
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)

            self.optimizer.step()

            # Update metrics
            total_loss += loss.item()
            num_batches += 1

            # Update progress bar
            pbar.set_postfix({'loss': f'{loss.item():.4f}'})

        avg_loss = total_loss / num_batches
        return avg_loss

    @torch.no_grad()
    def validate(self):
        """Validate on validation set."""
        self.model.eval()
        total_loss = 0
        num_batches = 0

        all_predictions = []
        all_targets = []

        for batch in tqdm(self.dataloaders['val'], desc="Validating"):
            images = batch['images'].to(self.device)
            labels = batch['labels'].to(self.device)

            # Forward pass
            logits = self.model(images, labels)

            # Calculate loss
            target = labels[:, 1:]
            loss = self.criterion(logits, target)

            total_loss += loss.item()
            num_batches += 1

            # Generate predictions for metrics
            sos_idx = self.dataloaders['char_to_idx']['<SOS>']
            eos_idx = self.dataloaders['char_to_idx']['<EOS>']
            predictions = self.model.generate(images, sos_idx, eos_idx)

            all_predictions.extend(predictions.cpu().numpy())
            all_targets.extend(labels.cpu().numpy())

        avg_loss = total_loss / num_batches

        # Calculate metrics (CER, WER, accuracy)
        dataset = self.dataloaders['val'].dataset
        metrics = calculate_metrics(all_predictions, all_targets, dataset)

        return avg_loss, metrics

    def train(self, num_epochs, save_every=5, validate_every=1):
        """
        Full training loop.

        Args:
            num_epochs: Number of epochs to train
            save_every: Save checkpoint every N epochs
            validate_every: Validate every N epochs
        """
        print(f"Starting training for {num_epochs} epochs...")
        print(f"Device: {self.device}")
        print(f"Model parameters: {sum(p.numel() for p in self.model.parameters()):,}")
        print(f"Output directory: {self.output_dir}")

        # Update scheduler max iterations
        self.scheduler.T_max = num_epochs

        for epoch in range(num_epochs):
            self.epoch = epoch + 1

            # Apply warmup learning rate
            if epoch < self.warmup_epochs:
                warmup_lr = (epoch + 1) / self.warmup_epochs * self.optimizer.param_groups[0]['lr']
                for param_group in self.optimizer.param_groups:
                    param_group['lr'] = warmup_lr

            # Train
            train_loss = self.train_epoch()

            # Log training loss
            self.writer.add_scalar('Loss/train', train_loss, self.epoch)
            self.writer.add_scalar('Learning_rate', self.optimizer.param_groups[0]['lr'], self.epoch)

            print(f"\nEpoch {self.epoch}/{num_epochs}")
            print(f"  Train Loss: {train_loss:.4f}")
            print(f"  Learning Rate: {self.optimizer.param_groups[0]['lr']:.6f}")

            # Validate
            if self.epoch % validate_every == 0:
                val_loss, metrics = self.validate()

                # Log validation metrics
                self.writer.add_scalar('Loss/val', val_loss, self.epoch)
                self.writer.add_scalar('Metrics/CER', metrics['cer'], self.epoch)
                self.writer.add_scalar('Metrics/WER', metrics['wer'], self.epoch)
                self.writer.add_scalar('Metrics/Accuracy', metrics['accuracy'], self.epoch)

                print(f"  Val Loss: {val_loss:.4f}")
                print(f"  CER: {metrics['cer']:.2f}%")
                print(f"  WER: {metrics['wer']:.2f}%")
                print(f"  Accuracy: {metrics['accuracy']:.2f}%")

                # Save best model based on CER
                if metrics['cer'] < self.best_cer:
                    self.best_cer = metrics['cer']
                    self.save_checkpoint('best_model.pth', metrics)
                    print(f"  ✅ New best CER! Saved checkpoint.")

                if val_loss < self.best_val_loss:
                    self.best_val_loss = val_loss

            # Save periodic checkpoint
            if self.epoch % save_every == 0:
                self.save_checkpoint(f'checkpoint_epoch_{self.epoch}.pth')

            # Update learning rate (after warmup)
            if epoch >= self.warmup_epochs:
                self.scheduler.step()

        print("\n✅ Training complete!")
        print(f"Best validation CER: {self.best_cer:.2f}%")
        print(f"Best validation loss: {self.best_val_loss:.4f}")

        # Save final model
        self.save_checkpoint('final_model.pth')
        self.writer.close()

    def save_checkpoint(self, filename, metrics=None):
        """Save model checkpoint."""
        checkpoint = {
            'epoch': self.epoch,
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'scheduler_state_dict': self.scheduler.state_dict(),
            'best_val_loss': self.best_val_loss,
            'best_cer': self.best_cer,
        }

        if metrics:
            checkpoint['metrics'] = metrics

        checkpoint_path = self.output_dir / filename
        torch.save(checkpoint, checkpoint_path)
        print(f"  Saved checkpoint: {checkpoint_path}")

    def load_checkpoint(self, checkpoint_path):
        """Load model checkpoint."""
        checkpoint = torch.load(checkpoint_path, map_location=self.device)

        self.model.load_state_dict(checkpoint['model_state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        self.scheduler.load_state_dict(checkpoint['scheduler_state_dict'])

        self.epoch = checkpoint['epoch']
        self.best_val_loss = checkpoint['best_val_loss']
        self.best_cer = checkpoint.get('best_cer', float('inf'))

        print(f"✅ Loaded checkpoint from epoch {self.epoch}")
        print(f"  Best validation loss: {self.best_val_loss:.4f}")
        print(f"  Best CER: {self.best_cer:.2f}%")


def main():
    parser = argparse.ArgumentParser(description='Train ViT-OCR model')

    # Data arguments
    parser.add_argument('--data-dir', required=True, help='Path to training data directory')
    parser.add_argument('--batch-size', type=int, default=32, help='Batch size')
    parser.add_argument('--num-workers', type=int, default=4, help='Number of data loading workers')

    # Model arguments
    parser.add_argument('--model-size', default='base',
                       choices=['tiny', 'small', 'base', 'large'],
                       help='Model size')
    parser.add_argument('--img-size', type=int, default=224, help='Input image size')
    parser.add_argument('--max-seq-len', type=int, default=50, help='Maximum sequence length')

    # Training arguments
    parser.add_argument('--epochs', type=int, default=100, help='Number of epochs')
    parser.add_argument('--lr', type=float, default=1e-4, help='Learning rate')
    parser.add_argument('--weight-decay', type=float, default=0.01, help='Weight decay')
    parser.add_argument('--warmup-epochs', type=int, default=5, help='Warmup epochs')
    parser.add_argument('--label-smoothing', type=float, default=0.1, help='Label smoothing')

    # Checkpoint arguments
    parser.add_argument('--output-dir', default='checkpoints', help='Output directory')
    parser.add_argument('--resume', help='Resume from checkpoint')
    parser.add_argument('--save-every', type=int, default=5, help='Save checkpoint every N epochs')
    parser.add_argument('--validate-every', type=int, default=1, help='Validate every N epochs')

    # Device arguments
    parser.add_argument('--device', default='cuda' if torch.cuda.is_available() else 'cpu',
                       help='Device to use')

    args = parser.parse_args()

    # Create dataloaders
    print("Loading data...")
    dataloaders = create_dataloaders(
        data_dir=args.data_dir,
        batch_size=args.batch_size,
        num_workers=args.num_workers,
        image_size=(args.img_size, args.img_size),
        max_label_length=args.max_seq_len
    )

    print(f"✅ Data loaded!")
    print(f"  Train batches: {len(dataloaders['train'])}")
    print(f"  Val batches: {len(dataloaders['val'])}")
    print(f"  Vocabulary size: {dataloaders['vocab_size']}")

    # Create model
    print("\nCreating model...")
    model = create_model(
        vocab_size=dataloaders['vocab_size'],
        model_size=args.model_size,
        img_size=args.img_size,
        max_seq_len=args.max_seq_len
    )

    total_params = sum(p.numel() for p in model.parameters())
    print(f"✅ Model created ({args.model_size})!")
    print(f"  Total parameters: {total_params:,}")

    # Create trainer
    trainer = Trainer(
        model=model,
        dataloaders=dataloaders,
        device=args.device,
        learning_rate=args.lr,
        weight_decay=args.weight_decay,
        warmup_epochs=args.warmup_epochs,
        label_smoothing=args.label_smoothing,
        output_dir=args.output_dir,
        pad_idx=dataloaders['char_to_idx']['<PAD>']
    )

    # Resume from checkpoint if specified
    if args.resume:
        trainer.load_checkpoint(args.resume)

    # Train
    trainer.train(
        num_epochs=args.epochs,
        save_every=args.save_every,
        validate_every=args.validate_every
    )


if __name__ == '__main__':
    main()
