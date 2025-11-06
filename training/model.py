"""
Vision Transformer model for OCR.

This implements a ViT encoder + Transformer decoder architecture
similar to TrOCR but trainable from scratch.
"""

import torch
import torch.nn as nn
import math


class PatchEmbedding(nn.Module):
    """
    Split image into patches and embed them.
    """

    def __init__(self, img_size=224, patch_size=16, in_channels=1, embed_dim=768):
        super().__init__()
        self.img_size = img_size
        self.patch_size = patch_size
        self.n_patches = (img_size // patch_size) ** 2

        # Linear projection of flattened patches
        self.proj = nn.Conv2d(
            in_channels,
            embed_dim,
            kernel_size=patch_size,
            stride=patch_size
        )

    def forward(self, x):
        """
        Args:
            x: [batch_size, channels, height, width]

        Returns:
            [batch_size, n_patches, embed_dim]
        """
        x = self.proj(x)  # [B, embed_dim, H/P, W/P]
        x = x.flatten(2)  # [B, embed_dim, n_patches]
        x = x.transpose(1, 2)  # [B, n_patches, embed_dim]
        return x


class PositionalEncoding(nn.Module):
    """
    Sinusoidal positional encoding.
    """

    def __init__(self, d_model, max_len=5000):
        super().__init__()

        position = torch.arange(max_len).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2) * (-math.log(10000.0) / d_model))

        pe = torch.zeros(max_len, d_model)
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)

        self.register_buffer('pe', pe)

    def forward(self, x):
        """
        Args:
            x: [batch_size, seq_len, d_model]

        Returns:
            [batch_size, seq_len, d_model]
        """
        return x + self.pe[:x.size(1)]


class VisionTransformerEncoder(nn.Module):
    """
    Vision Transformer encoder for image feature extraction.
    """

    def __init__(self,
                 img_size=224,
                 patch_size=16,
                 in_channels=1,
                 embed_dim=768,
                 depth=12,
                 num_heads=12,
                 mlp_ratio=4.0,
                 dropout=0.1):
        super().__init__()

        self.patch_embed = PatchEmbedding(img_size, patch_size, in_channels, embed_dim)
        num_patches = self.patch_embed.n_patches

        # Learnable class token
        self.cls_token = nn.Parameter(torch.zeros(1, 1, embed_dim))

        # Learnable position embeddings
        self.pos_embed = nn.Parameter(torch.zeros(1, num_patches + 1, embed_dim))

        self.pos_drop = nn.Dropout(p=dropout)

        # Transformer encoder blocks
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=embed_dim,
            nhead=num_heads,
            dim_feedforward=int(embed_dim * mlp_ratio),
            dropout=dropout,
            activation='gelu',
            batch_first=True
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=depth)

        self.norm = nn.LayerNorm(embed_dim)

        # Initialize weights
        nn.init.trunc_normal_(self.cls_token, std=0.02)
        nn.init.trunc_normal_(self.pos_embed, std=0.02)

    def forward(self, x):
        """
        Args:
            x: [batch_size, channels, height, width]

        Returns:
            [batch_size, num_patches + 1, embed_dim]
        """
        B = x.shape[0]

        # Patch embedding
        x = self.patch_embed(x)  # [B, num_patches, embed_dim]

        # Add class token
        cls_tokens = self.cls_token.expand(B, -1, -1)
        x = torch.cat([cls_tokens, x], dim=1)  # [B, num_patches + 1, embed_dim]

        # Add position embeddings
        x = x + self.pos_embed
        x = self.pos_drop(x)

        # Transformer encoder
        x = self.encoder(x)
        x = self.norm(x)

        return x


class TransformerDecoder(nn.Module):
    """
    Transformer decoder for sequence generation.
    """

    def __init__(self,
                 vocab_size,
                 embed_dim=512,
                 num_heads=8,
                 num_layers=6,
                 max_seq_len=50,
                 dropout=0.1):
        super().__init__()

        self.embed_dim = embed_dim
        self.max_seq_len = max_seq_len

        # Token embedding
        self.token_embed = nn.Embedding(vocab_size, embed_dim)

        # Positional encoding
        self.pos_encoding = PositionalEncoding(embed_dim, max_seq_len)

        # Transformer decoder
        decoder_layer = nn.TransformerDecoderLayer(
            d_model=embed_dim,
            nhead=num_heads,
            dim_feedforward=embed_dim * 4,
            dropout=dropout,
            activation='gelu',
            batch_first=True
        )
        self.decoder = nn.TransformerDecoder(decoder_layer, num_layers=num_layers)

        # Output projection
        self.fc_out = nn.Linear(embed_dim, vocab_size)

        self.dropout = nn.Dropout(dropout)

        # Initialize weights
        nn.init.trunc_normal_(self.token_embed.weight, std=0.02)

    def generate_square_subsequent_mask(self, sz):
        """
        Generate causal mask for autoregressive decoding.
        """
        mask = torch.triu(torch.ones(sz, sz), diagonal=1)
        mask = mask.masked_fill(mask == 1, float('-inf'))
        return mask

    def forward(self, tgt, memory, tgt_mask=None):
        """
        Args:
            tgt: [batch_size, tgt_seq_len] - target token indices
            memory: [batch_size, src_seq_len, embed_dim] - encoder output
            tgt_mask: Causal mask for target sequence

        Returns:
            [batch_size, tgt_seq_len, vocab_size] - logits
        """
        # Embed tokens
        tgt = self.token_embed(tgt)  # [B, tgt_seq_len, embed_dim]
        tgt = self.pos_encoding(tgt)
        tgt = self.dropout(tgt)

        # Generate causal mask if not provided
        if tgt_mask is None:
            tgt_mask = self.generate_square_subsequent_mask(tgt.size(1)).to(tgt.device)

        # Decode
        output = self.decoder(tgt, memory, tgt_mask=tgt_mask)

        # Project to vocabulary
        logits = self.fc_out(output)

        return logits


class ViTOCR(nn.Module):
    """
    Complete Vision Transformer OCR model.

    Architecture: ViT Encoder + Transformer Decoder
    """

    def __init__(self,
                 vocab_size,
                 img_size=224,
                 patch_size=16,
                 in_channels=1,
                 encoder_embed_dim=768,
                 encoder_depth=12,
                 encoder_num_heads=12,
                 decoder_embed_dim=512,
                 decoder_num_heads=8,
                 decoder_num_layers=6,
                 max_seq_len=50,
                 dropout=0.1):
        super().__init__()

        self.vocab_size = vocab_size
        self.max_seq_len = max_seq_len

        # Encoder
        self.encoder = VisionTransformerEncoder(
            img_size=img_size,
            patch_size=patch_size,
            in_channels=in_channels,
            embed_dim=encoder_embed_dim,
            depth=encoder_depth,
            num_heads=encoder_num_heads,
            dropout=dropout
        )

        # Project encoder output to decoder dimension if different
        self.encoder_proj = nn.Linear(encoder_embed_dim, decoder_embed_dim) \
            if encoder_embed_dim != decoder_embed_dim else nn.Identity()

        # Decoder
        self.decoder = TransformerDecoder(
            vocab_size=vocab_size,
            embed_dim=decoder_embed_dim,
            num_heads=decoder_num_heads,
            num_layers=decoder_num_layers,
            max_seq_len=max_seq_len,
            dropout=dropout
        )

    def forward(self, images, targets):
        """
        Training forward pass.

        Args:
            images: [batch_size, channels, height, width]
            targets: [batch_size, seq_len] - target token indices

        Returns:
            [batch_size, seq_len, vocab_size] - logits
        """
        # Encode image
        memory = self.encoder(images)  # [B, num_patches + 1, encoder_embed_dim]
        memory = self.encoder_proj(memory)  # [B, num_patches + 1, decoder_embed_dim]

        # Decode (teacher forcing)
        # Use targets[:, :-1] as input (shift right)
        tgt_input = targets[:, :-1]

        logits = self.decoder(tgt_input, memory)

        return logits

    @torch.no_grad()
    def generate(self, images, sos_idx, eos_idx, max_len=None):
        """
        Autoregressive generation (inference).

        Args:
            images: [batch_size, channels, height, width]
            sos_idx: Start-of-sequence token index
            eos_idx: End-of-sequence token index
            max_len: Maximum sequence length (default: self.max_seq_len)

        Returns:
            [batch_size, seq_len] - generated token indices
        """
        self.eval()
        batch_size = images.size(0)
        max_len = max_len or self.max_seq_len

        # Encode image
        memory = self.encoder(images)
        memory = self.encoder_proj(memory)

        # Start with SOS token
        generated = torch.full((batch_size, 1), sos_idx, dtype=torch.long, device=images.device)

        # Track which sequences have finished
        finished = torch.zeros(batch_size, dtype=torch.bool, device=images.device)

        for _ in range(max_len - 1):
            # Decode one step
            logits = self.decoder(generated, memory)  # [B, current_len, vocab_size]

            # Get next token (greedy)
            next_token = logits[:, -1, :].argmax(dim=-1, keepdim=True)  # [B, 1]

            # Append to generated sequence
            generated = torch.cat([generated, next_token], dim=1)

            # Check for EOS tokens
            finished |= (next_token.squeeze(-1) == eos_idx)

            # Stop if all sequences have finished
            if finished.all():
                break

        return generated


def create_model(vocab_size,
                model_size='base',
                img_size=224,
                max_seq_len=50):
    """
    Create ViT-OCR model with predefined configurations.

    Args:
        vocab_size: Size of character vocabulary
        model_size: 'tiny', 'small', 'base', or 'large'
        img_size: Input image size
        max_seq_len: Maximum sequence length

    Returns:
        ViTOCR model
    """
    configs = {
        'tiny': {
            'patch_size': 16,
            'encoder_embed_dim': 192,
            'encoder_depth': 6,
            'encoder_num_heads': 3,
            'decoder_embed_dim': 256,
            'decoder_num_heads': 4,
            'decoder_num_layers': 3,
        },
        'small': {
            'patch_size': 16,
            'encoder_embed_dim': 384,
            'encoder_depth': 8,
            'encoder_num_heads': 6,
            'decoder_embed_dim': 384,
            'decoder_num_heads': 6,
            'decoder_num_layers': 4,
        },
        'base': {
            'patch_size': 16,
            'encoder_embed_dim': 768,
            'encoder_depth': 12,
            'encoder_num_heads': 12,
            'decoder_embed_dim': 512,
            'decoder_num_heads': 8,
            'decoder_num_layers': 6,
        },
        'large': {
            'patch_size': 16,
            'encoder_embed_dim': 1024,
            'encoder_depth': 24,
            'encoder_num_heads': 16,
            'decoder_embed_dim': 768,
            'decoder_num_heads': 12,
            'decoder_num_layers': 8,
        },
    }

    config = configs[model_size]

    model = ViTOCR(
        vocab_size=vocab_size,
        img_size=img_size,
        patch_size=config['patch_size'],
        in_channels=1,  # Grayscale
        encoder_embed_dim=config['encoder_embed_dim'],
        encoder_depth=config['encoder_depth'],
        encoder_num_heads=config['encoder_num_heads'],
        decoder_embed_dim=config['decoder_embed_dim'],
        decoder_num_heads=config['decoder_num_heads'],
        decoder_num_layers=config['decoder_num_layers'],
        max_seq_len=max_seq_len,
    )

    return model


# Test code
if __name__ == '__main__':
    print("Testing ViT-OCR model...")

    # Create model
    vocab_size = 500
    model = create_model(vocab_size, model_size='tiny')

    # Count parameters
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)

    print(f"✅ Model created successfully!")
    print(f"Total parameters: {total_params:,}")
    print(f"Trainable parameters: {trainable_params:,}")

    # Test forward pass
    batch_size = 2
    images = torch.randn(batch_size, 1, 224, 224)
    targets = torch.randint(0, vocab_size, (batch_size, 30))

    logits = model(images, targets)
    print(f"\nForward pass test:")
    print(f"  Input images: {images.shape}")
    print(f"  Input targets: {targets.shape}")
    print(f"  Output logits: {logits.shape}")

    # Test generation
    generated = model.generate(images, sos_idx=1, eos_idx=2, max_len=20)
    print(f"\nGeneration test:")
    print(f"  Generated shape: {generated.shape}")
    print(f"  Generated tokens: {generated[0].tolist()[:10]}...")
