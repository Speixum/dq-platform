
import json, os, sys, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

if __name__ == "__main__":
    seed_split = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    epochs = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    sp = make_split(seed=seed_split)
    print("SPLIT", json.dumps({"seed": sp["seed"], "counts": sp["counts"]}))
    print("train per class", class_counts(sp["train"]))
    print("val   per class", class_counts(sp["val"]))
    print("test  per class", class_counts(sp["test"]))
    runs = []
    for seed in (0, 1, 2):
        print("=== CLEAN BASELINE seed=%d ===" % seed, flush=True)
        r = train_one(sp["train"], sp["val"], seed=seed, epochs=epochs,
                      tag="clean_baseline", test_files=sp["test"],
                      log_extra={"split_seed": seed_split})
        runs.append(r)
        os.makedirs(RESULTS_DIR, exist_ok=True)
        json.dump(r, open(RESULTS_DIR + "/clean_baseline_seed" + str(seed) + ".json", "w"), indent=1)
    accs = [r["test_acc"] for r in runs]
    summary = {"n_runs": len(runs), "test_acc_all": accs,
               "mean": round(st.mean(accs), 5), "std": round(st.pstdev(accs), 5),
               "min": min(accs), "max": max(accs),
               "val_acc_all": [r["best_val_acc"] for r in runs],
               "best_epochs": [r["best_epoch"] for r in runs],
               "peak_vram_gb": [r["peak_vram_gb"] for r in runs],
               "train_time_s": [r["train_time_s"] for r in runs],
               "init": runs[0]["init"], "split": sp["counts"],
               "batch_size": runs[0]["batch_size"], "epochs": epochs}
    json.dump(summary, open(RESULTS_DIR + "/clean_baseline_summary.json", "w"), indent=1)
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
