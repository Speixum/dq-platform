"""Aggregate the per-version runs: tables, rank correlations, figures.

Reads only JSON produced by run_versions.py / build_versions.py.
Outputs:
  results/versions/table.csv, table.md
  results/versions/spearman.json
  paper/figs/fig4_q_vs_acc.png      (26 points, one per dataset version)
  paper/figs/fig5_family_curves.png (accuracy vs severity, one line per family)
  paper/figs/fig6_cumulative.png    (accuracy and Q vs number of stacked defects)
"""
import csv, json, os
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import spearmanr
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROOT = ROOT
REF_SHARP = 682.409   # mean Laplacian variance of the clean training split
RUNS = os.path.join(ROOT, "results", "versions")
CAT = os.path.join(RUNS, "catalog.csv")
FIGS = os.path.join(ROOT, "paper", "figs")

FAM_ORDER = ["gaussian_noise", "salt_pepper", "jpeg_compression", "motion_blur", "label_confusion"]
FAM_COLOR = {"gaussian_noise": "#1f78b4", "salt_pepper": "#33a02c",
             "jpeg_compression": "#ff7f00", "motion_blur": "#e31a1c",
             "label_confusion": "#6a3d9a"}
FAM_MARK = {"gaussian_noise": "o", "salt_pepper": "s", "jpeg_compression": "^",
            "motion_blur": "v", "label_confusion": "D"}


def load():
    cat = list(csv.DictReader(open(CAT)))
    runs = {}
    for f in sorted(os.listdir(RUNS)):
        if f.startswith("run_") and f.endswith(".json"):
            r = json.load(open(os.path.join(RUNS, f)))
            runs.setdefault(r["version"], []).append(r)
    rows = []
    for c in cat:
        v = c["version"] + "_" + c["label"]
        rs = runs.get(v, [])
        man = json.load(open(os.path.join(ROOT, "data", "versions", v, "manifest.json")))
        ratio = man.get("SHP_raw", 0.0) / REF_SHARP
        shp_sym = float(min(1.0, ratio, 1.0 / max(ratio, 1e-6)))
        accs = [r["test_acc"] for r in rs]
        rows.append({
            "version": c["version"], "label": c["label"], "defects": c["defects"],
            "n_families": int(c["n_families"]), "n_train": int(c["n_train"]),
            "Q": float(c["Q"]), "LC": float(c["LC"]), "BAL": float(c["BAL"]), "SHP": float(c["SHP"]),
            "SHP_raw": man.get("SHP_raw"), "SHP_sym": shp_sym,
            "Q_sym": float(c["LC"]) * float(c["BAL"]) * shp_sym,
            "acc": float(np.mean(accs)) if accs else None,
            "acc_sd": float(np.std(accs, ddof=1)) if len(accs) > 1 else 0.0,
            "n_seeds": len(accs),
            "peak_vram_gb": rs[0]["peak_vram_gb"] if rs else None,
            "train_time_s": rs[0]["train_time_s"] if rs else None,
        })
    return rows


def family_of(label):
    for f in FAM_ORDER:
        if label.startswith(f):
            return f
    return None


def main():
    rows = load()
    done = [r for r in rows if r["acc"] is not None]

    # ---------- table ----------
    with open(os.path.join(RUNS, "table.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["version", "label", "defects", "n_train", "Q", "LC", "BAL", "SHP",
                    "test_acc", "acc_sd", "n_seeds"])
        for r in rows:
            w.writerow([r["version"], r["label"], r["defects"], r["n_train"],
                        "%.4f" % r["Q"], "%.4f" % r["LC"], "%.4f" % r["BAL"], "%.4f" % r["SHP"],
                        "%.4f" % r["acc"] if r["acc"] is not None else "",
                        "%.4f" % r["acc_sd"], r["n_seeds"]])

    lines = ["| Version | Defects | n_train | Q | LC | SHP | Test acc (%) | n |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        acc = "%.2f" % (100 * r["acc"]) if r["acc"] is not None else "-"
        if r["acc"] is not None and r["n_seeds"] > 1:
            acc = "%.2f ± %.2f" % (100 * r["acc"], 100 * r["acc_sd"])
        lines.append("| %s %s | %s | %d | %.3f | %.3f | %.3f | %s | %d |" %
                     (r["version"], r["label"], r["defects"] or "-", r["n_train"],
                      r["Q"], r["LC"], r["SHP"], acc, r["n_seeds"]))
    open(os.path.join(RUNS, "table.md"), "w").write("\n".join(lines) + "\n")

    # ---------- rank correlations ----------
    acc = np.array([r["acc"] for r in done])
    res = {}
    scores = {"Q": [r["Q"] for r in done],
              "LC_only": [r["LC"] for r in done],
              "SHP_only": [r["SHP"] for r in done],
              "BAL_only": [r["BAL"] for r in done],
              "LCxSHP": [r["LC"] * r["SHP"] for r in done]}
    rng = np.random.default_rng(0)
    for k, v in scores.items():
        rho, p = spearmanr(v, acc)
        res[k] = {"rho": float(rho), "p": float(p), "n": len(done)}
    # random-score baseline: distribution of rho for a random permutation score
    null = np.sort(np.array([spearmanr(rng.random(len(acc)), acc)[0] for _ in range(2000)]))
    res["random_permutation_95pct"] = [float(np.percentile(null, 2.5)), float(np.percentile(null, 97.5))]
    # leave-one-family-out robustness of Q
    lofo = {}
    for fam in FAM_ORDER:
        sub = [(r["Q"], r["acc"]) for r in done if family_of(r["label"]) != fam]
        if len(sub) > 3:
            rho, p = spearmanr([s[0] for s in sub], [s[1] for s in sub])
            lofo[fam] = {"rho": float(rho), "p": float(p), "n": len(sub)}
    res["leave_one_family_out"] = lofo
    # within-family monotonicity
    mono = {}
    for fam in FAM_ORDER:
        vals = sorted([r for r in done if family_of(r["label"]) == fam], key=lambda r: r["version"])
        if len(vals) >= 3:
            rr = spearmanr([r["Q"] for r in vals], [r["acc"] for r in vals])
            mono[fam] = {"rho": float(rr[0]), "p": float(rr[1]),
                         "accs": [round(100 * r["acc"], 2) for r in vals],
                         "Qs": [r["Q"] for r in vals]}
    res["within_family"] = mono
    res["n_versions"] = len(done)
    json.dump(res, open(os.path.join(RUNS, "spearman.json"), "w"), indent=1)

    print(json.dumps({k: v for k, v in res.items() if k not in ("leave_one_family_out", "within_family")}, indent=1))
    print(json.dumps(res["within_family"], indent=1))

    # ---------- figures ----------
    os.makedirs(FIGS, exist_ok=True)
    plt.rcParams.update({"font.size": 10})

    # fig4: Q vs accuracy
    fig, ax = plt.subplots(figsize=(6.4, 4.8))
    for fam in FAM_ORDER:
        pts = [r for r in done if family_of(r["label"]) == fam]
        if not pts:
            continue
        ax.scatter([r["Q"] for r in pts], [100 * r["acc"] for r in pts],
                   s=46, c=FAM_COLOR[fam], marker=FAM_MARK[fam], edgecolors="black",
                   linewidths=0.5, label=fam.replace("_", " "), zorder=3)
    z = np.polyfit([r["Q"] for r in done], acc, 1)
    xs = np.linspace(min(r["Q"] for r in done), max(r["Q"] for r in done), 50)
    ax.plot(xs, 100 * np.polyval(z, xs), "--", color="black", linewidth=1.2, zorder=2)
    ax.set_xlabel("Training-free quality score  Q = LC x BAL x SHP")
    ax.set_ylabel("Test accuracy (%)")
    ax.set_title("Spearman rho = %.3f (n=%d, p = %.1e)" %
                 (res["Q"]["rho"], res["Q"]["n"], res["Q"]["p"]))
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    ax.grid(alpha=0.25)
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig4_q_vs_acc.png"), dpi=300); plt.close(fig)

    # fig5: per-family curves
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    for fam in FAM_ORDER:
        pts = sorted([r for r in done if family_of(r["label"]) == fam], key=lambda r: int(r["version"][1:]))
        if not pts:
            continue
        ax.plot(range(1, len(pts) + 1), [100 * r["acc"] for r in pts], "-" + FAM_MARK[fam],
                color=FAM_COLOR[fam], label=fam.replace("_", " "), markersize=6)
        ax.set_xticks(range(1, 5))
    ax.axhline(100 * done[0]["acc"], ls=":", color="grey", linewidth=1)
    ax.set_xlabel("Severity level (1 = mildest, 4 = strongest)")
    ax.set_ylabel("Test accuracy (%)")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig5_family_curves.png"), dpi=300); plt.close(fig)

    # fig6: cumulative
    cum = sorted([r for r in done if r["label"].startswith("cumulative")], key=lambda r: r["n_families"])
    base = [r for r in done if r["label"] == "clean"][0]
    fig, ax1 = plt.subplots(figsize=(6.4, 4.2))
    xs = [0] + [r["n_families"] for r in cum]
    ys = [100 * base["acc"]] + [100 * r["acc"] for r in cum]
    es = [100 * base["acc_sd"]] + [100 * r["acc_sd"] for r in cum]
    ax1.errorbar(xs, ys, yerr=es, fmt="-o", color="#e31a1c", capsize=3, label="test accuracy")
    ax1.set_xlabel("Number of stacked defect families (each at level 2 of 4)")
    ax1.set_ylabel("Test accuracy (%)", color="#e31a1c")
    ax1.tick_params(axis="y", labelcolor="#e31a1c")
    ax2 = ax1.twinx()
    ax2.plot(xs, [base["Q"]] + [r["Q"] for r in cum], "--s", color="#1f78b4", label="Q", markersize=5)
    ax2.set_ylabel("Training-free quality score Q", color="#1f78b4")
    ax2.tick_params(axis="y", labelcolor="#1f78b4")
    ax2.set_ylim(0, 1.05)
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig6_cumulative.png"), dpi=300); plt.close(fig)
    print("FIGURES written to " + FIGS)


if __name__ == "__main__":
    main()
