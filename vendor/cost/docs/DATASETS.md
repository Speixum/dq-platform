# Datasets

Neither dataset is redistributed in this repository. Both are public benchmarks used under
their own research-use terms; only derived artifacts (splits, label files, manifests, results)
are included here.

## Telling the code where your data lives

Nothing is hard-coded to one machine. Two environment variables are all you need:

| variable | default | what it points at |
|---|---|---|
| `NEU_DATA_DIR` | `<repo>/data/neu-cls` | the folder holding the flat `.bmp` files of NEU-CLS |
| `KSDD2_DIR` | `<repo>/data/external/ksdd2` | the extracted `KolektorSDD2/` folder (only for section 7.8) |

Either drop the data into the default location, or export the variable first:

```bash
export NEU_DATA_DIR="/path/to/your/neu-cls"      # Windows: set NEU_DATA_DIR=<path-to-neu-cls>
python src/build_versions.py
```

If the folder is missing, `src/common.py` stops with a message saying which path it looked at
instead of failing later with a confusing `FileNotFoundError`.

## NEU-CLS (main dataset)

- **What**: hot-rolled steel strip surface defects, 6 classes x 300 images = 1,800 images.
- **Format**: 8-bit grayscale BMP, 200 x 200 px, stored **flat** (no class folders).
- **Class encoding**: filename prefix -> class

  | prefix | class | index |
  |---|---|---|
  | `Cr_` | crazing | 0 |
  | `In_` | inclusion | 1 |
  | `Pa_` | patches | 2 |
  | `PS_` | pitted surface | 3 |
  | `RS_` | rolled-in scale | 4 |
  | `Sc_` | scratches | 5 |

  (`Thumbs.db` in the directory is ignored.)
- **Source**: the page of the original authors (Northeastern University, K. Song):
  <https://faculty.neu.edu.cn/songkechen/zh_CN/zdylm/263270/list/> — use the **classification**
  release (NEU-CLS), not the detection release with XML boxes (NEU-DET).
- **Cite**: K. Song and Y. Yan, "A noise robust method based on completed local binary patterns
  for hot-rolled steel strip surface defects," *Applied Surface Science*, 285:858-864, 2013.
- **Place it at**: `data/neu-cls/` (flat), i.e. `data/neu-cls/Cr_1.bmp` etc.

Observed when we downloaded it: 1,800 files, all mode "L", all 200x200, none corrupt.

## KolektorSDD2 (second dataset)

- **What**: defect / no-defect images of production items, binary task with pixel masks.
  3,336 images (2,332 train + 1,004 test) plus `_GT` masks; ~229 x 645 px.
- **Source**: <https://www.vicos.si/resources/kolektorsdd2/> (direct archive:
  `https://data.vicos.si/datasets/KSDD/KolektorSDD2.zip`, 853,126,555 bytes).
- **Licence**: CC BY-NC-SA 4.0 — non-commercial; contact the authors for commercial use.
- **Cite**: J. Bozic, D. Tabernik, D. Skocaj, "Mixed supervision for surface-defect detection:
  from weakly to fully supervised learning," *Computers in Industry*, 2021.
- **Place it at**: `data/external/ksdd2/` with `train/` and `test/` subfolders.
  `src/fetch_ksdd2.py` downloads it with 16 parallel range requests (single-connection speed
  from that host was ~55 KB/s, 16 connections reached ~300 KB/s).
- **Note**: one train image (`10301 (copy).png`) has no matching `_GT.png`; the loader skips
  such files. Labels are derived as `mask.max() > 0`.

## Why the images are not bundled

Redistribution is a different right from use. Publishing measurements computed on a benchmark
is fine; re-hosting the benchmark's images is not, and would also break the licence terms of
KSDD2 (non-commercial, share-alike). Anyone can obtain both datasets from the links above and
reproduce every number with the code in this repository.
