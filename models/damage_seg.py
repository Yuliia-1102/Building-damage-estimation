"""Building-damage segmentation with the DINOv2-Emb U-Net (B2b weights), standalone.

One file, no project code. Needs: torch, torchvision, timm (>= 1.0), pillow, numpy.

    python damage_seg.py photo.jpg                     # -> photo_mask.png, photo_overlay.png
    python damage_seg.py photos/ --out results/ --probs

    from damage_seg import DamageSegmenter
    seg = DamageSegmenter("dinov2_b2b_6class.pt")
    probs = seg.predict_probs("photo.jpg")             # (H, W, 6) float32
    mask = probs.argmax(-1)                            # (H, W) class ids 0..5

How it works (the same as in the paper / the annotation tool):
  1. The whole photo -> ConvNeXt-L CLIP (timm, downloaded once, ~800 MB) -> a
     1536-number "what kind of scene" vector.
  2. The photo is covered by 518x518 crops with a stride of ~300 px (photos
     smaller than 518 px are upscaled first).
  3. Each crop + the scene vector + the crop's position (x/W, y/H) -> the U-Net
     (DINOv2 ViT-L/14 encoder + conv decoder) -> 6 class scores per pixel.
  4. Softmax probabilities of overlapping crops are averaged.
"""
import argparse
from pathlib import Path

import numpy as np
import timm
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.transforms as T
from PIL import Image
from torchvision.transforms.functional import InterpolationMode

CLASS_NAMES = ["Other", "Building", "Roof", "Damage", "Broken Window", "Damaged roof"]
COLORS = [(160, 160, 160), (40, 170, 60), (255, 165, 0), (170, 50, 200), (30, 90, 255), (230, 30, 30)]

DINO_MODEL = "vit_large_patch14_reg4_dinov2.lvd142m"
EMBEDDING_MODEL = "convnext_large_mlp.clip_laion2b_augreg_ft_in12k_384"
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]
PATCH, STRIDE = 518, 300


# --------------------------------------------------------------------------- model
class UNetDinoV2(nn.Module):
    """U-Net with a DINOv2 ViT-L/14 encoder (features from blocks 1, 7, 12, 20), plus a
    global image embedding and the crop position joined at the bottleneck."""

    def __init__(self, num_classes=6):
        super().__init__()
        # pretrained=False: every weight, the encoder's included, comes from our checkpoint
        self.encoder = timm.create_model(DINO_MODEL, pretrained=False, features_only=True,
                                         out_indices=(1, 7, 12, 20))
        c1, c2, c3, c4 = self.encoder.feature_info.channels()
        self.image_emb_fc = nn.Linear(1536, c4 // 2)
        self.position_emb_fc = nn.Linear(2, c4 // 4)
        self.bottleneck = self._conv_block(c4 + c4 // 2 + c4 // 4, c3)
        self.decoder4 = self._conv_block(c3 + c3, c2)
        self.decoder3 = self._conv_block(c2 + c2, c1)
        self.decoder2 = self._conv_block(c1 + c1, c1 // 2)
        self.decoder1 = self._conv_block(c1 // 2, c1 // 4)
        self.conv_last = nn.Conv2d(c1 // 4, num_classes, kernel_size=1)

    @staticmethod
    def _conv_block(in_ch, out_ch):
        return nn.Sequential(
            nn.Conv2d(in_ch, out_ch // 2, 3, padding=1), nn.BatchNorm2d(out_ch // 2), nn.GELU(), nn.Dropout(0.6),
            nn.Conv2d(out_ch // 2, out_ch, 3, padding=1), nn.BatchNorm2d(out_ch), nn.GELU(), nn.Dropout(0.6),
        )

    def forward(self, x, image_embedding, position):
        """x (B,3,518,518) ImageNet-normalized, image_embedding (B,1536), position (B,2)
        -> logits (B,6,518,518)."""
        enc1, enc2, enc3, enc4 = self.encoder(x)
        B, _, h, w = enc4.shape
        img_e = self.image_emb_fc(image_embedding).view(B, -1, 1, 1).expand(-1, -1, h, w)
        pos_e = self.position_emb_fc(position).view(B, -1, 1, 1).expand(-1, -1, h, w)
        d = self.bottleneck(torch.cat([enc4, img_e, pos_e], 1))
        d = self.decoder4(torch.cat([F.interpolate(d, size=enc3.shape[2:], mode="bilinear", align_corners=False), enc3], 1))
        d = self.decoder3(torch.cat([F.interpolate(d, size=enc2.shape[2:], mode="bilinear", align_corners=False), enc2], 1))
        d = self.decoder2(torch.cat([F.interpolate(d, size=enc1.shape[2:], mode="bilinear", align_corners=False), enc1], 1))
        d = self.decoder1(F.interpolate(d, scale_factor=4, mode="bilinear", align_corners=False))
        d = F.interpolate(d, scale_factor=3.5, mode="bilinear", align_corners=False)
        return self.conv_last(d)


# --------------------------------------------------------------------------- crops
def _upscale_if_small(image, size):
    w, h = image.size
    if w >= size and h >= size:
        return image
    s = max(size / w, size / h)
    return image.resize((int(round(w * s)), int(round(h * s))), Image.BILINEAR)


def _positions(length, patch, stride):
    if length == patch:
        return [0]
    n = max(2, int(round((length - patch) / stride)) + 1)
    step = (length - patch) / (n - 1)
    return [min(int(round(i * step)), length - patch) for i in range(n)]


def patch_grid(width, height, patch=PATCH, stride=STRIDE):
    """Top-left corners of crops that cover the image evenly (first and last crop touch the edges)."""
    return [(x, y) for y in _positions(height, patch, stride) for x in _positions(width, patch, stride)]


# --------------------------------------------------------------------------- inference
class DamageSegmenter:
    def __init__(self, weights, device=None, batch_size=4):
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.batch_size = batch_size
        self.model = UNetDinoV2()
        self.model.load_state_dict(torch.load(weights, map_location="cpu"), strict=True)
        self.model.to(self.device).eval()
        self.embedder = timm.create_model(EMBEDDING_MODEL, pretrained=True, num_classes=0).to(self.device).eval()
        self._embed_tf = T.Compose([T.Resize((384, 384), interpolation=InterpolationMode.BILINEAR),
                                    T.ToTensor(), T.Normalize(IMAGENET_MEAN, IMAGENET_STD)])
        self._crop_tf = T.Compose([T.ToTensor(), T.Normalize(IMAGENET_MEAN, IMAGENET_STD)])

    @torch.no_grad()
    def predict_probs(self, image, progress=None):
        """image: path or PIL image -> class probabilities (H, W, 6) float32 at the
        original size. progress(done, total) is called after each batch of crops."""
        if not isinstance(image, Image.Image):
            image = Image.open(image)
        image = image.convert("RGB")
        orig_size = image.size
        image = _upscale_if_small(image, PATCH)
        w, h = image.size
        emb = self.embedder(self._embed_tf(image)[None].to(self.device))           # (1, 1536)

        acc = torch.zeros(6, h, w, device=self.device)
        cnt = torch.zeros(1, h, w, device=self.device)
        grid = patch_grid(w, h)
        for i in range(0, len(grid), self.batch_size):
            corners = grid[i:i + self.batch_size]
            x = torch.stack([self._crop_tf(image.crop((x0, y0, x0 + PATCH, y0 + PATCH))) for x0, y0 in corners])
            pos = torch.tensor([[x0 / w, y0 / h] for x0, y0 in corners], dtype=torch.float32)
            probs = torch.softmax(self.model(x.to(self.device), emb.expand(len(corners), -1),
                                             pos.to(self.device)).float(), 1)
            for (x0, y0), p in zip(corners, probs):
                acc[:, y0:y0 + PATCH, x0:x0 + PATCH] += p
                cnt[:, y0:y0 + PATCH, x0:x0 + PATCH] += 1
            if progress:
                progress(min(i + self.batch_size, len(grid)), len(grid))
        probs = acc / cnt
        if image.size != orig_size:                    # back to the size of the input photo
            probs = F.interpolate(probs[None], size=orig_size[::-1], mode="bilinear", align_corners=False)[0]
        return probs.permute(1, 2, 0).cpu().numpy()

    def predict_mask(self, image):
        """(H, W) uint8 class ids: 0 Other, 1 Building, 2 Roof, 3 Damage, 4 Broken Window, 5 Damaged roof."""
        return self.predict_probs(image).argmax(-1).astype(np.uint8)


def colorize(mask):
    return np.array(COLORS, np.uint8)[mask]


def overlay(image, mask, alpha=0.5):
    rgb = np.asarray(Image.open(image).convert("RGB") if not isinstance(image, Image.Image) else image.convert("RGB"))
    out = rgb.astype(np.float32)
    keep = mask > 0                                     # "Other" stays as the photo
    out[keep] = (1 - alpha) * out[keep] + alpha * colorize(mask)[keep]
    return out.astype(np.uint8)


# --------------------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input", help="an image or a folder of images")
    ap.add_argument("--weights", default=str(Path(__file__).with_name("dinov2_b2b_6class.pt")))
    ap.add_argument("--out", help="output folder (default: next to each image)")
    ap.add_argument("--device", help="cuda / cpu (default: cuda if available)")
    ap.add_argument("--probs", action="store_true", help="also save the probabilities (.npy, H x W x 6, float16)")
    a = ap.parse_args()

    src = Path(a.input)
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
    files = sorted(p for p in src.iterdir() if p.suffix.lower() in exts) if src.is_dir() else [src]
    seg = DamageSegmenter(a.weights, a.device)
    for f in files:
        out = Path(a.out) if a.out else f.parent
        out.mkdir(parents=True, exist_ok=True)
        probs = seg.predict_probs(f, progress=lambda d, n: print(f"\r{f.name}: crop {d}/{n}", end=""))
        mask = probs.argmax(-1).astype(np.uint8)
        Image.fromarray(mask).save(out / f"{f.stem}_mask.png")              # pixel value = class id
        Image.fromarray(overlay(f, mask)).save(out / f"{f.stem}_overlay.png")
        if a.probs:
            np.save(out / f"{f.stem}_probs.npy", probs.astype(np.float16))
        share = np.bincount(mask.ravel(), minlength=6) / mask.size
        print(f"\r{f.name}: " + ", ".join(f"{n} {s:.1%}" for n, s in zip(CLASS_NAMES, share)))


if __name__ == "__main__":
    main()
