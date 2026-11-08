"""生成示例 CSV：约 200 行，故意混入缺失值、重复行与混合类型。

用法：python examples/make_fixtures.py [--out PATH] [--rows 200]
产物通过 .gitignore 排除，不入库。
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

HEADER = ["user_id", "name", "city", "age", "signup_date", "amount", "status"]
CITIES = ["BeiJing", "ShangHai", "ShenZhen", "HangZhou", "ChengDu", "WuHan"]
STATUS = ["active", "inactive", "pending"]
NAMES = ["Li Wei", "Wang Fang", "Zhang Min", "Liu Yang", "Chen Jie", "Zhao Lei", "Sun Yu"]
AGE_NOISE = ["unknown", "", "N/A"]
AMOUNT_NOISE = ["N/A", "1,200", "12.50"]
DEFAULT_ROWS = 200
DEFAULT_SEED = 20261108
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "examples" / "data" / "raw_users.csv"


def build_rows(count: int = DEFAULT_ROWS, seed: int = DEFAULT_SEED) -> list[dict[str, str]]:
    """生成 count 行示例数据（含缺失/重复/混合类型）。"""
    rng = random.Random(seed)
    rows: list[dict[str, str]] = []
    for index in range(1, count + 1):
        age = rng.randint(18, 65)
        amount = round(rng.uniform(10.0, 990.0), 2)
        row = {
            "user_id": f"U{index:04d}",
            "name": rng.choice(NAMES),
            "city": rng.choice(CITIES),
            "age": str(age),
            "signup_date": f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "amount": f"{amount:.2f}",
            "status": rng.choice(STATUS),
        }
        # 缺失值：约 8% 的行缺 age 或 city
        if rng.random() < 0.08:
            row["age"] = ""
        if rng.random() < 0.05:
            row["city"] = ""
        # 混合类型：少量行用文本噪声冒充数字
        if rng.random() < 0.04:
            row["age"] = rng.choice(AGE_NOISE)
        if rng.random() < 0.05:
            row["amount"] = rng.choice(AMOUNT_NOISE)
        rows.append(row)
    # 重复行：把最后 8 行替换成前面行的副本
    if count > 16:
        for offset in range(8):
            rows[count - 1 - offset] = dict(rows[offset])
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    """按固定列序写出 CSV（UTF-8，无 BOM）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in HEADER})
    return path


def summarise(rows: list[dict[str, str]]) -> dict[str, int]:
    """统计缺失单元格、重复行数，供控制台展示。"""
    missing = sum(
        1 for row in rows for key in HEADER if row.get(key) in (None, "")
    )
    seen: set[tuple[str, ...]] = set()
    duplicates = 0
    for row in rows:
        key = tuple(row.get(column, "") for column in HEADER)
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
    return {"rows": len(rows), "missing_cells": missing, "duplicate_rows": duplicates}


def main(argv: list[str] | None = None) -> int:
    """命令行入口：生成 fixtures 并打印 ASCII 摘要。"""
    parser = argparse.ArgumentParser(description="Generate the example CSV fixtures.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output csv path")
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS, help="row count")
    args = parser.parse_args(argv)
    if args.rows <= 0:
        print("error: --rows must be positive", file=sys.stderr)
        return 2
    rows = build_rows(count=args.rows)
    target = write_csv(Path(args.out), rows)
    stats = summarise(rows)
    print(f"wrote {target.resolve()}")
    rows_out = [
        (key, str(stats[key])) for key in ("rows", "missing_cells", "duplicate_rows")
    ]
    width = max(len("metric"), *(len(key) for key, _ in rows_out))
    value_width = max(len("value"), *(len(value) for _, value in rows_out))
    border = "+" + "-" * (width + 2) + "+" + "-" * (value_width + 2) + "+"
    print(border)
    print(f"| {'metric':<{width}} | {'value':<{value_width}} |")
    print(border)
    for key, value in rows_out:
        print(f"| {key:<{width}} | {value:<{value_width}} |")
    print(border)
    return 0


if __name__ == "__main__":
    sys.exit(main())
