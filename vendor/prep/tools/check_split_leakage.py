# -*- coding: utf-8 -*-
"""训练/测试集泄漏检查。

数据泄漏 = 同一个样本（或几乎一样的图）同时出现在训练集和测试集，
模型等于提前见过答案，测试分数虚高。

两层检查：
  1. 精确重复：文件 md5 相同
  2. 近似重复：转成 16x16 灰度做平均哈希，汉明距离 <= 阈值即判为近似
     （同一片叶片换角度拍、或做了翻转增强后又被分到另一侧，都会被抓出来）

用法:
    python tools/check_split_leakage.py
"""
import argparse
import glob
import hashlib
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402


def md5_of(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def ahash(path, size=16):
    with Image.open(path) as im:
        g = im.convert("L").resize((size, size), Image.BILINEAR)
        px = list(g.getdata())
    avg = sum(px) / len(px)
    return "".join("1" if v >= avg else "0" for v in px)


def hamming(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


def collect(split, root):
    d = os.path.join(root, split, "JPEGImages")
    out = []
    for ext in (".jpg", ".jpeg", ".png", ".bmp"):
        out.extend(sorted(glob.glob(os.path.join(d, "*" + ext))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=config.DATA587_DIR)
    ap.add_argument("--threshold", type=int, default=4, help="汉明距离阈值，越小越严")
    args = ap.parse_args()

    train, test = collect("Train", args.root), collect("Test", args.root)
    print("Train 图像数       : %d" % len(train))
    print("Test  图像数       : %d" % len(test))

    train_md5 = {md5_of(p): p for p in train}
    exact = [(p, train_md5[md5_of(p)]) for p in test if md5_of(p) in train_md5]
    print("精确重复（md5）    : %d" % len(exact))
    for t, tr in exact[:5]:
        print("   test/%s  ==  train/%s" % (os.path.basename(t), os.path.basename(tr)))

    train_hash = [(ahash(p), p) for p in train]
    near = []
    for tp in test:
        th = ahash(tp)
        for hh, trp in train_hash:
            if hamming(th, hh) <= args.threshold:
                near.append((tp, trp, hamming(th, hh)))
                break
    print("近似重复（阈值 %d）: %d" % (args.threshold, len(near)))
    for t, tr, d in near[:5]:
        print("   test/%s  ~  train/%s  (距离 %d)" % (os.path.basename(t), os.path.basename(tr), d))
    print("")
    print("结论：%s" % ("未发现跨集合泄漏" if (not exact and not near) else "存在跨集合重复，需要在划分前先做去重"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
