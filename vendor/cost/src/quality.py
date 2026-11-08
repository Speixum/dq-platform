
"""Training-free data-quality features for a training set (the paper's tool layer).

All three components are computed WITHOUT training on NEU-CLS and WITHOUT seeing
any downstream accuracy, so the composite score can be validated by rank
correlation against measured accuracy without leakage.

  LC  label consistency : kNN agreement in a fixed ImageNet-ResNet18 embedding
                          (k=10, cosine). Detects label-noise defects.
  BAL class balance     : normalised class-count entropy H/log(C). Detects
                          imbalance defects.
  SHP sharpness         : mean Laplacian variance of the images relative to the
                          clean reference set. Detects resolution defects.

Composite score (primary, no fitted weights):
  Q = LC * BAL * SHP      (a dataset must satisfy all three to score high)
"""
import json, os
import os
import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset
import torchvision
from torchvision import transforms
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(ROOT, "data", "neu-cls")
CACHE = os.path.join(ROOT, "results", "_emb_cache.npz")
MEAN = (0.485, 0.456, 0.406); STD = (0.229, 0.224, 0.225)
PREFIXES = ["Cr", "In", "Pa", "PS", "RS", "Sc"]


class _ImgSet(Dataset):
    def __init__(self, files, images=None, size=224):
        self.files, self.images = files, images
        self.tf = transforms.Compose([transforms.Resize((size, size)), transforms.ToTensor(),
                                      transforms.Normalize(MEAN, STD)])

    def __len__(self):
        return len(self.files)

    def __getitem__(self, i):
        f = self.files[i]
        im = self.images[f] if self.images is not None else Image.open(os.path.join(DATA_DIR, f))
        return self.tf(im.convert("L").convert("RGB"))


@torch.no_grad()
def embed(files, images=None, bs=32):
    """Return (N,512) L2-normalised embeddings (resnet18 avgpool, no training)."""
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    net = torchvision.models.resnet18(weights=torchvision.models.ResNet18_Weights.IMAGENET1K_V1)
    net.fc = nn.Identity(); net.eval().to(dev)
    dl = DataLoader(_ImgSet(files, images), batch_size=bs, shuffle=False, num_workers=0)
    out = []
    for x in dl:
        out.append(net(x.to(dev)).float().cpu().numpy())
    e = np.concatenate(out, 0)
    e /= (np.linalg.norm(e, axis=1, keepdims=True) + 1e-8)
    return e


def embed_cached(files):
    if os.path.exists(CACHE):
        z = np.load(CACHE, allow_pickle=True)
        names = list(z["names"]); mat = z["emb"]
        have = {n: i for i, n in enumerate(names)}
        if all(f in have for f in files):
            return mat[[have[f] for f in files]]
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    allf = sorted([f for f in os.listdir(DATA_DIR) if f.lower().endswith(".bmp")])
    e = embed(allf)
    np.savez(CACHE, names=np.array(allf), emb=e)
    have = {n: i for i, n in enumerate(allf)}
    return e[[have[f] for f in files]]


def label_consistency(files, labels, emb=None, k=10):
    """Mean fraction of the k nearest neighbours (cosine) sharing the label."""
    if emb is None:
        emb = embed_cached(files)
    n = len(files)
    k = min(k, n - 1)
    sim = emb @ emb.T
    np.fill_diagonal(sim, -2.0)
    idx = np.argpartition(-sim, k, axis=1)[:, :k]
    y = np.asarray(labels)
    return float(np.mean(y[idx] == y[:, None]))


def class_counts(files, labels=None):
    c = np.zeros(6, dtype=int)
    for i, f in enumerate(files):
        c[labels[i] if labels is not None else PREFIXES.index(f.split("_")[0])] += 1
    return c


def balance_score(counts):
    p = counts[counts > 0] / counts.sum()
    return float(-(p * np.log(p)).sum() / np.log(len(counts)))


def sharpness(files, images=None):
    from scipy.ndimage import laplace
    vals = []
    for f in files:
        im = images[f] if images is not None else Image.open(os.path.join(DATA_DIR, f))
        a = np.asarray(im.convert("L"), dtype=np.float32)
        vals.append(float(np.var(laplace(a))))
    return float(np.mean(vals))


def quality_features(files, labels, images=None, ref_sharpness=None, emb=None):
    cnt = class_counts(files, labels)
    shp_raw = sharpness(files, images)
    lc = label_consistency(files, labels, emb=emb)
    bal = balance_score(cnt)
    shp = 1.0 if ref_sharpness is None else float(min(1.0, shp_raw / ref_sharpness))
    out = {"n": int(cnt.sum()), "counts": cnt.tolist(),
           "imbalance_ratio": float(cnt.max() / max(cnt.min(), 1)),
           "LC": round(lc, 4), "BAL": round(bal, 4),
           "SHP_raw": round(shp_raw, 2), "SHP": round(shp, 4),
           "Q": round(lc * bal * shp, 4)}
    return out
