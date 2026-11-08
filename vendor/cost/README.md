# Quantifying the Cost of Dirty Data

**How much accuracy does a dirty dataset cost — and can we predict it without training?**

This project builds **26 versions** of one industrial image dataset, each carrying a known
defect at a known strength, trains one identical ResNet-18 per version, and measures what the
defect actually costs. It then asks whether a **training-free quality score** can rank those
versions the same way the measured accuracy does.

The model is only a ruler. The object of study is the data.

---

## Headline results

| Question | Answer |
|---|---|
| Clean reference (NEU-CLS) | **99.63%** test accuracy |
| Most expensive defect | Gaussian noise, σ = 32 → **−67.41 pp** |
| Cheapest defect | 15% systematic label confusion → **−1.11 pp** |
| Are stacked defects additive? | **No.** Adding blur + compression to a noisy version *raises* accuracy 46.85% → 78.33%, because those operations erase the high-frequency noise injected first |
| Does a fidelity score (LC × BAL × SHP) work? | **No.** Spearman ρ = −0.011 against accuracy |
| Does reference-model agreement (RMA) work? | **Yes.** Spearman ρ = **0.825**, p = 2.1e-7, n = 26 |
| Can RMA work as a screening gate? | precision **1.00**, recall **0.94** at a −5 pp threshold |
| Does acting on the score help? | Replacing the worst-scored 20% of training files lifts the worst version 32.22% → **99.63%** |
| Does the cost table transfer to another dataset? | **No.** The same corruptions cost ≤ 2.29 pp on KolektorSDD2 — cost must be measured per dataset |

## What it looks like

**Cost depends far more on defect type than on defect strength**

![Accuracy vs defect severity](figs/fig5_family_curves.png)

**Accuracy drop per family and level (pp vs clean)**

![Accuracy drop](figs/fig7_drop_bars.png)

**A training-free score that ranks versions like the measured accuracy does**

![Score vs accuracy](figs/fig4_q_vs_acc.png)

**The score also tracks the repair**

![Repair](figs/fig10_repair.png)

---

## How it works

1. **One fixed split.** NEU-CLS (6 classes × 300 hot-rolled steel surface images), stratified
   70/15/15 with seed 42 — 1260 / 270 / 270. Every version reuses this split, so no version
   can win by getting an easier test set.
2. **Injection is deterministic and versioned.** Each version keeps its images, label file,
   `manifest.json` and `problems.md`; the catalogue indexes all 26.
3. **One identical training budget.** ResNet-18 (ImageNet), 224×224, batch 64, AdamW
   (lr 3e-4, wd 1e-4), cosine, 6 epochs, no augmentation, checkpoint chosen on validation,
   test evaluated once. Differences are therefore attributable to the defect, not to
   optimisation luck.
4. **Scoring without training.** LC = label consistency of k-NN in ImageNet embeddings;
   BAL = class-balance entropy; SHP = sharpness relative to a clean reference. RMA =
   agreement between a clean reference network's predictions and the delivered labels.
5. **Verification.** Rank correlations, a gate analysis, a repair loop, a second dataset and a
   second backbone, plus `src/verify_paper_numbers.py` which re-derives every reported number
   from the result files.

## Reproduce

```bash
pip install -r requirements.txt
# put NEU-CLS images in data/neu-cls/ (or set NEU_DATA_DIR; see docs/DATASETS.md)
python src/build_versions.py         # ~3 min, writes data/versions/
python src/run_versions.py           # 30 runs, ~5.5 min each on a 4 GB laptop GPU
python src/q_v2.py                   # reference model + one forward pass per version
python src/make_results.py           # tables, rank correlations, figures
python src/verify_paper_numbers.py   # cross-check reported numbers against results/
```

## Repository layout

```
src/                     experiment code (build versions, train, score, analyse, plot)
data/splits/             fixed stratified 70/15/15 split (seed 42)
data/versions/Vxx/       per-version metadata: manifest.json, labels.csv, problems.md
results/versions/        one JSON per training run (accuracy, scores, timing)
results/ksdd2/           second-dataset runs
figs/                    result figures
docs/                    datasets, reproduction notes, findings
```

**Dataset images are not redistributed here.** NEU-CLS and KolektorSDD2 carry their own
terms; see [docs/DATASETS.md](docs/DATASETS.md) for links and expected layout. What is
included is everything this project produced: the split, per-version label files, manifests
and all result files, so every number can be re-derived.

## Licence

Code MIT (`LICENSE`); result files, manifests and label files CC BY 4.0. The two benchmark
datasets remain under their original licences.

## Citation

```
@misc{dirty-data-cost-2026,
  title  = {Quantifying the Cost of Dirty Data: A Controlled Study of Dataset Defects on
            Surface-Defect Classification},
  author = {dirty-data-cost contributors},
  year   = {2026},
  url    = {https://github.com/Speixum/dirty-data-cost}
}
```

If you use the datasets, cite the originals: Song & Yan (2013) for NEU-CLS; Bozic, Tabernik &
Skocaj (2021) for KolektorSDD2.
