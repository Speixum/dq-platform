# -*- coding: utf-8 -*-
"""统计 Labelme 标注里每个缺陷类别的样本量，输出类别分布。

用法:
    python tools/class_stats.py
    python tools/class_stats.py --json-dir <目录>
"""
import argparse
import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402


def iter_json(json_dir):
    return sorted(glob.glob(os.path.join(json_dir, "*.json")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-dir", default=config.LABELME_DIR)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    files = iter_json(args.json_dir)
    if not files:
        print("[ERROR] 目录里没有 json: %s" % args.json_dir)
        return 1

    counter = collections.Counter()   # 每个类别的多边形个数
    img_of_class = collections.defaultdict(set)  # 每个类别出现在多少张图上
    no_label = 0
    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        shapes = data.get("shapes") or []
        if not shapes:
            no_label += 1
            continue
        for sh in shapes:
            label = (sh.get("label") or "").strip()
            counter[label] += 1
            img_of_class[label].add(os.path.basename(fp))

    total_shapes = sum(counter.values())
    print("标注文件数        : %d" % len(files))
    print("空标注文件数      : %d" % no_label)
    print("多边形总数        : %d" % total_shapes)
    print("类别数            : %d" % len(counter))
    print("")
    print("%-18s %8s %10s %8s" % ("类别", "多边形数", "覆盖图片数", "占比"))
    print("-" * 48)
    for label, n in counter.most_common(args.top):
        print("%-18s %8d %10d %7.1f%%" % (label, n, len(img_of_class[label]), 100.0 * n / total_shapes))

    if len(counter) > 1:
        big = counter.most_common(1)[0][1]
        small = counter.most_common()[-1][1]
        print("")
        print("最大/最小类样本比 : %.1f : 1  (类别不平衡程度)" % (big / max(small, 1)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
