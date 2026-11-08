"""Build all dataset versions and compute their training-free quality score Q.

Run:  python src/build_versions.py
Outputs: data/versions/V**/...  and  results/versions/catalog.csv
"""
import json, os, sys, time
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image

from versions import (VERSIONS_DIR, version_plan, build_version, FAMILIES, SPLIT_PATH,
                      PREFIXES, NAMES, DATA_DIR)
from quality import quality_features, embed
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CATALOG = os.path.join(ROOT, "results", "versions", "catalog.csv")
REF_SHARPNESS = os.path.join(ROOT, "results", "_ref_sharpness.json")


def load_split():
    return json.load(open(SPLIT_PATH))


def version_train(vid_label):
    root = os.path.join(VERSIONS_DIR, vid_label)
    rows = open(os.path.join(root, "labels.csv")).read().strip().split("\n")[1:]
    files, labels = [], []
    for r in rows:
        f, sub, y, _ = r.split(",")
        if sub == "train":
            files.append(f); labels.append(int(y))
    imgs = {}
    img_dir = os.path.join(root, "images", "train")
    for f in files:
        stem = f.rsplit(".", 1)[0]
        cand = [os.path.join(img_dir, stem + e) for e in (".bmp", ".jpg")]
        p = next(c for c in cand if os.path.exists(c))
        imgs[f] = Image.open(p).convert("L")
    return files, labels, imgs


def main():
    os.makedirs(os.path.dirname(CATALOG), exist_ok=True)
    split = load_split()
    ref = json.load(open(REF_SHARPNESS))["clean_train"]
    plan = [("V00", "clean", [])] + version_plan()

    rows = []
    t_all = time.time()
    for vid, label, defects in plan:
        t0 = time.time()
        vid_label = vid + "_" + label
        man = build_version(vid, label, defects, split)
        files, labels, imgs = version_train(vid_label)
        emb = embed(files, images=imgs)
        q = quality_features(files, labels, images=imgs, ref_sharpness=ref, emb=emb)

        man.update({"Q": q["Q"], "LC": q["LC"], "BAL": q["BAL"], "SHP": q["SHP"],
                    "SHP_raw": q["SHP_raw"], "class_counts": q["counts"],
                    "imbalance_ratio": q["imbalance_ratio"]})
        json.dump(man, open(os.path.join(VERSIONS_DIR, vid_label, "manifest.json"), "w"), indent=1)

        params = "; ".join("%s=%g" % (d["family"], d["value"]) for d in man["defects"]) or "-"
        rows.append({"version": vid, "label": label,
                     "defects": params,
                     "n_families": man["n_defect_families"],
                     "n_train": man["n_train"],
                     "Q": q["Q"], "LC": q["LC"], "BAL": q["BAL"], "SHP": q["SHP"]})
        print("%s %-28s Q=%.4f LC=%.4f BAL=%.4f SHP=%.4f  (%.0fs)" %
              (vid, label, q["Q"], q["LC"], q["BAL"], q["SHP"], time.time() - t0), flush=True)

    with open(CATALOG, "w") as fh:
        fh.write("version,label,defects,n_families,n_train,Q,LC,BAL,SHP,test_acc,test_acc_sd,n_seeds\n")
        for r in rows:
            fh.write("%s,%s,%s,%d,%d,%.4f,%.4f,%.4f,%.4f,,,\n" %
                     (r["version"], r["label"], r["defects"], r["n_families"], r["n_train"],
                      r["Q"], r["LC"], r["BAL"], r["SHP"]))
    print("CATALOG " + CATALOG, flush=True)
    print("total %.1f min" % ((time.time() - t_all) / 60), flush=True)


if __name__ == "__main__":
    main()
