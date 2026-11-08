# -*- coding: utf-8 -*-
"""掩码与图像的一致性核验。

检查四件事：
  1. 图像数和掩码数是否对齐（有没有漏转 / 多转）
  2. 文件名是否一一对应
  3. 掩码尺寸和图像尺寸是否一致
  4. 空掩码比例（全是黑 = 这张图没有缺陷，通常是漏标或负样本）

用法:
    python tools/check_masks.py                    # 检查 data_587
    python tools/check_masks.py --split Test
"""
import argparse
import glob
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402


def stems(d, exts):
    out = {}
    for ext in exts:
        for p in glob.glob(os.path.join(d, "*" + ext)):
            out[os.path.splitext(os.path.basename(p))[0]] = p
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=config.DATA587_DIR)
    ap.add_argument("--split", default="Train", choices=["Train", "Test"])
    args = ap.parse_args()

    img_dir = os.path.join(args.root, args.split, "JPEGImages")
    msk_dir = os.path.join(args.root, args.split, "BlackWhite")
    imgs = stems(img_dir, [".jpg", ".jpeg", ".png", ".bmp"])
    msks = stems(msk_dir, [".png", ".jpg", ".bmp"])

    only_img = sorted(set(imgs) - set(msks))
    only_msk = sorted(set(msks) - set(imgs))

    print("== %s ==" % args.split)
    print("图像数            : %d" % len(imgs))
    print("掩码数            : %d" % len(msks))
    print("只有图没有掩码    : %d %s" % (len(only_img), only_img[:5]))
    print("只有掩码没有图    : %d %s" % (len(only_msk), only_msk[:5]))

    size_mismatch, empty, checked = 0, 0, 0
    for stem in sorted(set(imgs) & set(msks)):
        try:
            with Image.open(imgs[stem]) as im:
                isz = im.size
            with Image.open(msks[stem]) as mk:
                msz = mk.size
                hist = mk.convert("L").histogram()
        except Exception as e:
            print("[WARN] 读图失败 %s: %s" % (stem, e))
            continue
        checked += 1
        if isz != msz:
            size_mismatch += 1
        # 非零像素数为 0 => 空掩码
        if sum(hist[1:]) == 0:
            empty += 1

    print("可对比样本数      : %d" % checked)
    print("尺寸不一致        : %d" % size_mismatch)
    print("空掩码（全黑）    : %d  (%.1f%%)" % (empty, 100.0 * empty / max(checked, 1)))
    print("")
    print("结论：%s" % ("通过" if (not only_img and not only_msk and size_mismatch == 0) else "有问题，需要人工复核"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
