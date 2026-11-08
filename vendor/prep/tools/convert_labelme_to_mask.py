# -*- coding: utf-8 -*-
"""把 Labelme 多边形标注（json）转成像素级分割掩码（0/255 二值 PNG）。

两种模式:
  1) 保留原类别：--keep-classes   每个类别一个目录一张掩码
  2) 合并成单类（本项目采用）：默认行为，所有缺陷多边形合并成 1 类 defect

合并理由：原始 7 类里 Crack / Nick / Tip curl 样本量过低，单独成类学不动，
还会拉低整体指标；合并成"有缺陷/无缺陷"后可用于二分类分割。

用法:
    python tools/convert_labelme_to_mask.py --limit 20      # 先试 20 张
    python tools/convert_labelme_to_mask.py                # 全量
"""
import argparse
import glob
import json
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402


def shape_to_points(shape):
    """Labelme 的 shape 支持 polygon / rectangle / circle，这里只处理 polygon 和 rectangle。"""
    pts = shape.get("points") or []
    if not pts:
        return []
    st = (shape.get("shape_type") or "polygon").lower()
    if st == "rectangle" and len(pts) >= 2:
        (x1, y1), (x2, y2) = pts[0], pts[1]
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    return [(float(p[0]), float(p[1])) for p in pts]


def json_to_mask(json_path, keep_classes=False):
    with open(json_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    w, h = int(d["imageWidth"]), int(d["imageHeight"])
    masks = {}
    for sh in d.get("shapes") or []:
        pts = shape_to_points(sh)
        if len(pts) < 3:
            continue
        label = (sh.get("label") or "unknown").strip()
        key = label if keep_classes else config.MERGED_CLASS_NAME
        if key not in masks:
            masks[key] = Image.new("L", (w, h), 0)
        ImageDraw.Draw(masks[key]).polygon(pts, fill=255)
    return masks, w, h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-dir", default=config.LABELME_DIR)
    ap.add_argument("--out-dir", default=os.path.join(config.DATA587_DIR, "masks_from_json"))
    ap.add_argument("--keep-classes", action="store_true", help="保留原始类别，不合并")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 张，0 = 全量")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.json_dir, "*.json")))
    if args.limit:
        files = files[: args.limit]

    ok, empty, bad = 0, 0, 0
    for fp in files:
        try:
            masks, w, h = json_to_mask(fp, args.keep_classes)
        except Exception as e:              # 坏 json 单独计数，不中断整批
            bad += 1
            print("[WARN] 解析失败 %s: %s" % (os.path.basename(fp), e))
            continue
        if not masks:
            empty += 1                  # 有 json 但没有有效多边形
            continue
        stem = os.path.splitext(os.path.basename(fp))[0]
        for label, img in masks.items():
            out_dir = os.path.join(args.out_dir, label) if args.keep_classes else args.out_dir
            os.makedirs(out_dir, exist_ok=True)
            img.save(os.path.join(out_dir, stem + ".png"))
        ok += 1

    print("处理 json 总数    : %d" % len(files))
    print("成功转出掩码      : %d" % ok)
    print("无有效多边形      : %d" % empty)
    print("解析失败          : %d" % bad)
    print("输出目录          : %s" % args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
