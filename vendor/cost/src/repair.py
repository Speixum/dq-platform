"""Repair loop: find the worst delivered version, flag its most suspicious 20%
of training samples with the same training-free signals used by Q, replace only
those with clean originals, and retrain.

This is the "problem closed-loop" step: detect -> localise -> repair -> re-measure.

Run: python src/repair.py V16_motion_blur_L4
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("NEU_BATCH", "64")
import numpy as np
from PIL import Image
import torch

from common import make_split, train_one, RESULTS_DIR, DATA_DIR
from quality import embed, quality_features, label_consistency, sharpness
from versions import VERSIONS_DIR

OUT = os.path.join(RESULTS_DIR, "versions")
REF = json.load(open(os.path.join(RESULTS_DIR, "_ref_sharpness.json")))["clean_train"]
FRAC = float(os.environ.get("NEU_REPAIR_FRAC", "0.20"))


def load_version_train(root):
    rows = open(os.path.join(root, "labels.csv")).read().strip().split("\n")[1:]
    img_dir = os.path.join(root, "images", "train")
    have = {os.path.splitext(x)[0]: os.path.join(img_dir, x) for x in os.listdir(img_dir)}
    files, labels, imgs = [], {}, {}
    for r in rows:
        f, sub, y, _ = r.split(",")
        if sub == "train":
            files.append(f); labels[f] = int(y)
            imgs[f] = Image.open(have[os.path.splitext(f)[0]]).convert("L")
    files.sort()
    return files, labels, imgs


def suspicion_scores(files, labels, imgs, emb):
    """Per-sample suspicion = z-scored (label inconsistency) + z-scored (blurriness)."""
    y = np.array([labels[f] for f in files])
    sim = emb @ emb.T
    np.fill_diagonal(sim, -2.0)
    k = min(10, len(files) - 1)
    idx = np.argpartition(-sim, k, axis=1)[:, :k]
    agree = (y[idx] == y[:, None]).mean(1)          # 1.0 = all neighbours agree
    from scipy.ndimage import laplace
    shp = np.array([float(np.var(laplace(np.asarray(imgs[f].convert("L"), dtype=np.float32))))
                    for f in files])
    z = lambda a: (a - a.mean()) / (a.std() + 1e-8)
    return z(1.0 - agree) + z(1.0 - np.minimum(1.0, shp / REF))


def main(vdir):
    root = os.path.join(VERSIONS_DIR, vdir)
    man = json.load(open(os.path.join(root, "manifest.json")))
    sp = make_split(42)
    files, labels, imgs = load_version_train(root)
    labs = [labels[f] for f in files]   # quality_features indexes labels positionally
    emb = embed(files, images=imgs)
    q_before = quality_features(files, labs, images=imgs, ref_sharpness=REF, emb=emb)

    s = suspicion_scores(files, labels, imgs, emb)
    n_fix = int(round(FRAC * len(files)))
    victims = set(np.array(files)[np.argsort(-s)[:n_fix]].tolist())

    imgs_fix = dict(imgs)
    for f in victims:
        imgs_fix[f] = Image.open(os.path.join(DATA_DIR, f)).convert("L")
    emb_fix = embed(files, images=imgs_fix)
    q_after = quality_features(files, labs, images=imgs_fix, ref_sharpness=REF, emb=emb_fix)

    print("REPAIR %s  flagged=%d/%d (%.0f%%)" % (vdir, n_fix, len(files), 100 * FRAC))
    print("Q before=%.4f (LC %.3f SHP %.3f)  after=%.4f (LC %.3f SHP %.3f)" %
          (q_before["Q"], q_before["LC"], q_before["SHP"],
           q_after["Q"], q_after["LC"], q_after["SHP"]), flush=True)

    r = train_one(files, sp["val"], images_train=imgs_fix, labels_train=labels, seed=0,
                  epochs=6, tag=vdir + "_repaired", test_files=sp["test"],
                  log_extra={"repair_of": vdir, "repaired_fraction": FRAC,
                             "n_repaired": n_fix, "Q_before": q_before["Q"], "Q_after": q_after["Q"]})
    r["repair"] = {"source_version": vdir, "fraction": FRAC, "n_repaired": n_fix,
                   "Q_before": q_before, "Q_after": q_after,
                   "defects": man["defects"]}
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "repair_%s_f%02d.json" % (vdir, int(round(100 * FRAC))))
    json.dump(r, open(path, "w"), indent=1)
    print("SAVED " + path, flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
