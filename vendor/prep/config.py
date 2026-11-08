# -*- coding: utf-8 -*-
"""路径配置：数据根目录优先读环境变量，未设置时取仓库旁的 dataset/ 目录。"""
import os

# 原始数据根目录（不含数据本身，脚本只读不写）
# 取值顺序：
#   1) 环境变量 BLADE_DATASET_ROOT
#   2) 仓库目录下的 dataset/（把 AEBIS 数据放在这里即可）
_REPO_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_ROOT = os.environ.get("BLADE_DATASET_ROOT") or os.path.join(_REPO_DIR, "dataset")

# Labelme 多边形标注（每张图一个 json）
LABELME_DIR = os.path.join(DATASET_ROOT, "Dataset", "航空发动机叶片数据集")

# 已经转换好的 587 张训练数据（Train 528 / Test 59）
DATA587_DIR = os.path.join(DATASET_ROOT, "data_587")

# 类别合并规则：原始 7 类缺陷 -> 统一成 1 类缺陷
# 合并依据：Crack(33) / Nick(21) / Tip curl(30) 样本量过低，单独成类学不动且拉低整体指标
KEEP_CLASSES = None          # None = 全部保留原类别
MERGED_CLASS_NAME = "defect" # 合并后的类名
