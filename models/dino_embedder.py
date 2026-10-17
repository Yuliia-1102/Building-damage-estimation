"""Frame embeddings with DINOv2 (task 8.3), used only to compare frames with each other."""
import numpy as np
from PIL import Image

from core import config


class DinoEmbedder:
    def __init__(self, model_name: str | None = None, device: str = "cpu"):
        import timm
        import torch
        self.torch = torch
        self.model = timm.create_model(model_name or config.get("video", "embedding_model"),
                                       pretrained=True, num_classes=0, img_size=224).to(device).eval()
        cfg = timm.data.resolve_data_config({}, model=self.model)
        cfg["input_size"] = (3, 224, 224)          # frame comparison does not need 518 px; 16x16 patches
        self.transform = timm.data.create_transform(**cfg)
        self.device = device

    def embed(self, images: list[np.ndarray]) -> np.ndarray:
        with self.torch.no_grad():
            x = self.torch.stack([self.transform(Image.fromarray(im)) for im in images]).to(self.device)
            return self.model(x).cpu().numpy()
