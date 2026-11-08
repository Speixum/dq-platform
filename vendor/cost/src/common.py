
"""Shared utilities for the NEU-CLS data-defect controlled study.

Design notes (fixed for the whole study so that injection is the ONLY variable):
  * files are grouped by filename prefix (flat folder, no subdirs);
  * ONE fixed stratified split, serialised to disk and reused by every run;
  * no train-time augmentation (measurement must be clean);
  * input 224x224, ImageNet normalisation, torchvision ResNet18.
"""
import json, os, random, time
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from PIL import Image
import torchvision
from torchvision import transforms

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# the (flat) NEU-CLS folder; point NEU_DATA_DIR anywhere else if you keep it outside the repo
DATA_DIR = os.environ.get("NEU_DATA_DIR", os.path.join(ROOT, "data", "neu-cls"))
SPLIT_DIR = os.path.join(ROOT, "data", "splits")
RESULTS_DIR = os.path.join(ROOT, "results")
LOG_DIR = os.path.join(ROOT, "logs")
IMG_SIZE = 224
BATCH = int(os.environ.get("NEU_BATCH", "64"))   # measured: 1.67 GB peak on a 4 GB GPU
CLASSES = [("Cr", "crazing"), ("In", "inclusion"), ("Pa", "patches"),
           ("PS", "pitted_surface"), ("RS", "rolled-in_scale"), ("Sc", "scratches")]
PREFIX_TO_IDX = {p: i for i, (p, _) in enumerate(CLASSES)}
IDX_TO_NAME = {i: n for i, (_, n) in enumerate(CLASSES)}

MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)


def list_files():
    if not os.path.isdir(DATA_DIR):
        raise SystemExit(
            "NEU-CLS not found at " + DATA_DIR + "\n"
            "Download it (see docs/DATASETS.md), then either drop the .bmp files into that\n"
            "folder or point the environment variable NEU_DATA_DIR at the folder you keep them in.")
    fs = [f for f in os.listdir(DATA_DIR) if f.lower().endswith(".bmp")]
    fs.sort(key=lambda s: (s.split("_")[0], int(s.split("_")[1].split(".")[0])))
    return fs


def make_split(seed=42, fracs=(0.70, 0.15, 0.15), force=False):
    """Stratified per-class split, cached to JSON so every experiment reuses it."""
    os.makedirs(SPLIT_DIR, exist_ok=True)
    path = os.path.join(SPLIT_DIR, "split_seed" + str(seed) + ".json")
    if os.path.exists(path) and not force:
        return json.load(open(path))
    rng = random.Random(seed)
    by_cls = {}
    for f in list_files():
        by_cls.setdefault(f.split("_")[0], []).append(f)
    split = {"train": [], "val": [], "test": []}
    for p, fs in by_cls.items():
        fs = sorted(fs)
        rng.shuffle(fs)
        n = len(fs); n_tr = int(round(fracs[0] * n)); n_va = int(round(fracs[1] * n))
        split["train"] += fs[:n_tr]
        split["val"] += fs[n_tr:n_tr + n_va]
        split["test"] += fs[n_tr + n_va:]
    for k in split:
        split[k] = sorted(split[k])
    meta = {"seed": seed, "fracs": list(fracs), "counts": {k: len(v) for k, v in split.items()}}
    out = dict(meta); out.update(split)
    json.dump(out, open(path, "w"), indent=1)
    return out


class NEUCLS(Dataset):
    """Returns (image, label). Image list may be replaced by the defect injector."""
    def __init__(self, files, root=DATA_DIR, images=None, labels=None):
        self.files = files
        self.root = root
        self.images = images   # optional dict filename -> PIL.Image (in-memory injection)
        self.labels = labels   # optional dict filename -> int (label-noise injection)
        self.tf = transforms.Compose([
            transforms.Resize((IMG_SIZE, IMG_SIZE)),
            transforms.ToTensor(),
            transforms.Normalize(MEAN, STD),
        ])

    def __len__(self):
        return len(self.files)

    def __getitem__(self, i):
        f = self.files[i]
        img = self.images[f] if self.images is not None else Image.open(os.path.join(self.root, f))
        img = img.convert("L").convert("RGB")
        y = self.labels[f] if self.labels is not None else PREFIX_TO_IDX[f.split("_")[0]]
        return self.tf(img), y


def build_model(n_classes=6, seed=0):
    torch.manual_seed(seed)
    try:
        w = torchvision.models.ResNet18_Weights.IMAGENET1K_V1
        m = torchvision.models.resnet18(weights=w)
        init = "imagenet_pretrained"
    except Exception as e:              # offline -> random init, stated explicitly in logs
        m = torchvision.models.resnet18(weights=None)
        init = "random_init (" + type(e).__name__ + ": " + str(e) + ")"
    m.fc = nn.Linear(m.fc.in_features, n_classes)
    return m, init


def class_counts(files):
    c = {}
    for f in files:
        n = IDX_TO_NAME[PREFIX_TO_IDX[f.split("_")[0]]]
        c[n] = c.get(n, 0) + 1
    return dict(sorted(c.items()))


@torch.no_grad()
def evaluate(model, loader, device):
    model.eval()
    correct = n = 0
    per_cls_c = np.zeros(6); per_cls_n = np.zeros(6)
    for x, y in loader:
        x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
        p = model(x).argmax(1)
        correct += (p == y).sum().item(); n += y.numel()
        for t, q in zip(y.cpu().numpy(), p.cpu().numpy()):
            per_cls_n[t] += 1; per_cls_c[t] += int(t == q)
    acc = correct / max(n, 1)
    return {"acc": acc, "n": n,
            "per_class_acc": {IDX_TO_NAME[i]: (float(per_cls_c[i] / per_cls_n[i]) if per_cls_n[i] else None)
                              for i in range(6)}}


def train_one(files_train, files_val, images_train=None, seed=0, epochs=15,
              lr=3e-4, tag="run", test_files=None, images_test=None,
              labels_train=None, log_extra=None):
    """Train on (possibly injected) train split; model selection on val; test once."""
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    tr = NEUCLS(files_train, images=images_train, labels=labels_train)
    va = NEUCLS(files_val)
    dl_tr = DataLoader(tr, batch_size=BATCH, shuffle=True, num_workers=4,
                       pin_memory=True, drop_last=False)
    dl_va = DataLoader(va, batch_size=BATCH, shuffle=False, num_workers=4, pin_memory=True)

    model, init = build_model(6, seed)
    model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    crit = nn.CrossEntropyLoss()

    torch.cuda.reset_peak_memory_stats()
    hdr = {
        "tag": tag, "seed": seed, "init": init, "device": str(device),
        "batch_size": BATCH, "img_size": IMG_SIZE, "epochs": epochs, "lr": lr,
        "n_train": len(files_train), "n_val": len(files_val),
        "n_test": len(test_files) if test_files else None,
        "train_class_counts": class_counts(files_train),
        "val_class_counts": class_counts(files_val),
        "hyper": {"opt": "AdamW", "wd": 1e-4, "sched": "cosine", "augmentation": "none"},
    }
    if log_extra:
        hdr.update(log_extra)
    print(json.dumps(hdr, ensure_ascii=False))

    hist = []
    t0 = time.time()
    best = (-1.0, -1, None)
    for ep in range(epochs):
        model.train()
        tot = cor = 0; ls = 0.0
        for x, y in dl_tr:
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            opt.zero_grad(set_to_none=True)
            out = model(x)
            loss = crit(out, y)
            loss.backward(); opt.step()
            ls += loss.item() * y.numel(); cor += (out.argmax(1) == y).sum().item(); tot += y.numel()
        sched.step()
        v = evaluate(model, dl_va, device)
        hist.append({"epoch": ep + 1, "train_loss": round(ls / tot, 5),
                     "train_acc": round(cor / tot, 5), "val_acc": round(v["acc"], 5)})
        if v["acc"] > best[0]:
            best = (v["acc"], ep + 1, {k: t.detach().clone() for k, t in model.state_dict().items()})
        print("  ep%02d loss=%.4f train_acc=%.4f val_acc=%.4f" % (ep + 1, ls / tot, cor / tot, v["acc"]), flush=True)
    train_time = time.time() - t0

    model.load_state_dict(best[2])
    res = {"tag": tag, "seed": seed, "init": init, "best_epoch": best[1],
           "best_val_acc": round(best[0], 5), "train_time_s": round(train_time, 1),
           "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2) if device.type == "cuda" else None,
           "history": hist, "batch_size": BATCH,
           "n_train": len(files_train), "n_val": len(files_val)}
    if test_files:
        dl_te = DataLoader(NEUCLS(test_files, images=images_test), batch_size=BATCH,
                           shuffle=False, num_workers=4, pin_memory=True)
        te = evaluate(model, dl_te, device)
        res["test_acc"] = round(te["acc"], 5); res["n_test"] = te["n"]
        res["test_per_class_acc"] = te["per_class_acc"]
        res["test_class_counts"] = class_counts(test_files)
    print(json.dumps({k: v for k, v in res.items() if k != "history"}, indent=1, ensure_ascii=False))
    return res
