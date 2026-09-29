"""PyTorch CNN pipeline: ResNet-50 / EfficientNet backbone + multi-task heads.

Outputs: visual attribute tags, defect risk, aesthetic style score, 2048-d embedding (for visual
similarity search), plus classical photo-quality signals and a dominant colour palette.

Heads are randomly initialised unless `CNN_HEAD_CHECKPOINT` points to fine-tuned weights; the
response carries `calibrated=false` in that case and model-head outputs are withheld.
"""
import asyncio
import io
import logging
import threading
from functools import lru_cache
from typing import Any

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torchvision import models, transforms

from app.core.config import settings

logger = logging.getLogger("optimarket.cnn")
Image.MAX_IMAGE_PIXELS = 50_000_000

ATTRIBUTES = ["solid", "striped", "floral", "graphic", "denim", "knit", "formal", "casual", "oversized", "athleisure"]
DEFECTS = ["stain", "tear", "wrinkle", "misprint"]
NAMED_COLORS = {
    "black": (20, 20, 20), "white": (240, 240, 240), "grey": (128, 128, 128), "navy": (25, 35, 90),
    "blue": (40, 90, 200), "red": (200, 40, 40), "green": (40, 150, 70), "olive": (110, 120, 50),
    "yellow": (235, 200, 50), "orange": (230, 120, 30), "pink": (230, 130, 170), "purple": (120, 70, 170),
    "brown": (120, 80, 50), "beige": (215, 195, 165),
}


class MultiHeadNet(nn.Module):
    def __init__(self, backbone: str, pretrained: bool) -> None:
        super().__init__()
        if backbone == "resnet50":
            weights = models.ResNet50_Weights.DEFAULT if pretrained else None
            net = models.resnet50(weights=weights)
            feat = net.fc.in_features
            net.fc = nn.Identity()
        else:
            weights = models.EfficientNet_B0_Weights.DEFAULT if pretrained else None
            net = models.efficientnet_b0(weights=weights)
            feat = net.classifier[1].in_features
            net.classifier = nn.Identity()
        self.backbone, self.feat_dim = net, feat
        self.attr_head = nn.Sequential(nn.Dropout(0.2), nn.Linear(feat, len(ATTRIBUTES)))
        self.defect_head = nn.Sequential(nn.Dropout(0.2), nn.Linear(feat, len(DEFECTS)))
        self.aesthetic_head = nn.Sequential(nn.Linear(feat, 256), nn.GELU(), nn.Linear(256, 1))

    def forward(self, x: torch.Tensor):
        f = self.backbone(x)
        return f, self.attr_head(f), self.defect_head(f), self.aesthetic_head(f).squeeze(-1)


class VisionPipeline:
    def __init__(self) -> None:
        self._net: MultiHeadNet | None = None
        self._lock = threading.Lock()
        self.calibrated = False
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.tf = transforms.Compose([
            transforms.Resize(256), transforms.CenterCrop(224), transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

    @property
    def embedding_dim(self) -> int:
        return 2048 if settings.cnn_backbone == "resnet50" else 1280

    def _ensure_loaded(self) -> MultiHeadNet:
        with self._lock:
            if self._net is not None:
                return self._net
            try:
                net = MultiHeadNet(settings.cnn_backbone, settings.cnn_pretrained)
            except Exception as exc:  # weights download blocked
                logger.warning("Pretrained weights unavailable (%s); using random backbone", exc)
                net = MultiHeadNet(settings.cnn_backbone, pretrained=False)
            if settings.cnn_head_checkpoint:
                state = torch.load(settings.cnn_head_checkpoint, map_location="cpu")
                net.load_state_dict(state, strict=False)
                self.calibrated = True
            self._net = net.to(self.device).eval()
            return self._net

    # ---- classical signals -------------------------------------------------
    @staticmethod
    def _quality(img: Image.Image) -> dict[str, float]:
        g = np.asarray(img.convert("L").resize((min(512, img.width), min(512, img.height))), dtype=np.float32)
        lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
        sharp = float(lap.var())
        bright = float(g.mean() / 255)
        contrast = float(g.std() / 255)
        score = 0.5 * min(1.0, sharp / 300) + 0.3 * (1 - abs(bright - 0.55) / 0.55) + 0.2 * min(1.0, contrast / 0.25)
        return {"sharpness": round(sharp, 1), "brightness": round(bright, 3),
                "contrast": round(contrast, 3), "photo_quality": round(max(0.0, min(1.0, score)), 3)}

    @staticmethod
    def _palette(img: Image.Image, k: int = 4, iters: int = 8) -> list[dict[str, Any]]:
        px = np.asarray(img.resize((64, 64)), dtype=np.float32).reshape(-1, 3)
        rng = np.random.default_rng(0)
        centers = px[rng.choice(len(px), k, replace=False)].copy()
        labels = np.zeros(len(px), dtype=int)
        for _ in range(iters):
            labels = ((px[:, None, :] - centers[None]) ** 2).sum(-1).argmin(1)
            for i in range(k):
                if (labels == i).any():
                    centers[i] = px[labels == i].mean(0)
        share = np.bincount(labels, minlength=k) / len(px)
        names = list(NAMED_COLORS)
        table = np.array(list(NAMED_COLORS.values()), dtype=np.float32)
        out = []
        for i in np.argsort(-share):
            rgb = centers[i]
            name = names[int(((table - rgb) ** 2).sum(1).argmin())]
            out.append({"name": name, "hex": "#%02x%02x%02x" % tuple(int(c) for c in rgb), "share": round(float(share[i]), 3)})
        return out

    # ---- inference ---------------------------------------------------------
    def _analyze_sync(self, data: bytes) -> dict[str, Any]:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        net = self._ensure_loaded()
        x = self.tf(img).unsqueeze(0).to(self.device)
        with torch.inference_mode():
            feat, attr_logits, defect_logits, aesth = net(x)
        emb = torch.nn.functional.normalize(feat, dim=-1)[0].cpu().tolist()
        result: dict[str, Any] = {
            "width": img.width, "height": img.height, "backbone": settings.cnn_backbone,
            "calibrated": self.calibrated, "quality": self._quality(img), "palette": self._palette(img),
            "embedding": emb,
        }
        if self.calibrated:
            attr_p = torch.sigmoid(attr_logits)[0].cpu().tolist()
            defect_p = torch.sigmoid(defect_logits)[0].cpu().tolist()
            result["attributes"] = sorted(
                ({"tag": t, "prob": round(p, 3)} for t, p in zip(ATTRIBUTES, attr_p) if p >= 0.5),
                key=lambda d: -d["prob"],
            )
            result["defects"] = {d: round(p, 3) for d, p in zip(DEFECTS, defect_p)}
            result["defect_risk"] = round(max(defect_p), 3)
            result["aesthetic_score"] = round(float(torch.sigmoid(aesth)[0]), 3)
        else:
            result.update(attributes=None, defects=None, defect_risk=None, aesthetic_score=None,
                          note="Task heads are uncalibrated; set CNN_HEAD_CHECKPOINT to a fine-tuned checkpoint.")
        return result

    async def analyze(self, data: bytes) -> dict[str, Any]:
        return await asyncio.to_thread(self._analyze_sync, data)


@lru_cache
def get_vision_pipeline() -> VisionPipeline:
    return VisionPipeline()
