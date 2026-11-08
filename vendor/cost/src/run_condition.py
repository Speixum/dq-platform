
"""Run one experimental condition: inject -> train -> test -> quality features."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (make_split, train_one, class_counts, RESULTS_DIR, PREFIX_TO_IDX, BATCH)
from inject import build_condition
from quality import quality_features, embed_cached, sharpness, PREFIXES

EPOCHS = 6
MAIN_DIR = os.path.join(RESULTS_DIR, "main")


def labels_array(files, labels_dict):
    return [labels_dict[f] if labels_dict and f in labels_dict else PREFIX_TO_IDX[f.split("_")[0]]
            for f in files]


def run(kind, severity, seed, epochs=EPOCHS, split_seed=42):
    sp = make_split(seed=split_seed)
    used, lab, imgs, meta = build_condition(kind, severity, sp["train"], seed=seed)
    # build_condition returns a SPARSE override dict; the dataset needs a full label map
    lab_full = {f: (lab[f] if lab and f in lab else PREFIX_TO_IDX[f.split("_")[0]]) for f in used}
    tag = "clean" if kind == "clean" else (kind + "_" + severity)
    print("CONDITION " + json.dumps({**meta, "seed": seed, "epochs": epochs}), flush=True)
    r = train_one(used, sp["val"], seed=seed, epochs=epochs, tag=tag,
                  test_files=sp["test"], images_train=imgs, labels_train=lab_full,
                  log_extra={"condition": meta, "n_train_used": len(used)})

    # ---- training-free quality features of the *training* set as delivered ----
    emb = embed_cached(used)
    ref = json.load(open(os.path.join(RESULTS_DIR, "_ref_sharpness.json")))["clean_train"]
    y = labels_array(used, lab_full)
    q = quality_features(used, y, images=imgs, ref_sharpness=ref, emb=emb)
    r["quality"] = q
    r["n_train_used"] = len(used)

    os.makedirs(MAIN_DIR, exist_ok=True)
    path = os.path.join(MAIN_DIR, "run_" + tag + "_s" + str(seed) + ".json")
    json.dump(r, open(path, "w"), indent=1)
    print("SAVED " + path, flush=True)
    print("RESULT " + json.dumps({"tag": tag, "seed": seed, "test_acc": r["test_acc"],
                                  "q": q["Q"], "LC": q["LC"], "BAL": q["BAL"], "SHP": q["SHP"],
                                  "n": q["n"], "IR": q["imbalance_ratio"]}), flush=True)
    return r


if __name__ == "__main__":
    kind, sev, seed = sys.argv[1], sys.argv[2], int(sys.argv[3])
    run(kind, sev, seed)
