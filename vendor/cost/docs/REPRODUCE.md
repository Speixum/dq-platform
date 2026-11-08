# Reproduction

## Environment actually used

| item | value |
|---|---|
| Python | 3.11.9 |
| torch / torchvision | 2.7.1+cu118 / 0.22.1+cu118 |
| GPU | RTX 3050 Laptop, 4.09 GB |
| peak memory per run | 1.67 GB (batch 64) |
| numpy / pandas / Pillow / scikit-learn / scipy / matplotlib | 2.4.4 / 3.0.1 / 12.0.0 / 1.8.0 / 1.17.1 / 3.10.8 |

CUDA is optional: the code falls back to CPU, but the 30 main runs then take hours instead of
about 3 hours total on the laptop GPU.

## Order of operations

```bash
# 0. data: see docs/DATASETS.md  -> data/neu-cls/  (flat, 1,800 bmp files)

# 1. split (already included, deterministic: seed 42, stratified 70/15/15)
python src/common.py            # rewrites data/splits/split_seed42.json if missing

# 2. materialise the 26 versions (~3 min, ~1.7 GB on disk; source images are only read)
python src/build_versions.py    # also writes results/versions/catalog.csv

# 3. train one model per version (30 runs; identical budget)
python src/run_versions.py      # skips versions whose json already exists -> resumable

# 4. scores
python src/q_v2.py              # reference network (trained on clean split) + RMA per version
python src/analyze_versions.py  # catalog + correlations
python src/analyze_warning.py   # gate: threshold sweep, precision / recall
python src/make_results.py      # Table 1/2, Spearman blocks, figures 4-7

# 5. repair loop (one extra training run)
python src/repair.py V04_gaussian_noise_L4
python src/fig_repair.py

# 6. second dataset and backbone checks (optional, GPU)
python src/fetch_ksdd2.py       # ~45-60 min, 853 MB
python src/ksdd2_study.py       # 9 conditions x ~5 min
python src/ksdd2_rank.py
python src/second_model.py      # 6 conditions with MobileNetV3-small

# 7. figures for the paper
python src/export_stats_figs.py # 26 per-version cards + 6 summary figures
python src/fig_gate.py
python src/fig_crossmodel.py

# 8. audit: every number in the manuscript against results/
python src/verify_paper_numbers.py   # must print "mismatches: 0"
```

## Expected headline numbers

| check | expected |
|---|---|
| split | 1,260 / 270 / 270 (210/45/45 per class) |
| clean test accuracy | 99.63% |
| versions trained | 26 + 5 second seeds + 6 other-backbone + 9 KSDD2 + 2 repair |
| Spearman(Q1, acc), n = 26 | -0.011 |
| Spearman(RMA, acc), n = 26 | 0.825 |
| gate F1 (RMA) | 0.97 |
| repair 20% | 32.22% -> 99.63% |

Exact per-version numbers are in `results/versions/table_final.csv` and
`results/versions/q2_table.csv`; the raw per-run files are `results/versions/run_*.json`.

## Determinism notes

- The split is fixed once and reused; every version differs only in the training data.
- Injections are computed in memory from the read-only source directory; nothing writes back.
- Seeds: single-axis versions use seed 0; the cumulative series (V21-V25) and the clean
  baseline use two and three seeds respectively. This is stated in the paper.
- A 270-image test set implies about +-0.6 pp of sampling uncertainty; effects below one point
  are read as "not measurable", not as zero.
