"""Second-model check: does the ranking induced by Q survive a different backbone?

Same protocol as the main grid (6 epochs, batch 64, 224x224, ImageNet weights,
val-selected checkpoint, test evaluated once), but MobileNetV3-Small instead of
ResNet18. Only a handful of representative versions are re-trained, so the claim
we can support is about the *ordering* of versions, not about absolute accuracy.

Run: python src/second_model.py
Out: results/versions/model2/run2_<version>_s<seed>.json
"""
import csv, json, os, sys, time
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("NEU_BATCH", "64")
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from PIL import Image
import torchvision
from torchvision import transforms

from common import NEUCLS, evaluate, IMG_SIZE, BATCH, MEAN, STD
from versions import VERSIONS_DIR
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUT = os.path.join(ROOT, "results", "versions", "model2")
EPOCHS = 6
LR = 3e-4

# one version per family, chosen to span the range of measured difficulty
TARGETS = ["V00_clean", "V01_gaussian_noise_L1", "V09_jpeg_compression_L1",
           "V16_motion_blur_L4", "V20_label_confusion_L4", "V25_cumulative_5defects"]
SEEDS = [0]


def build_mobilenet(n_classes=6, seed=0):
    torch.manual_seed(seed)
    try:
        w = torchvision.models.MobileNet_V3_Small_Weights.IMAGENET1K_V1
        m = torchvision.models.mobilenet_v3_small(weights=w)
        init = "imagenet_pretrained"
    except Exception as e:
        m = torchvision.models.mobilenet_v3_small(weights=None)
        init = "random_init (%s: %s)" % (type(e).__name__, e)
    m.classifier[-1] = nn.Linear(m.classifier[-1].in_features, n_classes)
    return m, init


def load_version(vdir):
    rows = list(csv.DictReader(open(os.path.join(vdir, "labels.csv"))))
    sets = {"train": [], "val": [], "test": []}
    labels = {}
    for r in rows:
        sets[r["split"]].append(r["filename"])
        if r["split"] == "train":
            labels[r["filename"]] = int(r["label_idx"])
    for k in sets:
        sets[k].sort()

    def ds(split):
        d = os.path.join(vdir, "images", split)
        have = {os.path.splitext(x)[0]: x for x in os.listdir(d)}
        imgs = {}
        for f in sets[split]:
            imgs[f] = Image.open(os.path.join(d, have[os.path.splitext(f)[0]])).convert("L")
        return imgs

    imgs = {k: ds(k) for k in sets}
    tr = NEUCLS(sets["train"], images=imgs["train"], labels=labels)
    va = NEUCLS(sets["val"], images=imgs["val"])
    te = NEUCLS(sets["test"], images=imgs["test"])
    return sets, tr, va, te


def train(tr, va, te, seed):
    import random
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, init = build_mobilenet(seed=seed)
    model = model.to(device)
    dl_tr = DataLoader(tr, batch_size=BATCH, shuffle=True, num_workers=2, pin_memory=True)
    dl_va = DataLoader(va, batch_size=BATCH, shuffle=False, num_workers=2, pin_memory=True)
    dl_te = DataLoader(te, batch_size=BATCH, shuffle=False, num_workers=2, pin_memory=True)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS)
    lossf = nn.CrossEntropyLoss()
    best = {"acc": -1, "epoch": -1, "state": None}
    hist = []
    t0 = time.time()
    for ep in range(1, EPOCHS + 1):
        model.train(); tot = cor = 0; ls = 0.0
        for x, y in dl_tr:
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            opt.zero_grad(set_to_none=True)
            out = model(x); loss = lossf(out, y)
            loss.backward(); opt.step()
            ls += loss.item() * y.numel(); tot += y.numel()
            cor += (out.argmax(1) == y).sum().item()
        sched.step()
        v = evaluate(model, dl_va, device)
        hist.append({"epoch": ep, "loss": ls / tot, "train_acc": cor / tot, "val_acc": v["acc"]})
        print("  ep%02d loss=%.4f train_acc=%.4f val_acc=%.4f" % (ep, ls / tot, cor / tot, v["acc"]), flush=True)
        if v["acc"] > best["acc"]:
            best = {"acc": v["acc"], "epoch": ep,
                    "state": {k: t.detach().cpu().clone() for k, t in model.state_dict().items()}}
    model.load_state_dict(best["state"])
    te_res = evaluate(model, dl_te, device)
    return {"init": init, "best_epoch": best["epoch"], "best_val_acc": best["acc"],
            "test_acc": te_res["acc"], "test_per_class_acc": te_res["per_class_acc"],
            "history": hist, "train_time_s": round(time.time() - t0, 1),
            "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1024 ** 3, 2) if torch.cuda.is_available() else 0.0,
            "batch_size": BATCH, "img_size": IMG_SIZE, "epochs": EPOCHS, "lr": LR,
            "n_train": len(tr)}


def main():
    os.makedirs(OUT, exist_ok=True)
    for name in TARGETS:
        vdir = os.path.join(VERSIONS_DIR, name)
        if not os.path.isdir(vdir):
            print("MISSING " + vdir, flush=True); continue
        man = json.load(open(os.path.join(vdir, "manifest.json")))
        for seed in SEEDS:
            dst = os.path.join(OUT, "run2_%s_s%d.json" % (name, seed))
            if os.path.exists(dst):
                print("SKIP " + dst, flush=True); continue
            print("=== %s seed=%d n_train=%d ===" % (name, seed, man["n_train"]), flush=True)
            sets, tr, va, te = load_version(vdir)
            res = train(tr, va, te, seed)
            res.update({"version": name, "seed": seed, "model": "mobilenet_v3_small",
                        "Q": man.get("Q"), "manifest": man})
            json.dump(res, open(dst, "w"), indent=1)
            print("RESULT2 %s test_acc=%.4f Q=%.4f (%.0fs)" %
                  (name, res["test_acc"], man.get("Q") or -1, res["train_time_s"]), flush=True)


if __name__ == "__main__":
    main()
