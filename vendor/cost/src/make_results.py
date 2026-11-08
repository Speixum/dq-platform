"""Final result tables and figures for the dataset-version study.

Reads only: results/versions/catalog.csv (manifest-derived Q1/LC/BAL/SHP),
results/versions/q2.json (reference-model agreement RMA), results/versions/run_*.json
(measured accuracy). Writes tables, stats and four figures under paper/figs/.

Run: python src/make_results.py
"""
import csv, glob, json, os, sys
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import spearmanr, kendalltau
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE = ROOT
RES = os.path.join(BASE, "results", "versions")
FIGS = os.path.join(BASE, "paper", "figs")
os.makedirs(FIGS, exist_ok=True)

FAM_COLOR = {"gaussian_noise": "#1f78b4", "salt_pepper": "#33a02c", "jpeg_compression": "#ff7f00",
             "motion_blur": "#e31a1c", "label_confusion": "#6a3d9a", "cumulative": "#111111",
             "clean": "#4d4d4d"}
FAM_LABEL = {"gaussian_noise": "Gaussian noise", "salt_pepper": "Salt-and-pepper",
             "jpeg_compression": "JPEG compression", "motion_blur": "Motion blur",
             "label_confusion": "Label confusion", "cumulative": "Cumulative", "clean": "Clean"}
CUM = ["V21", "V22", "V23", "V24", "V25"]


def family_of(label):
    if label == "clean":
        return "clean"
    if label.startswith("cumulative"):
        return "cumulative"
    return label.rsplit("_L", 1)[0]


def level_of(label):
    if label == "clean":
        return 0
    if label.startswith("cumulative"):
        return int(label.split("_")[1][0])
    return int(label.rsplit("_L", 1)[1])


def load():
    rows = {r["version"]: r for r in csv.DictReader(open(os.path.join(RES, "catalog.csv")))}
    accs = {}
    for p in sorted(glob.glob(os.path.join(RES, "run_V*.json"))):
        d = json.load(open(p))
        raw = d.get("version") or "_".join(os.path.basename(p).split("_")[1:])
        vid = raw.split("_")[0]
        accs.setdefault(vid, []).append(float(d["test_acc"]))
    q2 = json.load(open(os.path.join(RES, "q2.json")))
    out = []
    for vid in sorted(rows):
        r = rows[vid]
        a = accs.get(vid, [])
        q = q2.get(vid, {})
        out.append({
            "version": vid, "label": r["label"], "defects": r["defects"],
            "family": family_of(r["label"]), "level": level_of(r["label"]),
            "n_train": int(r["n_train"]),
            "Q1": float(r["Q"]), "LC": float(r["LC"]), "BAL": float(r["BAL"]), "SHP": float(r["SHP"]),
            "RMA": q.get("RMA"), "conf": q.get("confidence"),
            "acc": float(np.mean(a)) if a else None,
            "acc_sd": float(np.std(a, ddof=1)) if len(a) > 1 else 0.0,
            "n_seeds": len(a),
        })
    return out


def spearman_block(rows, key):
    sel = [r for r in rows if r[key] is not None and r["acc"] is not None]
    if len(sel) < 4:
        return None
    x = np.array([r[key] for r in sel]); y = np.array([r["acc"] for r in sel])
    rho, p = spearmanr(x, y)
    tau, _ = kendalltau(x, y)
    rng = np.random.default_rng(0)
    boot = []
    for _ in range(2000):
        i = rng.integers(0, len(sel), len(sel))
        if len(np.unique(x[i])) < 3:
            continue
        boot.append(spearmanr(x[i], y[i])[0])
    lo, hi = (np.percentile(boot, [2.5, 97.5]) if boot else (np.nan, np.nan))
    return {"rho": round(float(rho), 4), "p": float(p), "kendall": round(float(tau), 4),
            "n": len(sel), "boot95": [round(float(lo), 4), round(float(hi), 4)]}


def main():
    rows = load()
    done = [r for r in rows if r["acc"] is not None]
    clean = next(r for r in done if r["version"] == "V00")
    for r in done:
        r["drop_pp"] = 100 * (clean["acc"] - r["acc"])

    # ---------------- table ----------------
    cols = ["version", "label", "defects", "n_train", "Q1", "LC", "BAL", "SHP", "RMA", "conf",
            "acc_pct", "acc_sd_pp", "n_seeds", "drop_pp"]
    with open(os.path.join(RES, "table_final.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(cols)
        for r in done:
            w.writerow([r["version"], r["label"], r["defects"], r["n_train"],
                        "%.4f" % r["Q1"], "%.4f" % r["LC"], "%.4f" % r["BAL"], "%.4f" % r["SHP"],
                        "%.4f" % r["RMA"] if r["RMA"] is not None else "",
                        "%.4f" % r["conf"] if r["conf"] is not None else "",
                        "%.2f" % (100 * r["acc"]), "%.2f" % (100 * r["acc_sd"]), r["n_seeds"],
                        "%.2f" % r["drop_pp"]])
    lines = ["| Version | Corruption | n_train | Q1 (fidelity) | RMA (agreement) | Test acc (%) | Drop (pp) |",
             "|---|---|---|---|---|---|---|"]
    for r in done:
        sd = (" +- %.2f" % (100 * r["acc_sd"])) if r["n_seeds"] > 1 else ""
        lines.append("| %s | %s | %d | %.3f | %.3f | %.2f%s | %.2f |" % (
            r["version"], r["defects"], r["n_train"], r["Q1"], r["RMA"] or 0,
            100 * r["acc"], sd, r["drop_pp"]))
    open(os.path.join(RES, "table_final.md"), "w").write("\n".join(lines) + "\n")

    # ---------------- stats ----------------
    stats = {"n_versions": len(done)}
    for key in ("Q1", "RMA", "LC", "BAL", "SHP", "conf"):
        b = spearman_block(done, key)
        if b: stats[key] = b
    stats["RMAxLC"] = spearman_block([dict(r, RMAxLC=(r["RMA"] or 0) * r["LC"]) for r in done], "RMAxLC")
    stats["subsets"] = {
        "single_axis": spearman_block([r for r in done if r["family"] != "cumulative"], "RMA"),
        "cumulative_only": spearman_block([r for r in done if r["family"] == "cumulative"], "RMA"),
        "no_blur": spearman_block([r for r in done if r["family"] != "motion_blur"], "RMA"),
        "no_label_confusion": spearman_block([r for r in done if r["family"] != "label_confusion"], "RMA"),
    }
    lofo = {}
    for fam in ("gaussian_noise", "salt_pepper", "jpeg_compression", "motion_blur", "label_confusion"):
        b = spearman_block([r for r in done if r["family"] != fam], "RMA")
        if b: lofo[fam] = b
    stats["leave_one_family_out_RMA"] = lofo
    stats["within_family"] = {}
    for fam in ("gaussian_noise", "salt_pepper", "jpeg_compression", "motion_blur", "label_confusion"):
        vals = sorted([r for r in done if r["family"] == fam], key=lambda r: r["level"])
        if len(vals) >= 3:
            rho, p = spearmanr([r["RMA"] for r in vals], [r["acc"] for r in vals])
            stats["within_family"][fam] = {"rho": round(float(rho), 3), "p": float(p),
                                           "accs": [round(100 * r["acc"], 2) for r in vals],
                                           "RMAs": [round(r["RMA"], 3) for r in vals]}
    json.dump(stats, open(os.path.join(RES, "stats_final.json"), "w"), indent=1)
    print(json.dumps({k: stats[k] for k in ("Q1", "RMA", "LC", "RMAxLC") if k in stats}, indent=1))
    print("single-axis RMA:", stats["subsets"]["single_axis"])

    # ---------------- fig4: two panels ----------------
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True)
    for ax, key, title in ((axes[0], "Q1", "Fidelity score  Q1 = LC x BAL x SHP"),
                           (axes[1], "RMA", "Reference-model agreement  RMA")):
        for fam in ("gaussian_noise", "salt_pepper", "jpeg_compression", "motion_blur",
                    "label_confusion", "cumulative"):
            pts = [r for r in done if r["family"] == fam and r[key] is not None]
            if not pts: continue
            ax.scatter([r[key] for r in pts], [100 * r["acc"] for r in pts], s=46,
                       color=FAM_COLOR[fam], edgecolor="black", linewidth=0.5,
                       label=FAM_LABEL[fam], zorder=3)
        b = stats[key]
        ax.set_xlabel(title, fontsize=9)
        ax.set_title("%s vs accuracy:  rho = %.3f  (p = %.1e, n = %d)" % (
            key, b["rho"], b["p"], b["n"]), fontsize=10)
        ax.grid(alpha=0.25, linewidth=0.5)
    axes[0].set_ylabel("Test accuracy (%)")
    axes[0].axhline(100 * clean["acc"], ls=":", color="gray", linewidth=1)
    axes[1].legend(fontsize=8, loc="lower right", frameon=False)
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig4_score_vs_accuracy.png"), dpi=300); plt.close(fig)

    # ---------------- fig5: family curves ----------------
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    for fam in ("gaussian_noise", "salt_pepper", "jpeg_compression", "motion_blur", "label_confusion"):
        vals = sorted([r for r in done if r["family"] == fam], key=lambda r: r["level"])
        ax.plot([r["level"] for r in vals], [100 * r["acc"] for r in vals], "-o",
                color=FAM_COLOR[fam], label=FAM_LABEL[fam], markersize=6)
    ax.axhline(100 * clean["acc"], ls="--", color="gray", linewidth=1, label="clean (%.2f%%)" % (100 * clean["acc"]))
    ax.set_xlabel("Defect severity level"); ax.set_ylabel("Test accuracy (%)")
    ax.set_xticks([1, 2, 3, 4]); ax.grid(alpha=0.25, linewidth=0.5)
    ax.legend(fontsize=8, frameon=False); fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig5_family_curves.png"), dpi=300); plt.close(fig)

    # ---------------- fig6: cumulative ----------------
    cum = sorted([r for r in done if r["family"] == "cumulative"], key=lambda r: r["level"])
    xs = [0] + [r["level"] for r in cum]
    accs = [100 * clean["acc"]] + [100 * r["acc"] for r in cum]
    rmas = [100 * clean["RMA"]] + [100 * r["RMA"] for r in cum]
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.plot(xs, accs, "-o", color="#e31a1c", label="measured accuracy")
    ax.plot(xs, rmas, "--s", color="#1f78b4", label="RMA x 100")
    for x, y in zip(xs, accs):
        ax.annotate("%.1f" % y, (x, y), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8)
    ax.set_xlabel("Number of stacked defect types (clean = 0)")
    ax.set_ylabel("Percent"); ax.set_xticks(xs)
    ax.grid(alpha=0.25, linewidth=0.5); ax.legend(fontsize=9, frameon=False)
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig6_cumulative.png"), dpi=300); plt.close(fig)

    # ---------------- fig7: drop bars ----------------
    fams = ["gaussian_noise", "salt_pepper", "jpeg_compression", "motion_blur", "label_confusion"]
    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    width = 0.2
    for i, fam in enumerate(fams):
        vals = sorted([r for r in done if r["family"] == fam], key=lambda r: r["level"])
        xs = np.arange(4) + (i - 2) * width
        ax.bar(xs, [r["drop_pp"] for r in vals], width=width, color=FAM_COLOR[fam],
               edgecolor="black", linewidth=0.4, label=FAM_LABEL[fam])
    ax.set_xticks(np.arange(4)); ax.set_xticklabels(["L1", "L2", "L3", "L4"])
    ax.set_ylabel("Accuracy drop vs clean (pp)"); ax.grid(axis="y", alpha=0.25, linewidth=0.5)
    ax.legend(fontsize=8, frameon=False); fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig7_drop_bars.png"), dpi=300); plt.close(fig)
    print("wrote tables, stats and 4 figures")


if __name__ == "__main__":
    main()
