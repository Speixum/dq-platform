# -*- coding: utf-8 -*-
"""统计原始图像分辨率分布。

为什么做这一步：原始图有好几种分辨率，送进网络前必须统一缩放到 512x512，
否则同一批数据尺寸不一致。先统计清楚，再决定缩放策略。
"""
import argparse
import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-dir", default=config.LABELME_DIR)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.json_dir, "*.json")))
    counter = collections.Counter()
    missing = 0
    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            d = json.load(f)
        w, h = d.get("imageWidth"), d.get("imageHeight")
        if not w or not h:
            missing += 1
            continue
        counter[(int(w), int(h))] += 1

    total = sum(counter.values())
    print("统计标注文件      : %d（缺尺寸 %d）" % (len(files), missing))
    print("")
    print("%-14s %8s %8s" % ("分辨率", "图片数", "占比"))
    print("-" * 34)
    for (w, h), n in counter.most_common():
        print("%-14s %8d %7.1f%%" % ("%dx%d" % (w, h), n, 100.0 * n / max(total, 1)))
    print("")
    print("不同分辨率种数    : %d" % len(counter))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
